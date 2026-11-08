"""Standard-library tests; integration test uses installed Tesseract and OpenCV."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_text_layer import labels_tsv, main, parse_tesseract_tsv


HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
ROWS = (
    "5\t1\t1\t1\t1\t1\t11\t20\t25\t10\t94.1\tBäume\n"
    "5\t1\t1\t1\t1\t2\t41\t20\t30\t10\t90.0\t&\n"
    "5\t1\t1\t1\t1\t3\t74\t20\t32\t10\t92.0\tWald\n"
    "5\t1\t2\t1\t1\t1\t20\t80\t40\t15\t32.0\tunsicher\n"
)


class TsvParsingTest(unittest.TestCase):
    def test_group_words_and_filter_low_confidence(self):
        lines, skipped = parse_tesseract_tsv(HEADER + ROWS, min_confidence=65)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["text"], "Bäume & Wald")
        self.assertEqual(lines[0]["x"], 11)
        self.assertEqual(lines[0]["y"], 30)
        self.assertEqual(len(lines[0]["words"]), 3)
        self.assertEqual([w["text"] for w in skipped], ["unsicher"])

    def test_tsv_for_vtracer_cli(self):
        lines, _ = parse_tesseract_tsv(HEADER + ROWS)
        rendered = labels_tsv(lines, "Comic Sans MS", "#123456")
        self.assertIn("11\t30\t12.0\tBäume & Wald\tComic Sans MS\t#123456", rendered)
        self.assertEqual(rendered.count("\n"), 2)

    def test_reject_malformed_tesseract_tsv(self):
        with self.assertRaises(ValueError):
            parse_tesseract_tsv("not\ttsv\n")


class RealOcrTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("tesseract"), "Tesseract executable not installed")
    def test_cli_detects_and_masks_sample_without_changing_source(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV and numpy not installed")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / "example.png"
            img = np.full((180, 570, 3), 255, dtype=np.uint8)
            cv2.putText(img, "Wald und Baum", (20, 100), cv2.FONT_HERSHEY_SIMPLEX,
                        1.8, (0, 0, 0), 3, cv2.LINE_AA)
            self.assertTrue(cv2.imwrite(str(source), img))
            before = source.read_bytes()
            result = main([str(source), "--lang", "eng", "--psm", "6", "--confidence", "40"])
            self.assertEqual(result, 0)
            self.assertEqual(source.read_bytes(), before)
            labels = folder / "example.labels.tsv"
            report = json.loads((folder / "example.ocr.json").read_text(encoding="utf-8"))
            self.assertGreater(report["line_count"], 0)
            self.assertIn("Wald", labels.read_text(encoding="utf-8"))
            self.assertTrue((folder / "example.cleaned.png").is_file())
            self.assertTrue((folder / "example.cleaned.mask.png").is_file())
            self.assertGreater(report["mask"]["masked_pixels"], 0)

    @unittest.skipUnless(shutil.which("tesseract"), "Tesseract executable not installed")
    def test_non_destructive_labels_only(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV and numpy not installed")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "text.png"
            img = np.full((160, 510, 3), 255, dtype=np.uint8)
            cv2.putText(img, "Blume", (10, 100), cv2.FONT_HERSHEY_SIMPLEX,
                        2, (0, 0, 0), 3, cv2.LINE_AA)
            self.assertTrue(cv2.imwrite(str(source), img))
            result = main([str(source), "--lang", "eng", "--psm", "6", "--confidence", "30", "--no-inpaint"])
            self.assertEqual(result, 0)
            self.assertTrue((Path(tmp) / "text.labels.tsv").exists())
            self.assertFalse((Path(tmp) / "text.cleaned.png").exists())

    def test_never_overwrite_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            source.write_bytes(b"not an image")
            with self.assertRaises(SystemExit):
                main([str(source), "--clean-image", str(source)])
            self.assertEqual(source.read_bytes(), b"not an image")


if __name__ == "__main__":
    unittest.main()