"""Build an allowlisted convenience ZIP with freshly generated synthetic media."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

from make_demo import make_demo
from talkbatch import VERSION

FILES = (
    "LICENSE", "README.md", "talkbatch.py", "make_demo.py", "test_talkbatch.py",
    "browser_smoke.py", "package.py", "index.html", "planner.js", "style.css", "pyproject.toml",
)


def build(output, screenshot=None):
    root = Path(__file__).resolve().parent
    contents = {name: (root / name).read_bytes() for name in FILES}
    with tempfile.TemporaryDirectory() as folder:
        source, _ = make_demo(Path(folder) / "demo")
        contents["demo/synthetic-source.webm"] = source.read_bytes()
        contents["demo/demo-plan.json"] = (source.parent / "demo-plan.json").read_bytes()
    if screenshot is not None:
        image = Path(screenshot).read_bytes()
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Screenshot must be a reviewed synthetic-only PNG.")
        contents["synthetic-planner.png"] = image
    manifest = {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in sorted(contents.items())}
    contents["CONTENTS.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    output = Path(output)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(contents.items()):
            entry = zipfile.ZipInfo(f"talkbatch-{VERSION}/{name}", (2026, 9, 21, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("ZIP integrity check failed.")
    return {"path": str(output), "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "entries": len(contents)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New ZIP path; existing files are refused.")
    parser.add_argument("--screenshot", type=Path, help="Only a reviewed screenshot of synthetic app data.")
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.screenshot), indent=2))
