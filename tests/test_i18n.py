import unittest

from partport.i18n import translate


class TranslationTests(unittest.TestCase):
    def test_chinese_translation_and_formatting(self):
        self.assertEqual(translate("zh_CN", "Import"), "导入")
        self.assertEqual(
            translate("zh_CN", "Saved to {path}", path="x.json"),
            "配置已保存到 x.json",
        )
        self.assertEqual(
            translate("zh_CN", "Product image from the selected data source."),
            "来自所选数据源的零件商品图片。",
        )

    def test_english_is_source_text(self):
        self.assertEqual(translate("en", "Import"), "Import")


if __name__ == "__main__":
    unittest.main()
