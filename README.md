# TalkBatch

**One recording -> an ordered queue of single- or multi-segment videos.**

TalkBatch is an **AI-authored, standalone, local-first preview** for repeated
grouped exports: a browser planner plus a standard-library Python exporter.
Give each output a title, collect its ranges, reorder the queue, and run one
export command. Outputs get stable numbered names such as
`001-opening.webm`, plus a machine-readable completion/failure report.

This is **not a LosslessCut plugin, not lossless stream-copy, and not a claim
that a standalone workflow replaces anyone's preferred native editor**.
It re-encodes VP9 video / Opus audio to avoid presenting off-keyframe copy
preroll as an exact cut. Paid demand and real conference-job suitability
are unvalidated. Examples are entirely synthetic, not customer work.

## Quick start

Requires **Python 3.10+**, **FFmpeg 6+ with `libvpx-vp9` and `libopus`**,
and **ffprobe** on your PATH. Install media tools separately from their
trusted distribution; no third-party binaries or Python packages are bundled.
A modern JavaScript-enabled browser is needed only for the planner.

1. Download/extract the source or convenience package.
2. Open `index.html` directly in your browser. No local server is needed.
3. Choose a local MP4, MOV, MKV or WebM. Add output cards and ranges.
   Use seconds, `MM:SS`, or `HH:MM:SS` with optional decimal seconds.
   The playhead buttons can mark in/out points when the browser can preview
   the codec. Manual entry also works.
4. Reorder outputs and ranges, then **Download validated plan**.
5. From a terminal, run (replace paths and use a **new** output directory):

```sh
python3 talkbatch.py --check
python3 talkbatch.py --source "/path/to/recording.webm" --plan "/path/to/plan.json" --dry-run
python3 talkbatch.py --source "/path/to/recording.webm" --plan "/path/to/plan.json" --output "/path/to/new-outputs"
```

On Windows use `python` if that is your Python command. Quote paths using
your shell's rules. Plans contain data, **not executable command lines**.
Python invokes FFmpeg with an argument list and never uses a shell.
The planner intentionally does not turn arbitrary filenames into shell snippets.

`--dry-run` probes the source and validates the queue; it does **not** test
encoding. Review a small real-media sample before committing to a long queue.

## A reproducible, synthetic example

```sh
python3 make_demo.py demo
python3 talkbatch.py --source demo/synthetic-source.webm --plan demo/demo-plan.json --output demo-output
```

The generator refuses an existing `demo` directory. It creates a 12-second,
160x96, 10fps source with frame-coded black/white stripes and a synthetic tone.
Open that source in the planner and load `demo/demo-plan.json` to edit it.

| Output | Ranges (seconds) | Planned duration | Expected decoded frame identities |
| --- | --- | --- | --- |
| Single range | 1-2 | 1s | 10-19 |
| Two ranges | 3-4, 6-7 | 2s | 30-39, 60-69 |
| Three ranges off-keyframe | 0-0.5, 4.7-5.7, 9-10 | 2.5s | 0-4, 47-56, 90-99 |

The integration tests decode those outputs and check the actual frame codes,
including the off-keyframe case. They also cover silent video, reordered
intervals and an MPEG-4 Part 2/AAC MP4 input. This small constant-frame-rate
fixture is **not** a guarantee for
every codec, variable-frame-rate file, audio offset, long recording or OS.
Audio presence is checked; comprehensive lip-sync/listening validation is not.

## Plan format

```json
{
  "version": 1,
  "source": {"name": "recording.webm"},
  "groups": [
    {"title": "Opening", "ranges": [[1, 2]]},
    {"title": "Panel", "ranges": [[3, 4], [6, 7]]}
  ]
}
```

Times are numeric seconds relative to the input timeline. The browser also
records size and, when available, duration. The exporter checks those against
the selected source; these are consistency checks, **not a content hash**.
Ranges join in listed order. Repeats and overlaps are allowed deliberately.
Group order determines numbering; nothing is silently sorted chronologically.
Titles are converted into bounded ASCII filenames. Duplicate titles remain
distinct because of their sequence numbers.

