from __future__ import annotations

import re
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

GITHUB_CONTEXT_VARIABLES = (
    "REPO_ROOT",
    "CURRENT_BRANCH",
    "DEFAULT_BRANCH",
    "BASE_REMOTE",
    "BASE_REF",
    "PUSH_REMOTE",
    "PR_REPO",
    "PR_HEAD_PREFIX",
    "ROLE",
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

    def test_setup_defines_context_before_references_use_it(self) -> None:
        setup = ROOT / "lib/github/setup.md"
        self.assertTrue(setup.is_file(), f"missing required reference: {setup}")
        setup_text = setup.read_text(encoding="utf-8")
        definitions = set(
            re.findall(
                r"(?m)^\s*(?:export )?([A-Z][A-Z0-9_]*)=", setup_text
            )
        )

        for variable in GITHUB_CONTEXT_VARIABLES:
            with self.subTest(variable=variable):
                self.assertIn(variable, definitions)

        for path in REQUIRED_GITHUB_REFERENCES[1:]:
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), f"missing required reference: {path}")
                used_context = set(
                    re.findall(
                        r"\$(?:{)?([A-Z][A-Z0-9_]*)(?:})?",
                        path.read_text(encoding="utf-8"),
                    )
                ).intersection(GITHUB_CONTEXT_VARIABLES)
                self.assertLessEqual(used_context, definitions)

    def test_rewritten_pushes_use_force_with_lease(self) -> None:
        reference = ROOT / "lib/github/commit-and-push.md"
        self.assertTrue(
            reference.is_file(), f"missing required reference: {reference}"
        )
        text = reference.read_text(encoding="utf-8")
        self.assertIn("git push --force-with-lease", text)
        self.assertNotRegex(text, r"git push\s+--force(?!-with-lease)")


if __name__ == "__main__":
    unittest.main()
