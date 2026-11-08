"""Regression tests for colored backgrounds and artwork-safe masking."""
from __future__ import annotations

import io
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from image_processing import build_text_mask, enhanced_ocr_image, rescale_ocr_tsv
from prepare_text_layer import inpaint_image, main


class ArtworkSafeMaskTest(unittest.TestCase):
    def make_image(self):
        h, w = 200, 520
        img = np.zeros((h, w, 3), dtype=np.uint8)
        # Smooth color gradient, rather than a white background.
        img[:, :, 0] = np.linspace(150, 190, w).astype(np.uint8)[None, :]
        img[:, :, 1] = np.linspace(180, 145, h).astype(np.uint8)[:, None]
        img[:, :, 2] = np.linspace(190, 205, w).astype(np.uint8)[None, :]
        cv2.putText(img, "Wald und Baum", (62, 115), cv2.FONT_HERSHEY_SIMPLEX,
                    1.45, (20, 30, 30), 3, cv2.LINE_AA)
        # Colorful illustration stroke crosses the *recognized word box*.
        cv2.line(img, (15, 82), (480, 82), (20, 50, 205), 2, cv2.LINE_AA)
        lines = [{"words": [{"x": 62, "y": 78, "width": 320, "height": 43}]}]
        return img, lines

    def test_colored_gradient_preserves_crossing_illustration(self):
        img, lines = self.make_image()
        glyph, stats = build_text_mask(img, lines, padding=2, mode="glyph")
        box, old = build_text_mask(img, lines, padding=2, mode="box")
        self.assertGreater(stats["masked_pixels"], 200)
        self.assertLess(stats["masked_pixels"], old["masked_pixels"] * 0.75)
        # Rectangular masking erases this picture line through the text area;
        # a connected-component mask protects the piece extending outside it.
        self.assertEqual(int(np.count_nonzero(glyph[82, 70:370])), 0)
        self.assertGreater(int(np.count_nonzero(box[82, 70:370])), 200)
        self.assertEqual(stats["rectangle_pixels"], old["masked_pixels"])

    def test_clean_copy_has_reduced_mask_and_keeps_source(self):
        img, lines = self.make_image()
        with tempfile.TemporaryDirectory() as tmp:
            src, dest = Path(tmp) / "src.png", Path(tmp) / "clean.png"
            self.assertTrue(cv2.imwrite(str(src), img))
            before = src.read_bytes()
            stats = inpaint_image(src, dest, lines, 2)
            self.assertEqual(src.read_bytes(), before)
            self.assertTrue(dest.exists())
            self.assertTrue((Path(tmp) / "clean.mask.png").exists())
            self.assertTrue((Path(tmp) / "clean.review.png").exists())
            self.assertLess(stats["masked_pixels"], stats["rectangle_pixels"])
            self.assertEqual(stats["mode"], "glyph")

    def test_alpha_channel_is_preserved(self):
        img, lines = self.make_image()
        alpha = np.repeat(np.linspace(0, 255, img.shape[1], dtype=np.uint8)[None, :], img.shape[0], axis=0)
        rgba = np.dstack((img, alpha))
        with tempfile.TemporaryDirectory() as tmp:
            src, dest = Path(tmp) / "rgba.png", Path(tmp) / "clean.png"
            self.assertTrue(cv2.imwrite(str(src), rgba))
            inpaint_image(src, dest, lines, 2)
            output = cv2.imread(str(dest), cv2.IMREAD_UNCHANGED)
            self.assertEqual(output.shape[2], 4)
            np.testing.assert_array_equal(output[:, :, 3], alpha)

    def test_enhancement_rescales_boxes_to_source_pixel_coordinates(self):
        tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
               "5\t1\t1\t1\t1\t1\t40\t60\t140\t52\t93\tWald\n")
        scaled = rescale_ocr_tsv(tsv, 2.0)
        self.assertIn("\t20\t30\t70\t26\t93\tWald", scaled)
        with self.assertRaises(ValueError):
            rescale_ocr_tsv(tsv, 0)
        img, _ = self.make_image()
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "src.png", Path(tmp) / "prepped.png"
            self.assertTrue(cv2.imwrite(str(src), img))
            before = src.read_bytes()
            enhanced_ocr_image(src, dst, 2.0)
            prepped = cv2.imread(str(dst), cv2.IMREAD_GRAYSCALE)
            self.assertEqual(prepped.shape, (400, 1040))
            self.assertEqual(src.read_bytes(), before)

    def test_enhanced_ocr_pipeline_writes_original_coordinate_labels(self):
        img, _ = self.make_image()
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "colored.png"
            cv2.imwrite(str(src), img)
            result = main([str(src), "--lang", "eng", "--psm", "6", "--confidence", "35",
                           "--ocr-preprocess", "enhanced", "--no-inpaint"])
            self.assertEqual(result, 0)
            import json
            report = json.loads((Path(tmp) / "colored.ocr.json").read_text())
            self.assertGreater(report["line_count"], 0)
            self.assertEqual(report["ocr_preprocess"], "enhanced")
            self.assertLess(report["lines"][0]["x"], img.shape[1])


if __name__ == "__main__":
    unittest.main()