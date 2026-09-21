import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import talkbatch as tb
from make_demo import make_demo


def plan():
    return {"version": 1, "source": {"name": "source.webm"},
            "groups": [{"title": "Opening", "ranges": [[1, 2], [4.7, 5.7]]}]}


class PlanTests(unittest.TestCase):
    def test_valid_order_is_preserved(self):
        data = plan()
        data["groups"][0]["ranges"] = [[4.7, 5.7], [1, 2]]
        self.assertEqual(tb.validate_plan(data, 8), data)

    def test_bad_ranges_are_rejected(self):
        for cut in ([True, 2], [1, float("nan")], [1, float("inf")],
                    [-1, 2], [2, 2], [3, 2], ["1", 2], [0, 0.05], [1, 99], [1],
                    [1, 10 ** 1000]):
            with self.subTest(cut=cut):
                data = plan()
                data["groups"][0]["ranges"] = [cut]
                with self.assertRaises(tb.PlanError):
                    tb.validate_plan(data, 8)

    def test_schema_and_bounds(self):
        changes = [
            lambda p: p.update(version=True),
            lambda p: p.update(extra="ignored?"),
            lambda p: p.update(groups=[]),
            lambda p: p.update(groups=p["groups"] * 31),
            lambda p: p["source"].update(name="../private"),
            lambda p: p["source"].update(size=True),
            lambda p: p["groups"][0].update(title=""),
            lambda p: p["groups"][0].update(ranges=[[1, 2]] * 11),
            lambda p: p.update(groups=[{"title": "a", "ranges": [[1, 2]] * 10}] * 13),
        ]
        for change in changes:
            data = plan()
            change(data)
            with self.subTest(data=data), self.assertRaises(tb.PlanError):
                tb.validate_plan(data)

    def test_one_frame_decimal_range_is_not_lost_to_float_rounding(self):
        data = plan()
        data["groups"][0]["ranges"] = [[4.7, 4.8]]
        tb.validate_plan(data, 8)

    def test_filename_is_safe_numbered_and_predictable(self):
        self.assertEqual(tb.output_name(0, "../../Caf\u00e9 / Intro"), "001-cafe-intro.webm")
        self.assertEqual(tb.output_name(2, "..."), "003-untitled.webm")
        self.assertNotIn("/", tb.output_name(1, "a\\b / c"))

    def test_duplicate_keys_and_large_plans(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "plan.json"
            path.write_text('{"version":1,"version":1}', encoding="utf-8")
            with self.assertRaisesRegex(tb.PlanError, "Duplicate"):
                tb.load_plan(path)
            path.write_bytes(b" " * (tb.MAX_PLAN_BYTES + 1))
            with self.assertRaisesRegex(tb.PlanError, "1 MiB"):
                tb.load_plan(path)

    def test_filter_uses_validated_numeric_ranges_not_titles(self):
        graph = tb.filter_graph([[1, 2], [4.7, 5.7]], True)
        self.assertIn("trim=start=4.7:end=5.7", graph)
        self.assertIn("concat=n=2:v=1:a=1", graph)
        self.assertNotIn("asplit", tb.filter_graph([[1, 2]], False))

    def test_command_is_an_argument_list_with_no_overwrite_or_network_protocol(self):
        with patch("talkbatch.tool", return_value="/usr/bin/ffmpeg"):
            command = tb.encode_command(Path("/tmp/a ; echo bad.webm"), [[1, 2]], False,
                                        Path("/tmp/out.webm"))
        self.assertIn("/tmp/a ; echo bad.webm", command)
        self.assertIn("-n", command)
        self.assertNotIn("-y", command)
        self.assertEqual(command[command.index("-protocol_whitelist") + 1], "file,pipe")


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tb.check_tools()
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.source, cls.plan = make_demo(cls.root / "fixture")

    def frame_codes(self, path):
        raw = tb.run([tb.tool("ffmpeg"), "-v", "error", "-i", str(path), "-an",
                      "-pix_fmt", "gray", "-f", "rawvideo", "-fps_mode", "passthrough", "pipe:1"], 60)
        size = 160 * 96
        self.assertEqual(len(raw) % size, 0)
        return [sum((1 << bit) for bit in range(8)
                    if raw[offset + 48 * 160 + bit * 20 + 10] > 128)
                for offset in range(0, len(raw), size)]

    def test_exported_single_double_triple_and_off_keyframe_identity(self):
        self.assertEqual(self.frame_codes(self.source), list(range(120)))
        output = self.root / "exports"
        report = tb.export(self.source, self.plan, output, 90)
        expected = [list(range(10, 20)), list(range(30, 40)) + list(range(60, 70)),
                    list(range(5)) + list(range(47, 57)) + list(range(90, 100))]
        self.assertEqual(report["status"], "completed")
        for result, frames in zip(report["completed"], expected):
            self.assertEqual(self.frame_codes(output / result["file"]), frames)
            self.assertTrue(result["observed_media"]["audio"])
        self.assertEqual(json.loads((output / "report.json").read_text())["status"], "completed")
        with self.assertRaises(FileExistsError):
            tb.export(self.source, self.plan, output, 90)

    def test_silent_video_and_reordered_intervals(self):
        source, data = make_demo(self.root / "silent", audio=False)
        data["groups"] = [{"title": "Reordered", "ranges": [[8, 9], [1, 2]]}]
        out = self.root / "silent-out"
        report = tb.export(source, data, out, 90)
        self.assertFalse(report["completed"][0]["observed_media"]["audio"])
        self.assertEqual(self.frame_codes(out / report["completed"][0]["file"]),
                         list(range(80, 90)) + list(range(10, 20)))

    def test_mp4_mpeg4_aac_input(self):
        source = self.root / "synthetic-mpeg4.mp4"
        tb.run([tb.tool("ffmpeg"), "-v", "error", "-nostdin", "-n", "-i", str(self.source),
                "-c:v", "mpeg4", "-q:v", "2", "-g", "20", "-c:a", "aac", str(source)], 90)
        data = {"version": 1, "source": {"name": source.name},
                "groups": [{"title": "MP4 cut", "ranges": [[4.7, 5.7], [9, 10]]}]}
        out = self.root / "mp4-out"
        report = tb.export(source, data, out, 90)
        self.assertEqual(self.frame_codes(out / report["completed"][0]["file"]),
                         list(range(47, 57)) + list(range(90, 100)))

    def test_changed_source_and_duration_fail_before_output(self):
        data = copy.deepcopy(self.plan)
        data["source"]["size"] += 1
        with self.assertRaisesRegex(tb.PlanError, "size"):
            tb.export(self.source, data, self.root / "wrong-source")
        self.assertFalse((self.root / "wrong-source").exists())
        data = copy.deepcopy(self.plan)
        data["groups"][0]["ranges"] = [[1, 99]]
        with self.assertRaisesRegex(tb.PlanError, "duration"):
            tb.export(self.source, data, self.root / "wrong-range")
        self.assertFalse((self.root / "wrong-range").exists())

    def test_encode_failure_is_reported_and_not_retried(self):
        out = self.root / "failure"
        with patch("talkbatch.encode_command", return_value=["unused"]), \
                patch("talkbatch.run", wraps=tb.run) as run:
            def fail_encode(command, timeout, input_data=None):
                if command == ["unused"]:
                    raise tb.MediaError("synthetic encoder failure")
                return run._mock_wraps(command, timeout, input_data)
            run.side_effect = fail_encode
            with self.assertRaisesRegex(tb.MediaError, "synthetic"):
                tb.export(self.source, self.plan, out, 90)
        report = json.loads((out / "report.json").read_text())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["completed"], [])


if __name__ == "__main__":
    unittest.main()
