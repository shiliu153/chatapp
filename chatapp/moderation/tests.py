from django.test import SimpleTestCase

from .text_check import find_blocked_word


class TextCheckTests(SimpleTestCase):
    def test_detects_blocked_word_even_with_spaces(self):
        self.assertEqual(find_blocked_word("专业代 开发票"), "代开发票")

    def test_normal_text_passes(self):
        self.assertIsNone(find_blocked_word("喜欢音乐和旅行的设计师"))

    def test_empty_text_passes(self):
        self.assertIsNone(find_blocked_word(""))
