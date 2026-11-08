# Optional OCR preparation for editable-text VTracer SVGs

This experimental companion tool makes it easier to convert illustrated,
lettered raster images (e.g. mindmaps) into an SVG with editable text.
It **does not change the Rust VTracer core** and does not require an OCR engine
for normal tracing.

The processing chain is:

1. **OCR:** Tesseract finds text, bounding boxes and confidence scores.
2. **Review outputs:** The script exports a TSV label list and a detailed JSON report.
3. **Optional background preparation:** OpenCV inpaints high-confidence word
   rectangles in a **copy** of the image and saves a separate PNG of the mask.
4. **SVG composition:** The existing VTracer CLI `--text-file` feature can
   combine the cleaned illustration with actual editable SVG `<text>` objects.

**This is an assisted workflow, not a fully accurate automatic converter.**
Tesseract can misread German words, drawings can be mistaken for text, and
rectangular inpainting may remove lines or damage nearby illustrations.
A high OCR confidence is **not** proof of correctness. Verify every label,
position, color and masked region before accepting the SVG.

## Requirements

- Python 3.10+.
- A system installation of [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
  with the `deu` (German) and/or `eng` (English) language data.
- `opencv-python-headless` and its NumPy dependency for background inpainting.
  If only `--no-inpaint` is used, OpenCV is not needed.
- VTracer with the optional `--text-file` enhancement from the
  `feature/editable-svg-text` branch (currently a development feature, **not**
  included in the standard released VTracer version).

Example installation on Ubuntu/Debian:

```sh
sudo apt-get install tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng
python -m pip install opencv-python-headless
```

## Usage

```sh
python tools/ocr/prepare_text_layer.py input.png --lang deu+eng \
  --confidence 75 --padding 2

# Review and manually correct input.labels.tsv, input.ocr.json and
# input.cleaned.mask.png. Inspect input.cleaned.png before tracing.
vtracer input.cleaned.png output.svg --text-file input.labels.tsv
```

The script writes files next to the original:

| Output | Description |
| --- | --- |
| `input.labels.tsv` | Editable text rows for VTracer's `--text-file`. |
| `input.ocr.json` | Text, confidence, individual word rectangles, warnings and skipped words. |
| `input.cleaned.png` | Copy of the input with recognized text rectangles inpainted. |
| `input.cleaned.mask.png` | Review image showing which pixels were masked. |

**Important:** Each TSV row's `y` is estimated from the bottom of an OCR text
box, not from an exact typographic baseline. Default font family is
`Comic Sans MS, Comic Neue, cursive`, but OCR **does not identify the original
font**, font size, style or text color. These are initial defaults only.

Use `--no-inpaint` to export only the labels and the JSON report without
cleaning the original illustration. Use `--psm 11` (default) for sparse
mindmap lettering, or experiment with other Tesseract page-segmentation modes.
Increase `--confidence` to reduce low-confidence insertions, but note that
unrecognized words will still be visible as paths in the traced input unless
they are manually removed. Skipped words are listed in the JSON report.

## Example workflow with manual correction

1. Run the script with `--no-inpaint` to evaluate text recognition without
   removing any pixels.
2. Open the JSON report and verify every recognized word and skipped word.
3. Run again with inpainting enabled and review the cleaned PNG and mask
   *side by side* against the original.
4. Correct text/position/font in the TSV before composing the SVG.
5. Trace the cleaned image; check all text remains editable (SVG `<text>`), all
   illustrations remain complete, and no original raster is embedded.

Original files are never overwritten. If an output path equals the source
path, the script stops with an error.

## Development tests

```sh
python -m unittest discover -s tools/ocr/tests -v
```

Tests cover TSV grouping, confidence filtering, non-destructive file handling,
and a small real Tesseract/OpenCV image test. The OCR-specific GitHub Actions
workflow also installs the needed optional dependencies and runs these tests.

## Design boundaries

- The **core tracing engine** has no Tesseract, OpenCV, Python or OCR dependency.
- The companion script is intentionally separate, so maintainers can decide
  independently whether to include or distribute it.
- Future improvements could use pixel-accurate glyph segmentation rather than
  full word rectangles, add OCR alternatives, or offer human-in-the-loop
  correction via a GUI. These are not part of this prototype.