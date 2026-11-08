# Editable SVG text overlay (experimental)

VTracer normally traces raster pixels into SVG paths. The optional editable-text
overlay preserves those paths and writes real SVG <text> elements above them.
This is especially useful for diagrams and illustrated mindmaps.

**Important:** This does **not** perform OCR (optical character recognition),
automatically detect text, or erase letters from a raster source. Before
tracing, provide an image from which rasterized lettering has already been
removed or masked. Otherwise the result will contain the old raster lettering
as paths *and* the editable text on top of it.

## Command-line usage

Prepare a UTF-8, tab-separated file (actual TAB characters, not spaces).
Each nonempty, noncomment row has these columns:

| Column | Meaning | Required |
| --- | --- | --- |
| 1 | x position in image pixels | yes |
| 2 | y **baseline** position in image pixels | yes |
| 3 | font_size in SVG pixels | yes |
| 4 | text (literal \n creates a second line) | yes |
| 5 | font_family, e.g. Comic Sans MS, Comic Neue, cursive | no, defaults to sans-serif |
| 6 | fill SVG color, e.g. #15212c | no, defaults to #000000 |
| 7 | font_weight (1–1000) | no |
| 8 | text_length in pixels | no |

Optional columns are positional. To set column 8 without column 7, leave
column 7 blank. Each row creates a separate editable SVG text element.
For multiple lines in one label, write the two characters \n in the fourth
column; the output uses editable tspan elements.

Example labels.tsv (here <TAB> represents an actual tab):

~~~text
# x<TAB>y<TAB>font_size<TAB>text<TAB>font_family<TAB>fill<TAB>weight<TAB>text_length
20<TAB>45<TAB>28<TAB>Mindmap: Wald<TAB>Comic Sans MS, Comic Neue, cursive<TAB>#174227<TAB>700
130<TAB>110<TAB>19<TAB>Bäume & Tiere<TAB>Comic Sans MS, Comic Neue, cursive<TAB>#203020
~~~

Run:

~~~sh
vtracer cleaned-illustration.png mindmap.svg --text-file labels.tsv
~~~

The converter handles XML escaping, so ampersands, less-than signs, quotes,
and German characters remain valid and editable. It rejects invalid numbers
and XML control characters. When --text-file is omitted, the existing SVG
output remains unchanged.

Text is **not** converted to paths or embedded as a bitmap. Install the named
font on the editing machine to obtain the same look; if it is missing, the SVG
renderer may substitute another font. The overlay has no automatic OCR,
font matching, text alignment, wrapping, or image inpainting.

## Rust API

The vtracer core library remains independent of file formats and IO:

~~~rust
use vtracer::{ColorImage, Config, EditableText};

fn example(clean_image: ColorImage) -> Result<(), vtracer::Error> {
    let mut title = EditableText::new("Lebensraum Wald", 30.0, 60.0);
    title.font_family = "Comic Sans MS, Comic Neue, cursive".to_string();
    title.font_size = 32.0;
    title.fill = "#173f28".to_string();

    let svg = Config::default()
        .build()?
        .to_svg_with_text(&clean_image, &[title])?;
    Ok(())
}
~~~

The lower-level append_editable_text(svg, labels) function also adds
editable text to a VTracer-generated SVG string. With no labels, it returns
the original string byte-for-byte. SVG labels render after (above) the traced
shapes, preserving the artwork's path geometry and paint order.

## Implementation notes

- This separates *text recognition and mask preparation* from *tracing and
  SVG composition*, avoiding an OCR dependency in the Rust core.
- Coordinates are absolute in the image's pixel coordinate system; y refers
  to the text baseline, not the top of the glyphs.
- The text layer can be edited in Inkscape and other SVG editors.
- The Rust library validates text and emits escaped XML; invalid fields are
  rejected rather than producing broken SVG.
- Multiline text uses tspan and dy="1.2em" for subsequent lines.
- Existing pipelines that call to_svg are unaffected.

## Future improvements

Separate follow-up changes could add OCR integrations, automatic masking or
inpainting, importing structured JSON text specifications, richer SVG text
styles, and a Python-language binding. Those are intentionally outside this
small initial change.
