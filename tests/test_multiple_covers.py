"""Regression tests for the configurable multi-cover delivery contract.

These tests inspect the provider source because importing it outside Picard would
require Picard's Qt application and plugin runtime.  The assertions deliberately
cover only stable, user-visible requirements.
"""

import ast
from pathlib import Path
import unittest


PROVIDER_PATH = Path(__file__).parents[1] / "preferred_cover_art" / "provider.py"


class MultipleCoverDeliveryTests(unittest.TestCase):
    """Protect the public settings and label used for returned covers."""

    @classmethod
    def setUpClass(cls):
        """Parse the provider once for all structural assertions."""
        cls.source = PROVIDER_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.constants = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in cls.tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
        }

    def test_comment_has_the_compact_rank_score_format(self):
        """Every returned cover must expose only its rank and two-digit score."""
        template = self.constants["COVER_COMMENT_TEMPLATE"]

        self.assertEqual("Rank-SCORE = 3-87.50", template.format(rank=3, score=87.5))

    def test_return_count_is_clamped_between_one_and_ten(self):
        """Corrupt external settings must not escape the supported 1..10 range."""
        self.assertIn(
            "min(10, max(1, config.setting[NUMBER_OF_COVERS_KEY]))",
            self.source,
        )

    def test_api_call_count_is_clamped_between_one_and_ten(self):
        """The provider must protect every source from invalid persisted limits."""
        self.assertIn(
            "min(10, max(1, config.setting[MAX_CALLS_PER_TYPE_KEY]))",
            self.source,
        )

    def test_returned_covers_declare_explicit_type_support(self):
        """Picard must not discard later ranked covers as type-less sources."""
        calls = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "CoverArtImage"
        ]
        self.assertEqual(1, len(calls))
        keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
        self.assertIn("support_types", keywords)
        self.assertIs(True, ast.literal_eval(keywords["support_types"]))


if __name__ == "__main__":
    unittest.main()
