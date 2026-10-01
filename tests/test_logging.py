"""Structural regression tests for Picard 2.13 debug-log guards.

The production provider cannot be imported in the standalone test environment
because Picard and Qt are intentionally absent.  These tests therefore inspect
its syntax tree and enforce the logging contract without mocking either runtime.
"""

import ast
from pathlib import Path
import unittest


PROVIDER_PATH = Path(__file__).parents[1] / "preferred_cover_art" / "provider.py"


class DebugLoggingTests(unittest.TestCase):
    """Ensure detailed provider traces remain conditional on Picard Debug mode."""

    @classmethod
    def setUpClass(cls):
        """Parse the provider once and retain parent links for ancestry checks."""
        cls.tree = ast.parse(PROVIDER_PATH.read_text(encoding="utf-8"))
        cls.parents = {}
        for parent in ast.walk(cls.tree):
            for child in ast.iter_child_nodes(parent):
                cls.parents[child] = parent

    @staticmethod
    def _is_debug_call(node):
        """Return whether an AST node calls ``log.debug``."""
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "log"
            and node.func.attr == "debug"
        )

    @staticmethod
    def _attribute_name(node):
        """Return a dotted name for a simple attribute expression."""
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
            return ".".join(reversed(parts))
        return ""

    def test_debug_mode_uses_picard_2_effective_level(self):
        """The mode guard must use Picard 2.13's effective logging level API."""
        helper = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_debug_logs_enabled"
        )
        calls = {
            self._attribute_name(node.func)
            for node in ast.walk(helper)
            if isinstance(node, ast.Call)
        }
        attributes = {
            self._attribute_name(node)
            for node in ast.walk(helper)
            if isinstance(node, ast.Attribute)
        }
        self.assertIn("log.get_effective_level", calls)
        self.assertIn("logging.DEBUG", attributes)

    def test_every_debug_log_is_conditionally_guarded(self):
        """Every detailed trace must be enclosed by a Debug-mode condition."""
        debug_calls = [node for node in ast.walk(self.tree) if self._is_debug_call(node)]
        self.assertTrue(debug_calls, "provider.py must contain debug traces")

        for call in debug_calls:
            ancestor = self.parents.get(call)
            guards = []
            while ancestor is not None:
                if isinstance(ancestor, ast.If):
                    guards.extend(
                        node.id for node in ast.walk(ancestor.test) if isinstance(node, ast.Name)
                    )
                    guards.extend(
                        node.func.id
                        for node in ast.walk(ancestor.test)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    )
                ancestor = self.parents.get(ancestor)
            self.assertTrue(
                "debug_logs" in guards or "_debug_logs_enabled" in guards,
                "unguarded log.debug call on line %d" % call.lineno,
            )


if __name__ == "__main__":
    unittest.main()
