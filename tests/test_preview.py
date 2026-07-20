import unittest

from partport.preview import build_preview_html, extract_svg_documents, sanitize_svg


class PreviewTests(unittest.TestCase):
    def test_extracts_multi_unit_svg_documents(self):
        value = '<svg id="a"></svg>\n<svg id="b"></svg>'
        documents = extract_svg_documents(value)
        self.assertEqual(len(documents), 2)
        self.assertIn('id="a"', documents[0])
        self.assertIn('id="b"', documents[1])

    def test_sanitizes_executable_and_external_svg_content(self):
        value = (
            '<svg onload="bad()"><script>bad()</script>'
            '<foreignObject><p>bad</p></foreignObject>'
            '<use href="https://example.com/x.svg"/><use href="#local"/></svg>'
        )
        cleaned = sanitize_svg(value)
        self.assertNotIn("script", cleaned.lower())
        self.assertNotIn("foreignobject", cleaned.lower())
        self.assertNotIn("onload", cleaned.lower())
        self.assertNotIn("https://", cleaned)
        self.assertIn('href="#local"', cleaned)

    def test_preview_html_has_csp_protected_zoom_controls(self):
        page = build_preview_html(
            "<svg></svg>", "Zoom out", "Reset zoom", "Zoom in", "Mouse wheel"
        )
        self.assertIn("id='zoom-out'", page)
        self.assertIn("id='zoom-reset'", page)
        self.assertIn("id='zoom-in'", page)
        self.assertIn("target.style.width", page)
        self.assertIn("addEventListener('wheel'", page)
        self.assertNotIn("if(!event.ctrlKey)return", page)
        self.assertIn("script-src 'nonce-partport-preview'", page)
        self.assertIn(".product{display:block;width:90%", page)
        self.assertIn(".canvas svg{width:94%", page)
        self.assertIn("window.addEventListener('resize'", page)


if __name__ == "__main__":
    unittest.main()
