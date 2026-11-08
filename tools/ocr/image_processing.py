"""Optional image preparation: contrast-enhanced OCR and conservative text masks.

This file imports OpenCV lazily: pure-text TSV processing needs no image stack.
The mask favors preserving nearby artwork over removing every possible glyph.
All decisions still require review by a person.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path


def enhanced_ocr_image(source: Path, destination: Path, scale: float = 2.0) -> None:
    """Create a grayscale, locally contrast-enhanced *temporary* OCR image.

    Original RGB pixel positions are recovered by rescaling the OCR TSV. An
    alpha channel is composited against white for OCR only; it is not edited.
    """
    import cv2
    import numpy as np

    src = cv2.imread(str(source), cv2.IMREAD_UNCHANGED)
    if src is None or src.dtype != np.uint8:
        raise RuntimeError("OCR enhancement requires a readable 8-bit image")
    if src.ndim == 2:
        gray = src
    elif src.shape[2] == 4:
        alpha = src[:, :, 3:4].astype(np.float32) / 255
        bgr = np.clip(src[:, :, :3].astype(np.float32) * alpha + 255 * (1 - alpha), 0, 255).astype(np.uint8)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    elif src.shape[2] == 3:
        gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
    else:
        raise RuntimeError("Only grayscale, RGB, and RGBA images are supported")
    local = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8)).apply(gray)
    if scale != 1:
        local = cv2.resize(local, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if not cv2.imwrite(str(destination), local):
        raise RuntimeError(f"Cannot write temporary OCR image: {destination}")


def rescale_ocr_tsv(tsv: str, scale: float) -> str:
    """Convert Tesseract box coordinates on an enlarged image back to source pixels."""
    if scale <= 0:
        raise ValueError("OCR image scale must be positive")
    if scale == 1:
        return tsv
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    if not reader.fieldnames or not {"left", "top", "width", "height"}.issubset(reader.fieldnames):
        raise ValueError("Invalid Tesseract TSV for scaling")
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=reader.fieldnames, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for row in reader:
        for field in ("left", "top", "width", "height"):
            try:
                number = float(row[field])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid Tesseract {field} field") from exc
            row[field] = str(max(0 if field in ("left", "top") else 1, round(number / scale)))
        writer.writerow(row)
    return stream.getvalue()


def build_text_mask(rgb, lines: list[dict], padding: int, mode: str = "glyph", contrast: int = 24):
    """Return a mask and audit statistics. rgb is an 8-bit BGR array.

    - box: backwards-compatible full OCR word rectangles.
    - glyph: local median-background contrast and connected-component filtering
      inside each OCR word box. Components extending outside the word box are
      treated as possible illustration lines and are *not* deleted.

    Conservative output may leave some letter pixels in the artwork. This is
    intentional: an overzealous mask can destroy irreplaceable illustrations.
    """
    import cv2
    import numpy as np

    height, width = rgb.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    rectangular = np.zeros_like(mask)
    ignored = 0
    for line in lines:
        for word in line["words"]:
            x, y = int(word["x"]), int(word["y"])
            w, h = int(word["width"]), int(word["height"])
            if w <= 0 or h <= 0:
                ignored += 1
                continue
            left, top = max(0, x - padding), max(0, y - padding)
            right, bottom = min(width, x + w + padding), min(height, y + h + padding)
            if left >= right or top >= bottom:
                ignored += 1
                continue
            rectangular[top:bottom, left:right] = 255
            if mode == "box":
                mask[top:bottom, left:right] = 255
                continue
            if mode != "glyph":
                raise ValueError(f"Unknown mask mode: {mode}")
            # Padding around the region is required so the median background
            # estimator sees the *surroundings*, not just a word's dark ink.
            margin = max(10, min(40, round(h * 0.9)))
            rx0, ry0 = max(0, x - margin), max(0, y - margin)
            rx1, ry1 = min(width, x + w + margin), min(height, y + h + margin)
            patch = rgb[ry0:ry1, rx0:rx1]
            min_dim = min(patch.shape[:2]); kernel = min(51, max(13, (round(h * 1.2) | 1)))
            if kernel > min_dim:
                kernel = min_dim if min_dim % 2 else min_dim - 1
            if kernel < 3:
                ignored += 1
                continue
            background = cv2.medianBlur(patch, kernel)
            # Fit a smooth color/gradient background from pixels *outside* the
            # OCR box, avoiding ink inside the box. This catches wide strokes
            # that survive median filtering (e.g. large mindmap titles).
            ph, pw = patch.shape[:2]
            ys, xs = np.indices((ph, pw), dtype=np.float32)
            normx = (xs - pw / 2) / max(pw, 1)
            normy = (ys - ph / 2) / max(ph, 1)
            features = np.stack((np.ones_like(xs), normx, normy), axis=-1)
            border = np.ones((ph, pw), dtype=bool)
            border[max(0, y - ry0):min(ph, y + h - ry0),
                   max(0, x - rx0):min(pw, x + w - rx0)] = False
            bg_estimate = background.astype(np.float32)
            if np.count_nonzero(border) >= 30:
                a = features[border]
                b = patch[border].astype(np.float32)
                keep = np.ones(b.shape[0], dtype=bool)
                try:
                    for _ in range(3):
                        if np.count_nonzero(keep) < 30:
                            break
                        beta = np.linalg.lstsq(a[keep], b[keep], rcond=None)[0]
                        errors = np.max(np.abs(a @ beta - b), axis=1)
                        keep = errors < max(30, contrast * 1.5)
                    bg_estimate = np.clip(features @ beta, 0, 255)
                except np.linalg.LinAlgError:
                    # Tiny or degenerate ROIs use the median estimate instead.
                    pass
            # Per-channel color contrast detects dark, light and colored ink.
            residual = np.max(np.abs(patch.astype(np.float32) - bg_estimate), axis=2)
            candidate = (residual >= contrast).astype(np.uint8)
            count, cc, stats, _ = cv2.connectedComponentsWithStats(candidate, 8)
            local = np.zeros(candidate.shape, np.uint8)
            allowed_x0, allowed_y0 = left - rx0, top - ry0
            allowed_x1, allowed_y1 = right - rx0, bottom - ry0
            for idx in range(1, count):
                cx, cy, cw, ch, area = (int(v) for v in stats[idx])
                if area < 2:
                    continue
                # A crossing drawing line usually continues beyond a word's
                # bounding box; preserve the whole component instead of using
                # an intersection crop that would cut the line in half.
                if (cx < allowed_x0 or cy < allowed_y0 or
                    cx + cw > allowed_x1 or cy + ch > allowed_y1):
                    continue
                if cx + cw <= x - rx0 or cy + ch <= y - ry0 or cx >= x + w - rx0 or cy >= y + h - ry0:
                    continue
                if area > (right - left) * (bottom - top) * 0.55:
                    continue
                local[cc == idx] = 255
            if not local.any():
                ignored += 1
                continue
            # Cover antialiased glyph-edge pixels, but avoid extending the
            # accepted mask outside the documented OCR word bounds.
            local = cv2.dilate(local, np.ones((3, 3), np.uint8), iterations=1)
            target = mask[ry0:ry1, rx0:rx1]
            word_bounds = np.zeros_like(local)
            word_bounds[allowed_y0:allowed_y1, allowed_x0:allowed_x1] = 255
            cv2.bitwise_or(target, cv2.bitwise_and(local, word_bounds), dst=target)
    n_masked = int(np.count_nonzero(mask))
    n_rectangle = int(np.count_nonzero(rectangular))
    return mask, {
        "mode": mode,
        "contrast_threshold": contrast if mode == "glyph" else None,
        "masked_pixels": n_masked,
        "rectangle_pixels": n_rectangle,
        "pixels_preserved_vs_rectangles": n_rectangle - n_masked,
        "mask_reduction_percent": round(100 * (1 - n_masked / n_rectangle), 1) if n_rectangle else 0,
        "words_without_safe_mask": ignored,
        "warning": "Review the mask and cleaned image: thin/low-contrast letters may remain, and internal illustrations can still be erased.",
    }