import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import MtConfig
from src.translator import _parse_output_text, translate_all


class TranslationOutputTests(unittest.TestCase):
    def test_numbered_output_keeps_punctuation_in_one_translation(self):
        raw = "[1] 不，准备就由我们来…… …………\n[2] 千圣学姐？\n[3] 好的"
        self.assertEqual(
            _parse_output_text(raw, 3),
            ["不，准备就由我们来…… …………", "千圣学姐？", "好的"],
        )

    def test_missing_or_duplicate_number_is_rejected_and_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            for raw in ("[1] 一\n[3] 三", "[1] 一\n[1] 二"):
                with self.assertRaises(ValueError):
                    _parse_output_text(raw, 2, directory)
            dumps = list(Path(directory).glob("_raw_response_*.txt"))
            self.assertEqual(len(dumps), 2)

    def test_bad_format_retries_then_raises(self):
        config = MtConfig(enabled=True, api_key="test")
        with patch("src.translator._call_openai", side_effect=ValueError("编号不匹配")) as call:
            with self.assertRaises(ValueError):
                translate_all([{"speaker": "", "text": "原文"}], config)
        self.assertEqual(call.call_count, 2)


if __name__ == "__main__":
    unittest.main()
