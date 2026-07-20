import unittest

from partport.input_parser import invalid_tokens, parse_codes


class InputParserTests(unittest.TestCase):
    def test_mixed_input_and_deduplication(self):
        text = "c12, C34; c12\nhttps://example.test/products/C56.html"
        self.assertEqual(parse_codes(text), ["C12", "C34", "C56"])

    def test_rejects_embedded_alphanumeric_codes(self):
        self.assertEqual(parse_codes("XC123 C4Z C99"), ["C99"])

    def test_invalid_tokens(self):
        self.assertEqual(invalid_tokens("C12 nope https://x.test/no-code"), ["nope", "https://x.test/no-code"])


if __name__ == "__main__":
    unittest.main()
