//! Optional editable SVG text layer for traced illustrations.
//!
//! Text placement, transcription, and removing rasterized lettering from the
//! input image are the caller's responsibility. This module only composes
//! checked, escaped SVG text elements with existing vector paths.

use std::fmt::Write as _;

use crate::Error;

/// A positioned, editable SVG label. Coordinates use the same pixel coordinate
/// system as the traced image; y is the text baseline.
#[derive(Debug, Clone, PartialEq)]
pub struct EditableText {
    pub text: String,
    pub x: f64,
    pub y: f64,
    pub font_family: String,
    pub font_size: f64,
    pub fill: String,
    pub font_weight: Option<u16>,
    /// Optional SVG textLength for matching lettering width in a reference.
    pub text_length: Option<f64>,
}

impl EditableText {
    /// Construct a label with neutral defaults. All properties remain editable.
    pub fn new(text: impl Into<String>, x: f64, y: f64) -> Self {
        Self {
            text: text.into(),
            x,
            y,
            font_family: "sans-serif".into(),
            font_size: 24.0,
            fill: "#000000".into(),
            font_weight: None,
            text_length: None,
        }
    }

    fn validate(&self) -> Result<(), Error> {
        if !self.x.is_finite() || !self.y.is_finite() {
            return Err(Error::Other("text coordinates must be finite".into()));
        }
        if !self.font_size.is_finite() || self.font_size <= 0.0 {
            return Err(Error::Other("text font_size must be finite and positive".into()));
        }
        if let Some(length) = self.text_length {
            if !length.is_finite() || length <= 0.0 {
                return Err(Error::Other("text_length must be finite and positive".into()));
            }
            if self.text.contains('\n') {
                return Err(Error::Other(
                    "text_length cannot be combined with multiline text".into(),
                ));
            }
        }
        if self.font_family.is_empty() || self.fill.is_empty() {
            return Err(Error::Other("font_family and fill cannot be empty".into()));
        }
        if let Some(weight) = self.font_weight {
            if !(1..=1000).contains(&weight) {
                return Err(Error::Other("font_weight must be between 1 and 1000".into()));
            }
        }
        if ![self.text.as_str(), &self.font_family, &self.fill]
            .iter()
            .all(|value| value.chars().all(is_xml_char))
        {
            return Err(Error::Other("text contains characters forbidden in XML 1.0".into()));
        }
        Ok(())
    }
}

/// Insert an optional editable text layer after the vector artwork, without
/// altering the traced paths or the bytes of an SVG with no text layer.
///
/// This is intended for an SVG produced by VTracer (a closing </svg> at the
/// end is required). Labels are XML-escaped and checked before insertion.
pub fn append_editable_text(svg: &str, labels: &[EditableText]) -> Result<String, Error> {
    if labels.is_empty() {
        return Ok(svg.to_owned());
    }

    let close = svg
        .rfind("</svg>")
        .filter(|&at| svg[at + "</svg>".len()..].trim().is_empty())
        .ok_or_else(|| Error::Other("expected a complete SVG document".into()))?;

    // Validate all labels before producing output: never return a partial layer.
    for label in labels {
        label.validate()?;
    }

    let mut layer = String::new();
    layer.push_str("<g id=\"editable-text\">\n");
    for label in labels {
        let _ = write!(
            layer,
            "<text x=\"{}\" y=\"{}\" font-family=\"{}\" font-size=\"{}\" fill=\"{}\"",
            label.x,
            label.y,
            escape_xml(&label.font_family),
            label.font_size,
            escape_xml(&label.fill)
        );
        if let Some(weight) = label.font_weight {
            let _ = write!(layer, " font-weight=\"{}\"", weight);
        }
        if let Some(length) = label.text_length {
            let _ = write!(
                layer,
                " textLength=\"{}\" lengthAdjust=\"spacingAndGlyphs\"",
                length
            );
        }
        layer.push('>');
        if label.text.contains('\n') {
            for (i, line) in label.text.split('\n').enumerate() {
                let dy = if i == 0 { "0" } else { "1.2em" };
                let _ = write!(
                    layer,
                    "<tspan x=\"{}\" dy=\"{}\">{}</tspan>",
                    label.x,
                    dy,
                    escape_xml(line)
                );
            }
        } else {
            layer.push_str(&escape_xml(&label.text));
        }
        layer.push_str("</text>\n");
    }
    layer.push_str("</g>\n");

    let mut result = String::with_capacity(svg.len() + layer.len());
    result.push_str(&svg[..close]);
    result.push_str(&layer);
    result.push_str(&svg[close..]);
    Ok(result)
}

