"""TalkBatch: validate a local cut plan and export numbered WebM groups."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unicodedata

VERSION = "0.1.0"
MAX_PLAN_BYTES = 1024 * 1024
MAX_GROUPS = 30
MAX_RANGES = 10
MAX_TOTAL_RANGES = 120


class PlanError(ValueError):
    pass


class MediaError(RuntimeError):
    pass


def number(value, label):
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise PlanError(f"{label} must be a finite number, not a string or boolean.")
    return value


def keys(value, allowed, required, label):
    if not isinstance(value, dict):
        raise PlanError(f"{label} must be an object.")
    if set(value) - set(allowed) or set(required) - set(value):
        raise PlanError(f"{label} has missing or unknown fields.")


def slug(title):
    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", plain).strip("-").lower()[:60].rstrip("-") or "untitled"


def output_name(index, title):
    return f"{index + 1:03d}-{slug(title)}.webm"


def validate_plan(plan, duration=None):
    keys(plan, ("version", "source", "groups"), ("version", "source", "groups"), "Plan")
    if type(plan["version"]) is not int or plan["version"] != 1:
        raise PlanError("Only plan version 1 is supported.")
    source = plan["source"]
    keys(source, ("name", "size", "duration"), ("name",), "Source")
    name = source["name"]
    if (not isinstance(name, str) or not name or len(name) > 255
            or name in (".", "..") or any(c in name for c in "/\\\x00")
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise PlanError("Source name must be a filename, not a path.")
    if "size" in source and (type(source["size"]) is not int or source["size"] <= 0):
        raise PlanError("Source size must be a positive integer.")
    if "duration" in source and number(source["duration"], "Source duration") <= 0:
        raise PlanError("Source duration must be positive.")
    if duration is not None:
        if number(duration, "Media duration") <= 0:
            raise PlanError("Media duration must be positive.")
        if "duration" in source and abs(source["duration"] - duration) > 0.25:
            raise PlanError("Media duration differs from the plan. Review the source and plan.")
    groups = plan["groups"]
    if not isinstance(groups, list) or not 1 <= len(groups) <= MAX_GROUPS:
        raise PlanError(f"Use 1 to {MAX_GROUPS} output groups.")
    total = 0
    for i, group in enumerate(groups):
        label = f"Group {i + 1}"
        keys(group, ("title", "ranges"), ("title", "ranges"), label)
        title = group["title"]
        if (not isinstance(title, str) or not title.strip() or len(title) > 80
                or any(ord(c) < 32 or ord(c) == 127 for c in title)):
            raise PlanError(f"{label}: title must be 1 to 80 characters without control characters.")
        ranges = group["ranges"]
        if not isinstance(ranges, list) or not 1 <= len(ranges) <= MAX_RANGES:
            raise PlanError(f"{label}: use 1 to {MAX_RANGES} ranges.")
        total += len(ranges)
        for j, cut in enumerate(ranges):
            if not isinstance(cut, list) or len(cut) != 2:
                raise PlanError(f"{label}, range {j + 1}: expected [start, end] seconds.")
            start = number(cut[0], "Start")
            end = number(cut[1], "End")
            if start < 0 or end <= start or end - start < 0.1 - 1e-9:
                raise PlanError(f"{label}, range {j + 1}: require 0 <= start < end and at least 0.1s.")
            limit = duration if duration is not None else source.get("duration")
            if limit is not None and end > limit + 0.001:
                raise PlanError(f"{label}, range {j + 1}: end exceeds source duration.")
    if total > MAX_TOTAL_RANGES:
        raise PlanError(f"Use at most {MAX_TOTAL_RANGES} ranges across the plan.")
    return plan


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PlanError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def load_plan(path):
    with Path(path).open("rb") as stream:
        content = stream.read(MAX_PLAN_BYTES + 1)
    if len(content) > MAX_PLAN_BYTES:
        raise PlanError("Plan exceeds 1 MiB.")
    try:
        plan = json.loads(content, object_pairs_hook=unique_object)
    except PlanError:
        raise
    except (ValueError, UnicodeDecodeError) as error:
        raise PlanError("Plan must be valid UTF-8 JSON.") from error
    return validate_plan(plan)


def tool(name):
    executable = shutil.which(name)
    if not executable:
        raise MediaError(f"{name} is missing from PATH. Install FFmpeg 6+ with ffprobe.")
    return executable


def run(command, timeout, input_data=None):
    try:
        result = subprocess.run(command, input=input_data, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise MediaError(f"Media command exceeded {timeout}s; no automatic retry.") from error
    if result.returncode:
        details = result.stderr.decode("utf-8", "replace")[-4000:]
        details = "".join(c for c in details if c in "\n\t" or 32 <= ord(c) < 127)
        raise MediaError(f"Media command failed ({result.returncode}):\n{details}")
    return result.stdout


def check_tools():
    ffmpeg, ffprobe = tool("ffmpeg"), tool("ffprobe")
    encoders = run([ffmpeg, "-hide_banner", "-encoders"], 30).decode("utf-8", "replace")
    for encoder in ("libvpx-vp9", "libopus"):
        if not re.search(r"\b" + re.escape(encoder) + r"\b", encoders):
            raise MediaError(f"Your FFmpeg build lacks {encoder}; no codec silently substituted.")
    return {
        "ffmpeg": run([ffmpeg, "-version"], 30).decode().splitlines()[0],
        "ffprobe": run([ffprobe, "-version"], 30).decode().splitlines()[0],
    }


def probe(path):
    raw = run([tool("ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe",
               "-format_whitelist", "mov,matroska,webm", "-show_format", "-show_streams",
               "-of", "json", "-i", str(path)], 60)
    try:
        data = json.loads(raw)
        duration = float(data["format"]["duration"])
        streams = data["streams"]
        videos = [s for s in streams if s.get("codec_type") == "video"]
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        if not math.isfinite(duration) or duration <= 0 or not videos:
            raise ValueError("No usable duration/video")
        first = videos[0]
        if first.get("disposition", {}).get("attached_pic") == 1:
            raise ValueError("First video stream is an attached picture")
        width, height = first["width"], first["height"]
        if not 1 <= width <= 4096 or not 1 <= height <= 4096:
            raise ValueError("Video dimensions outside 1..4096 pixels")
    except (ValueError, KeyError, TypeError) as error:
        raise MediaError("Cannot determine supported video streams/duration (max 4096px per dimension).") from error
    return {"duration": duration, "width": width, "height": height,
            "audio": bool(audio), "video_codec": first.get("codec_name"),
            "audio_codec": audio[0].get("codec_name") if audio else None}


def prepare(source, plan):
    source = Path(source).expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in (".mp4", ".mov", ".mkv", ".webm"):
        raise PlanError("Source must be a local MP4, MOV, MKV or WebM file.")
    if source.name != plan["source"]["name"]:
        raise PlanError("Source filename differs from the plan.")
    if "size" in plan["source"] and source.stat().st_size != plan["source"]["size"]:
        raise PlanError("Source size differs from the plan.")
    metadata = probe(source)
    validate_plan(plan, metadata["duration"])
    return source, metadata


def decimal(value):
    return format(value, ".9f").rstrip("0").rstrip(".") or "0"


def filter_graph(ranges, audio):
    count = len(ranges)
    video_labels = "".join(f"[vs{i}]" for i in range(count))
    parts = [f"[0:v:0]split={count}{video_labels}"]
    if audio:
        parts.append(f"[0:a:0]asplit={count}" + "".join(f"[as{i}]" for i in range(count)))
    inputs = []
    for i, (start, end) in enumerate(ranges):
        times = f"start={decimal(start)}:end={decimal(end)}"
        parts.append(f"[vs{i}]trim={times},setpts=PTS-STARTPTS[v{i}]")
        inputs.append(f"[v{i}]")
        if audio:
            parts.append(f"[as{i}]atrim={times},asetpts=PTS-STARTPTS[a{i}]")
            inputs.append(f"[a{i}]")
    parts.append("".join(inputs) + f"concat=n={count}:v=1:a={int(audio)}[joined]" + ("[a]" if audio else ""))
    parts.append("[joined]pad=ceil(iw/2)*2:ceil(ih/2)*2,format=yuv420p[v]")
    return ";".join(parts)


def encode_command(source, ranges, audio, output):
    command = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
               "-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm",
               "-i", str(source), "-filter_complex", filter_graph(ranges, audio),
               "-map", "[v]"]
    if audio:
        command += ["-map", "[a]", "-c:a", "libopus", "-b:a", "96k"]
    command += ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0",
                "-cpu-used", "4", "-row-mt", "1", "-threads", "2", "-fps_mode", "vfr",
                "-map_metadata", "-1", "-map_chapters", "-1", "-sn", "-dn",
                "-f", "webm", str(output)]
    return command


def write_report(directory, report):
    temporary = directory / "report.json.tmp"
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=True, allow_nan=False)
        stream.write("\n")
    temporary.replace(directory / "report.json")


def export(source, plan, directory, timeout=3600):
    versions = check_tools()
    source, metadata = prepare(source, plan)
    directory = Path(directory).expanduser().resolve()
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    report = {"tool": "TalkBatch", "version": VERSION,
              "started_at": datetime.now(timezone.utc).isoformat(),
              "status": "running", "source": plan["source"], "source_media": metadata,
              "tools": versions, "plan": plan, "completed": [],
              "limitations": "Re-encoded VP9/Opus, not lossless. Review every output. First video/audio only."}
    write_report(directory, report)
    try:
        for i, group in enumerate(plan["groups"]):
            name = output_name(i, group["title"])
            temporary = directory / (name + ".partial.webm")
            print(f"Exporting {i + 1}/{len(plan['groups'])}: {name}", flush=True)
            run(encode_command(source, group["ranges"], metadata["audio"], temporary), timeout)
            result = probe(temporary)
            expected = sum(end - start for start, end in group["ranges"])
            if (result["video_codec"] != "vp9" or result["audio"] != metadata["audio"]
                    or (result["audio"] and result["audio_codec"] != "opus")
                    or abs(result["duration"] - expected) > 0.25):
                raise MediaError(f"{name}: output stream/duration check failed; partial retained.")
            temporary.rename(directory / name)
            report["completed"].append({"file": name, "title": group["title"],
                                        "ranges": group["ranges"], "expected_duration": expected,
                                        "observed_media": result})
            write_report(directory, report)
    except (OSError, MediaError, KeyboardInterrupt) as error:
        report["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        report["error"] = str(error) or "Interrupted by user."
        write_report(directory, report)
        raise
    report["status"] = "completed"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_report(directory, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--check", action="store_true", help="Check FFmpeg/ffprobe and required encoders.")
    parser.add_argument("--source", type=Path, help="Original local video file.")
    parser.add_argument("--plan", type=Path, help="JSON downloaded from the offline planner.")
    parser.add_argument("--output", type=Path, help="A NEW output directory; existing directories are refused.")
    parser.add_argument("--dry-run", action="store_true", help="Validate/probe without writing or encoding.")
    parser.add_argument("--timeout", type=int, default=3600, help="Per-group encoding timeout, 1..86400 seconds.")
    args = parser.parse_args(argv)
    try:
        if args.check:
            print(json.dumps(check_tools(), indent=2))
            return 0
        if args.source is None or args.plan is None or (args.output is None and not args.dry_run):
            parser.error("--source and --plan are required; export also requires --output.")
        if not 1 <= args.timeout <= 86400:
            parser.error("--timeout must be 1..86400 seconds.")
        plan = load_plan(args.plan)
        if args.dry_run:
            _, media = prepare(args.source, plan)
            print(json.dumps({"valid": True, "media": media, "outputs": [
                {"file": output_name(i, g["title"]), "ranges": g["ranges"],
                 "duration": sum(b - a for a, b in g["ranges"])}
                for i, g in enumerate(plan["groups"])], "encoding_not_tested": True}, indent=2))
        else:
            os.umask(0o077)
            report = export(args.source, plan, args.output, args.timeout)
            print(f"Completed {len(report['completed'])} outputs. Review them and report.json.")
        return 0
    except (PlanError, MediaError, OSError, KeyboardInterrupt) as error:
        print(f"TalkBatch stopped: {error or 'Interrupted by user.'}", file=sys.stderr)
        return 130 if isinstance(error, KeyboardInterrupt) else 1


if __name__ == "__main__":
    raise SystemExit(main())
