from __future__ import annotations

import unittest
from pathlib import Path

from tests.skill_assertions import ROOT

BANNED_TEXT = (
    "hw-native-sys/pypto",
    "hw-native-sys/simpler",
    "hw-native-sys/pypto-lib",
    "upstream/main",
    "origin/main",
    "AskUserQuestion",
    "EnterPlanMode",
    "Task tool",
)

DEPLOYABLE_ROOTS = (ROOT / "skills", ROOT / "lib")

REQUIRED_GITHUB_REFERENCES = (
    ROOT / "lib/github/setup.md",
    ROOT / "lib/github/lookup-pr.md",
    ROOT / "lib/github/branch-naming.md",
    ROOT / "lib/github/commit-and-push.md",
    ROOT / "lib/github/common-issues.md",
    ROOT / "lib/github/detect-permission.md",
    ROOT / "lib/github/fetch-comments.md",
    ROOT / "lib/github/reply-and-resolve.md",
    ROOT / "lib/github/checkout-fork-branch.md",
)


def deployable_files() -> list[Path]:
    return sorted(
        path
        for root in DEPLOYABLE_ROOTS
        if root.is_dir()
        for path in root.rglob("*")
        if path.is_file()
    )


class PortabilityTests(unittest.TestCase):
    def test_deployable_content_has_no_banned_text(self) -> None:
        for path in deployable_files():
            text = path.read_text(encoding="utf-8")
            for banned in BANNED_TEXT:
                with self.subTest(path=path, banned=banned):
                    self.assertNotIn(banned, text)

    def test_required_github_references_exist(self) -> None:
        for path in REQUIRED_GITHUB_REFERENCES:
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), f"missing required reference: {path}")


if __name__ == "__main__":
    unittest.main()
