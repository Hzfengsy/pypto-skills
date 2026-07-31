from __future__ import annotations

import unittest

from tests.skill_assertions import ROOT


class CIToolConfigurationTests(unittest.TestCase):
    def test_ci_dependencies_are_exactly_pinned(self) -> None:
        requirements = (ROOT / "requirements-ci.txt").read_text(encoding="utf-8")
        self.assertEqual(
            ["pyright==1.1.410", "ruff==0.16.0"],
            requirements.splitlines(),
        )

    def test_python_tools_target_the_supported_baseline(self) -> None:
        configuration = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('target-version = "py310"', configuration)
        self.assertIn('select = ["E4", "E7", "E9", "F", "I"]', configuration)
        self.assertIn('pythonVersion = "3.10"', configuration)
        self.assertIn('typeCheckingMode = "basic"', configuration)
        self.assertIn('include = ["tests"]', configuration)


if __name__ == "__main__":
    unittest.main()
