import unittest

from autoresearch.prompts.improve import render


class TestPrompt(unittest.TestCase):
    def test_braces_dollars_passthrough(self) -> None:
        code = "f('${x}')  # {brace} $dollar"
        out = render(
            parent_code="p",
            parent_score="1.0",
            current_code=code,
            current_score="2.0",
            read_paths=[],
        )
        self.assertIn(code, out)

    def test_full_sections(self) -> None:
        out = render(
            parent_code="P",
            parent_score="1.0",
            current_code="C",
            current_score="2.0",
            read_paths=["/a", "/b"],
        )
        for s in ("Parent score: 1.0", "P", "Current score: 2.0", "C", "- /a", "- /b"):
            self.assertIn(s, out)

    def test_no_parent_omits_block(self) -> None:
        out = render(
            parent_code=None,
            parent_score=None,
            current_code="C",
            current_score="2.0",
            read_paths=[],
        )
        self.assertNotIn("Parent", out)

    def test_no_read_paths_omits_section(self) -> None:
        out = render(
            parent_code="P",
            parent_score="1.0",
            current_code="C",
            current_score="2.0",
            read_paths=[],
        )
        self.assertNotIn("read_approved", out)
