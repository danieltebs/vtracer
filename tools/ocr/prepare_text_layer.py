#!/usr/bin/env python3
"""Optional Tesseract OCR bridge for VTracer's editable SVG text layer.

This tool does not change VTracer's Rust core and never changes the input PNG.
It emits a cleaned PNG, a TAB-separated editable-text layer, and a JSON report.
Detected text and inpainted backgrounds MUST be manually reviewed.

Requirements: Tesseract executable (with requested language packs), OpenCV.
Usage: python tools/ocr/prepare_text_layer.py input.png --lang deu+eng
       vtracer input.cleaned.png result.svg --text-file input.labels.tsv
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

from image_processing import build_text_mask, enhanced_ocr_image, rescale_ocr_tsv


def parse_tesseract_tsv(tsv: str, min_confidence: float = 65.0) -> tuple[list[dict], list[dict]]:
    """Group confident TSV words into ordered text lines; retain skipped words.

    Coordinates use original PNG pixels. y is an *estimated* baseline (box
    bottom), not Tesseract's font baseline; precise position needs review.
    """
    groups: dict[tuple[str, ...], list[dict]] = {}
    skipped: list[dict] = []
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    needed = {"level", "page_num", "block_num", "par_num", "line_num", "left", "top", "width", "height", "conf", "text"}
    if not reader.fieldnames or not needed.issubset(reader.fieldnames):
        raise ValueError("Tesseract did not return the expected TSV format")
    for row in reader:
        if row.get("level") != "5":  # level 5 denotes individual words
            continue
        word = (row.get("text") or "").strip()
        if not word:
            continue
        try:
            confidence = float(row["conf"])
            x, y = int(row["left"]), int(row["top"])
            w, h = int(row["width"]), int(row["height"])
        except (ValueError, TypeError) as exc:
            raise ValueError("malformed word coordinates/confidence in Tesseract TSV") from exc
        item = {"text": word, "confidence": confidence, "x": x, "y": y, "width": w, "height": h}
        if confidence < min_confidence or w <= 0 or h <= 0 or not math.isfinite(confidence):
            skipped.append(item)
            continue
        key = tuple(row[k] for k in ("page_num", "block_num", "par_num", "line_num"))
        groups.setdefault(key, []).append(item)

    lines: list[dict] = []
    for words in groups.values():
        words.sort(key=lambda word: word["x"])
        left = min(w["x"] for w in words)
        top = min(w["y"] for w in words)
        right = max(w["x"] + w["width"] for w in words)
        bottom = max(w["y"] + w["height"] for w in words)
        lines.append({
            "text": " ".join(w["text"] for w in words),
            "x": left, "y": bottom, "top": top,
            "width": right - left, "height": bottom - top,
            "confidence": round(sum(w["confidence"] for w in words) / len(words), 2),
            "words": words,
        })
    lines.sort(key=lambda line: (line["top"], line["x"]))
    return lines, skipped


def labels_tsv(lines: list[dict], font_family: str, fill: str) -> str:
    """Emit labels using the VTracer CLI's x/y/size/text/font/fill TSV format."""
    result = ["# x\ty\tfont_size\ttext\tfont_family\tfill"]
    for line in lines:
        text = line["text"].replace("\t", " ").replace("\r", " ").replace("\n", " ")
        # Glyph boxes are typically lower than nominal font size; this is a
        # starting estimate and not automatic font identification.
        size = max(8, round(line["height"] * 1.2, 1))
        result.append(f'{line["x"]}\t{line["y"]}\t{size}\t{text}\t{font_family}\t{fill}')
    return "\n".join(result) + "\n"


def run_tesseract(path: Path, lang: str, psm: int, executable: str) -> str:
    # Arguments are passed as a list; no shell or untrusted command evaluation.
    cmd = [executable, str(path), "stdout", "-l", lang, "--psm", str(psm), "tsv"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=180)
    except FileNotFoundError as exc:
        raise RuntimeError("Tesseract is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Tesseract timed out after 180 seconds") from exc
    if result.returncode:
        raise RuntimeError("Tesseract failed: " + (result.stderr or result.stdout)[-500:])
    return result.stdout