fn is_xml_char(c: char) -> bool {
    matches!(
        c as u32,
        0x9 | 0xA | 0xD | 0x20..=0xD7FF | 0xE000..=0xFFFD | 0x10000..=0x10FFFF
    )
}

fn escape_xml(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len());
    for ch in value.chars() {
        match ch {
            '&' => escaped.push_str("&amp;"),
            '<' => escaped.push_str("&lt;"),
            '>' => escaped.push_str("&gt;"),
            '"' => escaped.push_str("&quot;"),
            '\'' => escaped.push_str("&apos;"),
            _ => escaped.push(ch),
        }
    }
    escaped
}

#[cfg(test)]
mod tests {
    use super::*;
    use resvg::usvg;

    const BASE: &str = "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"80\" height=\"60\"><path d=\"M0,0L10,10\" fill=\"#345678\"/></svg>\n";

    #[test]
    fn no_labels_preserve_original_output_exactly() {
        assert_eq!(append_editable_text(BASE, &[]).unwrap(), BASE);
    }

    #[test]
    fn editability_and_original_artwork_are_preserved() {
        let mut label = EditableText::new("Äpfel & <Birnen> \"reif\"", 10.0, 35.0);
        label.font_family = "Comic Sans MS, 'Comic Neue', cursive".into();
        label.font_size = 18.0;
        label.fill = "#112233".into();
        label.font_weight = Some(600);
        label.text_length = Some(160.5);
        let out = append_editable_text(BASE, &[label]).unwrap();
        assert!(out.contains("d=\"M0,0L10,10\""));
        assert!(out.find("<path").unwrap() < out.find("<text").unwrap());
        assert!(out.contains("Äpfel &amp; &lt;Birnen&gt; &quot;reif&quot;"));
        assert!(out.contains("Comic Sans MS, &apos;Comic Neue&apos;, cursive"));
        assert!(out.contains("textLength=\"160.5\" lengthAdjust=\"spacingAndGlyphs\""));
        assert_eq!(out.matches("<text ").count(), 1);
        usvg::Tree::from_str(&out, &usvg::Options::default()).unwrap();
    }

    #[test]
    fn multiline_labels_keep_editable_tspans() {
        let label = EditableText::new("Erste Zeile\nZweite Zeile", 12.0, 18.0);
        let out = append_editable_text(BASE, &[label]).unwrap();
        assert!(out.contains("<tspan x=\"12\" dy=\"0\">Erste Zeile</tspan>"));
        assert!(out.contains("<tspan x=\"12\" dy=\"1.2em\">Zweite Zeile</tspan>"));
        assert_eq!(out.matches("<text ").count(), 1);
        usvg::Tree::from_str(&out, &usvg::Options::default()).unwrap();
    }

    #[test]
    fn invalid_values_cannot_create_broken_svg() {
        let mut label = EditableText::new("OK", f64::NAN, 12.0);
        assert!(append_editable_text(BASE, &[label.clone()]).is_err());
        label.x = 3.0;
        label.font_size = f64::INFINITY;
        assert!(append_editable_text(BASE, &[label.clone()]).is_err());
        label.font_size = 12.0;
        label.text = "bad\u{0001}value".into();
        assert!(append_editable_text(BASE, &[label.clone()]).is_err());
        label.text = "OK".into();
        label.text_length = Some(0.0);
        assert!(append_editable_text(BASE, &[label.clone()]).is_err());
        label.text_length = None;
        label.font_weight = Some(1001);
        assert!(append_editable_text(BASE, &[label]).is_err());
        assert!(append_editable_text("<svg>", &[EditableText::new("OK", 1.0, 1.0)]).is_err());
    }
}
