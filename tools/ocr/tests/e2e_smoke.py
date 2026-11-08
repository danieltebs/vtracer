#!/usr/bin/env python3
"""End-to-end smoke test: Tesseract -> cleaned PNG -> VTracer editable SVG.

Run from repo checkout with Tesseract, OpenCV, and the Rust toolchain installed.
No user-supplied image is stored in the repository.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from xml.etree import ElementTree as ET

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_text_layer import main as prepare


def main() -> None:
    root = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="vtracer-ocr-e2e-") as tmp:
        work = Path(tmp)
        original = work / "example.png"
        cleaned = work / "example.cleaned.png"
        label_file = work / "example.labels.tsv"
        out_svg = work / "example.svg"
        report = work / "example.ocr.json"

        image = np.full((180, 570, 3), 255, dtype=np.uint8)
        cv2.putText(image, "Wald und Baum", (20, 100), cv2.FONT_HERSHEY_SIMPLEX,
                    1.8, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.circle(image, (500, 122), 28, (25, 130, 230), -1)
        assert cv2.imwrite(str(original), image), "could not create test PNG"
        before = original.read_bytes()

        code = prepare([
            str(original), "--lang", "eng", "--psm", "6",
            "--confidence", "40", "--labels", str(label_file),
            "--clean-image", str(cleaned), "--report", str(report),
        ])
        assert code == 0, f"OCR preprocessing failed: {code}"
        assert original.read_bytes() == before, "original image was changed"
        assert json.loads(report.read_text())["line_count"] > 0

        subprocess.run([
            "cargo", "run", "--quiet", "-p", "vtracer-cli", "--",
            str(cleaned), str(out_svg), "--text-file", str(label_file),
        ], cwd=root, check=True, timeout=240)

        ns = {"svg": "http://www.w3.org/2000/svg"}
        tree = ET.parse(out_svg)
        root_tag = tree.getroot()
        paths = root_tag.findall(".//svg:path", ns)
        labels = root_tag.findall(".//svg:text", ns)
        images = root_tag.findall(".//svg:image", ns)
        assert paths, "no vector paths in generated SVG"
        assert labels, "no editable <text> elements in generated SVG"
        assert not images, "output unexpectedly embeds raster images"
        assert "Wald" in "".join("".join(t.itertext()) for t in labels), \
            "recognized label missing in generated SVG"
        print(f"PASS: {len(paths)} paths, {len(labels)} editable text elements, no embedded raster images")


if __name__ == "__main__":
    main()
