//! Ensure tracing keeps generating the same paths when editable SVG text is added.

use resvg::usvg;
use vtracer::{ColorImage, Config, EditableText};

fn sample() -> ColorImage {
    let mut pixels = Vec::new();
    for y in 0..40 {
        for x in 0..60 {
            if (12..45).contains(&x) && (12..28).contains(&y) {
                pixels.extend_from_slice(&[31, 125, 190, 255]);
            } else {
                pixels.extend_from_slice(&[255, 255, 255, 255]);
            }
        }
    }
    ColorImage {
        pixels,
        width: 60,
        height: 40,
    }
}

#[test]
fn editable_overlay_does_not_modify_traced_paths() {
    let pipeline = Config::default().build().unwrap();
    let img = sample();
    let original = pipeline.to_svg(&img).unwrap();
    let mut label = EditableText::new("Übung: A & B", 10.0, 25.0);
    label.font_family = "Comic Sans MS, Comic Neue, cursive".into();
    let combined = pipeline.to_svg_with_text(&img, &[label]).unwrap();

    assert_eq!(original.matches("<path ").count(), combined.matches("<path ").count());
    let original_paths = original.split("<path ").skip(1).map(|s| s.split("/>").next().unwrap()).collect::<Vec<_>>();
    let combined_paths = combined.split("<path ").skip(1).map(|s| s.split("/>").next().unwrap()).collect::<Vec<_>>();
    assert_eq!(original_paths, combined_paths);
    assert!(combined.contains("<g id=\"editable-text\">"));
    assert!(combined.contains("Übung: A &amp; B"));
    usvg::Tree::from_str(&combined, &usvg::Options::default()).unwrap();
}

#[test]
fn empty_overlay_is_byte_for_byte_identical() {
    let pipeline = Config::default().build().unwrap();
    let img = sample();
    assert_eq!(pipeline.to_svg(&img).unwrap(), pipeline.to_svg_with_text(&img, &[]).unwrap());
}


#[test]
fn multiple_labels_keep_their_order_and_are_editable() {
    let pipeline = Config::default().build().unwrap();
    let first = EditableText::new("Erste Zeile", 8.0, 12.0);
    let second = EditableText::new("Zweite Zeile", 9.0, 32.0);
    let svg = pipeline
        .to_svg_with_text(&sample(), &[first, second])
        .unwrap();
    let first_pos = svg.find("Erste Zeile").unwrap();
    let second_pos = svg.find("Zweite Zeile").unwrap();
    assert!(first_pos < second_pos);
    assert_eq!(svg.matches("<text ").count(), 2);
    assert!(!svg.contains("<image"));
    usvg::Tree::from_str(&svg, &usvg::Options::default()).unwrap();
}