Limits: 1 MiB JSON plan; 1-30 groups; 1-10 ranges per group; at most 120 ranges
in total; minimum range 0.1s; video dimensions at most 4096px on each axis.
Unknown fields, duplicate JSON keys (CLI), non-finite values and invalid ranges
are errors, not silently repaired inputs.

## Export behavior and failure handling

- **Re-encoding changes quality and may change file size.** Outputs are WebM
  (VP9/Opus), not MP4. Codec/container preservation is not offered.
- Only the **first video stream and first audio stream** are used.
  Additional audio tracks, subtitles, chapters and source metadata are dropped.
  A first video stream that is only an attached cover image is rejected.
- Odd dimensions may be padded by one pixel. Cuts are constrained by actual
  frame timestamps; sub-frame precision, VFR equivalence and perfect audio
  synchronization are not guaranteed.
- Export checks the resulting codecs/stream presence and container duration
  within 0.25s of the planned duration. That is a sanity check, **not** proof
  of correct frame content or speech synchronization on your file.
- No hardware acceleration or fast input seek is assumed. Each group can
  decode substantial input again; this preview may be slow on long/high-res
  recordings. Default timeout is **3600s per group**; `--timeout` accepts
  1-86400 seconds. Adjust only after assessing your machine and source.
- An existing output directory is refused. A fresh private output directory
  receives completed files and `report.json`. During encoding the current
  file has a `.partial.webm` suffix.
- Failures stop the queue with a nonzero exit status and a failed/interrupted
  report. Completed files remain; a partial file may remain for diagnosis
  and must not be treated as a finished export. There is no automatic retry,
  resume, deletion of your media or overwriting of a prior output directory.

Use original media you trust and have permission to process. FFmpeg is a
third-party decoder, not a security sandbox. Keep it updated.

## Privacy and offline use

The downloaded planner reads a user-selected file through a browser-local
blob URL. No upload, account, external script, analytics, model call or cloud
processing is used. Its CSP disallows application network connections.
The Python exporter processes local files; input network protocols/playlists
are not enabled. No telemetry or automatic updates.

If an online preview is published, the host receives ordinary page/asset
requests; that does not upload the selected video. Download the files for
fully offline use. The source/feedback links are explicit outbound navigation.

Selected files/plans remain in browser memory until replaced or closed.
Plans, outputs and reports can contain filenames, titles and timing information.
Browser extensions, OS swap, download history, shared/network filesystems and
other software on your machine are outside this app's control. No secure
erasure or absolute privacy guarantee is made.

## Distribution and price hypothesis

The source is **free under MIT**, including the planner and exporter.
You may run it yourself without payment or an account.

The initial optional convenience-package price hypothesis is **US$9 once**:
the offline files, a pre-generated synthetic example and quick-start material.
It is not an exclusive license, a native installer, bundled FFmpeg, a hosted
service or a commitment to ongoing support. The same functionality is available
from source for free. No checkout is offered until a working link is explicitly
listed in the published release. Do not pay an unofficial or private-message link.

No purchase, customer savings or production-readiness claim is made.
This project is operated by an AI assistant under a human principal.

## Feedback and development

In a public issue, describe your OS, approximate duration/output count and
which repeatable step remains awkward. Use **synthetic** ranges/files only.
Do not post footage, private transcripts, customer data, credentials, payment
details or personal information. No paid customization is promised.

Core tests require the same media tools as export, but no Python packages:

```sh
python3 -m unittest -q test_talkbatch
```

`browser_smoke.py` is an optional developer check using Playwright and an
already installed Chromium. It uses an isolated **sandboxed headless** browser,
synthetic input, no existing user profile and no desktop capture.
This preview has been exercised on Linux; Windows/macOS behavior is unverified.
