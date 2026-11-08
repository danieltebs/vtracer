# Optional OCR preparation for editable-text VTracer SVGs

This experimental companion tool makes it easier to convert illustrated,
lettered raster images (e.g. mindmaps) into an SVG with editable text.
It **does not change the Rust VTracer core** and does not require an OCR engine
for normal tracing.

The processing chain is:

1. **OCR:** Tesseract finds text, bounding boxes and confidence scores.
2. **Review outputs:** The script exports a TSV label list and a detailed JSON report.
3. **Optional background preparation:** OpenCV can segment likely **glyph pixels**
   (rather than erase every pixel in a word rectangle), using a locally fitted
   background color/gradient and conservative connected-component filtering.
   It creates a cleaned **copy**, a mask, and a red review overlay.
4. **SVG composition:** The existing VTracer CLI `--text-file` feature can
   combine the cleaned illustration with actual editable SVG `<text>` objects.

**This is an assisted workflow, not a fully accurate automatic converter.**
Tesseract can misread German words, drawings can be mistaken for text, and
even conservative glyph masks may leave letters or damage an illustration
that overlaps the text. Choose a text-free source for best results.
A high OCR confidence is **not** proof of correctness. Verify every label,
position, color and masked region before accepting the SVG.

## Requirements

- Python 3.10+.
- A system installation of [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
  with the `deu` (German) and/or `eng` (English) language data.
- `opencv-python-headless` and its NumPy dependency for background inpainting.
  If only `--no-inpaint` with the default `--ocr-preprocess original`
  is used, OpenCV is not needed.
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
  --confidence 75 --padding 2 --mask-mode glyph

# For low-contrast text on colorful backgrounds: run OCR on a temporary
# upscaled, contrast-enhanced grayscale image, returning coordinates in the
# *original* image's pixel system:
python tools/ocr/prepare_text_layer.py input.png --lang deu+eng \
  --ocr-preprocess enhanced --mask-mode glyph --confidence 75

# Review and manually correct input.labels.tsv, input.ocr.json and
# input.cleaned.mask.png. Inspect input.cleaned.png before tracing.
vtracer input.cleaned.png output.svg --text-file input.labels.tsv
```

The script writes files next to the original:

| Output | Description |
| --- | --- |
| `input.labels.tsv` | Editable text rows for VTracer's `--text-file`. |
| `input.ocr.json` | Text, confidence, individual word rectangles, warnings and skipped words. |
| `input.cleaned.png` | Copy of the input with selected text pixels inpainted. |
| `input.cleaned.mask.png` | Exact binary mask of removed pixels. |
| `input.cleaned.review.png` | Original illustration with removed pixels highlighted in translucent red. |

### Choosing a mask mode

- `--mask-mode glyph` (**default**) removes only likely letter strokes inside
  recognized word boxes. It estimates the local background from surrounding
  pixels, including smooth color gradients, and tries to preserve long colored
  illustration lines that cross word boxes. This is a **conservative** mode:
  some letter pixels may remain and must be removed manually or by further
  processing. OCR misses will never be removed.
- `--mask-mode box` is the original rectangular algorithm. It removes more
  pixels, but can erase connectors, colored textures or illustrations that
  happen to cross a recognized word box.
- `--mask-contrast 24` sets the minimum color difference from the estimated
  local background for candidate letter pixels (5–120). Decreasing it makes
  masking more aggressive and may harm illustrations.
- `--ocr-preprocess original` (**default**) runs OCR on the source as before.
  `--ocr-preprocess enhanced` runs Tesseract on a **temporary 2× enlarged,
  CLAHE contrast-enhanced grayscale image**. CLAHE adjusts local contrast;
  its OCR box coordinates are scaled back to original pixels before exporting.
  Enhanced OCR can sometimes improve faint text but can also create false
  positives. It does not change the original.

The JSON report now records the mode, the number of masked pixels, the
comparable full-rectangle area, the number of word boxes with no safe glyph
mask, and the paths to both mask and red review image. Reducing the mask size
is not by itself proof of perfect artwork preservation or text removal.

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
colored backgrounds, an illustration line crossing a word rectangle,
RGBA transparency, coordinate scaling, and real Tesseract/OpenCV image tests. The OCR-specific GitHub Actions
workflow also installs the needed optional dependencies and runs these tests.

## Design boundaries

- The **core tracing engine** has no Tesseract, OpenCV, Python or OCR dependency.
- The companion script is intentionally separate, so maintainers can decide
  independently whether to include or distribute it.
- The mask uses local contrast and connected components, not trained semantic
  segmentation. It cannot identify an illustration that looks like a character
  inside a word box or reliably protect every connector line. Improvements
  could add learned text segmentation, OCR alternatives, or a GUI for manual
  correction.