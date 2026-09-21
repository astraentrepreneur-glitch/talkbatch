"""Create a wholly synthetic 12-second source and a three-group example plan."""

import argparse
import json
from pathlib import Path

from talkbatch import check_tools, run, tool


def make_demo(directory, audio=True):
    check_tools()
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    source = directory / "synthetic-source.webm"
    frames = []
    for index in range(120):
        row = b"".join(bytes([235 if index & (1 << bit) else 16]) * 20 for bit in range(8))
        frames.append(row * 96)
    command = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
               "-f", "rawvideo", "-pix_fmt", "gray", "-s", "160x96", "-r", "10", "-i", "pipe:0"]
    if audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=12",
                    "-c:a", "libopus"]
    command += ["-c:v", "libvpx-vp9", "-lossless", "1", "-g", "20",
                "-threads", "2", "-pix_fmt", "yuv420p", "-shortest", str(source)]
    run(command, 90, b"".join(frames))
    plan = {
        "version": 1, "source": {"name": source.name, "size": source.stat().st_size},
        "groups": [
            {"title": "Single range", "ranges": [[1, 2]]},
            {"title": "Two ranges", "ranges": [[3, 4], [6, 7]]},
            {"title": "Three ranges off-keyframe", "ranges": [[0, 0.5], [4.7, 5.7], [9, 10]]},
        ],
    }
    (directory / "demo-plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return source, plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="demo")
    args = parser.parse_args()
    source, _ = make_demo(args.directory)
    print(f"Created synthetic data only: {source}")