def inpaint_image(source: Path, destination: Path, lines: list[dict], padding: int,
                  mode: str = "glyph", contrast: int = 24) -> dict:
    """Inpaint conservative glyph masks (or legacy rectangles) in a COPY."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("This mode requires opencv-python-headless and numpy") from exc

    src = cv2.imread(str(source), cv2.IMREAD_UNCHANGED)
    if src is None or src.dtype != np.uint8:
        raise RuntimeError("Cannot read image as 8-bit PNG/JPEG with OpenCV")
    alpha = None
    if len(src.shape) == 2:
        rgb = cv2.cvtColor(src, cv2.COLOR_GRAY2BGR)
    elif src.shape[2] == 4:
        rgb, alpha = src[:, :, :3].copy(), src[:, :, 3].copy()
    elif src.shape[2] == 3:
        rgb = src.copy()
    else:
        raise RuntimeError("Only gray, RGB, and RGBA images are supported")
    height, width = rgb.shape[:2]
    mask, audit = build_text_mask(rgb, lines, padding, mode=mode, contrast=contrast)
    cleaned = cv2.inpaint(rgb, mask, 3, cv2.INPAINT_TELEA) if mask.any() else rgb
    if alpha is not None:
        cleaned = cv2.merge((*cv2.split(cleaned), alpha))
    if not cv2.imwrite(str(destination), cleaned):
        raise RuntimeError(f"Cannot write cleaned image to {destination}")
    mask_path = destination.with_name(destination.stem + ".mask.png")
    if not cv2.imwrite(str(mask_path), mask):
        raise RuntimeError(f"Cannot write OCR mask to {mask_path}")
    # A translucent red overlay reveals exactly what would be removed while
    # leaving every unmasked pixel identical to the original image.
    review_path = destination.with_name(destination.stem + ".review.png")
    review = rgb.copy()
    if mask.any():
        red = rgb.copy()
        red[:, :] = (20, 20, 255)  # BGR
        blended = cv2.addWeighted(rgb, 0.55, red, 0.45, 0)
        review[mask != 0] = blended[mask != 0]
    if not cv2.imwrite(str(review_path), review):
        raise RuntimeError(f"Cannot write OCR review image to {review_path}")
    return {"image_width": width, "image_height": height,
            "mask_path": str(mask_path), "review_path": str(review_path), **audit}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Original image (never modified)")
    parser.add_argument("--lang", default="deu+eng", help="Installed Tesseract languages")
    parser.add_argument("--psm", type=int, choices=range(3, 14), default=11,
                        metavar="3..13", help="Tesseract page segmentation mode (default: sparse text)")
    parser.add_argument("--confidence", type=float, default=65.0, help="Minimum word confidence, 0..100")
    parser.add_argument("--padding", type=int, default=2, help="Pixels around recognized glyphs / word boxes")
    parser.add_argument("--mask-mode", choices=("glyph", "box"), default="glyph",
                        help="Conservative glyph segmentation (default) or legacy full rectangles")
    parser.add_argument("--mask-contrast", type=int, default=24,
                        help="Minimum 8-bit per-channel difference from local background (5..120)")
    parser.add_argument("--ocr-preprocess", choices=("original", "enhanced"), default="original",
                        help="Use original image or temporary 2x grayscale CLAHE for low-contrast text")
    parser.add_argument("--font-family", default="Comic Sans MS, Comic Neue, cursive")
    parser.add_argument("--fill", default="#202020")
    parser.add_argument("--tesseract", default="tesseract", help="Tesseract executable")
    parser.add_argument("--no-inpaint", action="store_true", help="Write labels and report only; leave original image unchanged")
    parser.add_argument("--allow-empty", action="store_true", help="Permit zero detected text lines")
    parser.add_argument("--clean-image", type=Path, help="Destination cleaned PNG (default: input.cleaned.png)")
    parser.add_argument("--labels", type=Path, help="Destination TSV labels (default: input.labels.tsv)")
    parser.add_argument("--report", type=Path, help="Destination JSON report (default: input.ocr.json)")
    args = parser.parse_args(argv)
    if not 0 <= args.confidence <= 100 or not math.isfinite(args.confidence):
        parser.error("--confidence must be between 0 and 100")
    if not 0 <= args.padding <= 20:
        parser.error("--padding must be between 0 and 20")
    if not 5 <= args.mask_contrast <= 120:
        parser.error("--mask-contrast must be between 5 and 120")
    if any("\t" in v or "\n" in v or "\r" in v for v in (args.font_family, args.fill)):
        parser.error("Font family and fill must not contain tabs or newlines")
    if not args.input.is_file():
        parser.error(f"Input file does not exist: {args.input}")
    stem = args.input.with_suffix("")
    clean = args.clean_image or stem.with_name(stem.name + ".cleaned.png")
    labels = args.labels or stem.with_name(stem.name + ".labels.tsv")
    report = args.report or stem.with_name(stem.name + ".ocr.json")
    destinations = [labels, report] + ([] if args.no_inpaint else [
        clean, clean.with_name(clean.stem + ".mask.png"),
        clean.with_name(clean.stem + ".review.png")])
    if any(d.resolve() == args.input.resolve() for d in destinations) or len({d.resolve() for d in destinations}) != len(destinations):
        parser.error("Output paths must be distinct and must not overwrite the source image")
    try:
        if args.ocr_preprocess == "enhanced":
            with tempfile.TemporaryDirectory(prefix="vtracer_ocr_contrast_") as tmp:
                prepped = Path(tmp) / "enhanced.png"
                enhanced_ocr_image(args.input, prepped, scale=2.0)
                tsv = rescale_ocr_tsv(
                    run_tesseract(prepped, args.lang, args.psm, args.tesseract), 2.0
                )
        else:
            tsv = run_tesseract(args.input, args.lang, args.psm, args.tesseract)
        lines, skipped = parse_tesseract_tsv(tsv, args.confidence)
        if not lines and not args.allow_empty:
            raise RuntimeError("No confident OCR text found; inspect the source and language pack")
        stats = None if args.no_inpaint else inpaint_image(args.input, clean, lines, args.padding,
                                                            mode=args.mask_mode, contrast=args.mask_contrast)
        labels.write_text(labels_tsv(lines, args.font_family, args.fill), encoding="utf-8")
        result = {
            "source": str(args.input), "clean_image": None if args.no_inpaint else str(clean),
            "labels": str(labels), "language": args.lang, "psm": args.psm,
            "min_confidence": args.confidence, "line_count": len(lines),
            "ocr_preprocess": args.ocr_preprocess, "mask_mode": args.mask_mode,
            "skipped_word_count": len(skipped), "skipped_words": skipped,
            "lines": lines, "mask": stats,
            "warning": "OCR is fallible: review EVERY transcription, text position, color, and inpainted region. Original input is unchanged.",
        }
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Detected {len(lines)} text lines; skipped {len(skipped)} low-confidence words")
        print(f"Labels: {labels}\nReport: {report}")
        if not args.no_inpaint:
            print(f"Cleaned image: {clean}\nMask: {stats['mask_path']}\nReview overlay: {stats['review_path']}")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"OCR preparation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())