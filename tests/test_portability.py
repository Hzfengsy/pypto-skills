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

REFERENCE_INPUTS = {
    "setup.md": frozenset(),
    "lookup-pr.md": frozenset(
        {
            "CURRENT_BRANCH",
            "PR_HEAD_BRANCH",
            "PR_HEAD_PREFIX",
            "PR_NUMBER",
            "PR_REPO",
        }
    ),
    "branch-naming.md": frozenset(
        {"BRANCH_PREFIX", "BRANCH_SUMMARY", "CURRENT_BRANCH", "DEFAULT_BRANCH"}
    ),
    "commit-and-push.md": frozenset(
        {
            "BASE_REMOTE",
            "CURRENT_BRANCH",
            "DEFAULT_BRANCH",
            "HEAD_REPO",
            "LOCAL_REPO",
            "MAINTAINER_CHECKOUT_VERIFIED",
            "PR_HEAD_BRANCH",
            "PUSH_REMOTE",
            "REPO_ROOT",
            "ROLE",
            "WORK_BRANCH",
        }
    ),
    "common-issues.md": frozenset(
        {"PR_NUMBER", "PR_REPO", "REPOSITORY_NODE_ID"}
    ),
    "detect-permission.md": frozenset(
        {"GITHUB_HOST", "PR_NUMBER", "PR_REPO"}
    ),
    "fetch-comments.md": frozenset(
        {
            "COMMENTS_CURSOR",
            "PR_NUMBER",
            "PR_REPO",
            "REVIEWS_CURSOR",
            "THREADS_CURSOR",
        }
    ),
    "reply-and-resolve.md": frozenset(
        {
            "COMMENT_DATABASE_ID",
            "HANDLED_LEDGER",
            "HANDLED_NODE_IDS",
            "PR_NUMBER",
            "PR_REPO",
            "REPLY_BODY",
            "THREAD_ID",
        }
    ),
    "checkout-fork-branch.md": frozenset(
        {"HEAD_REPO", "PR_HEAD_BRANCH", "PR_NUMBER", "PUSH_REMOTE", "ROLE"}
    ),
}

BASH_BLOCK_RE = re.compile(r"```bash\n(.*?)```", re.DOTALL)
SHELL_VARIABLE_USE_RE = re.compile(
    r"\$(?:{!?([A-Z][A-Z0-9_]*)|([A-Z][A-Z0-9_]*))"
)
SHELL_ASSIGNMENT_RE = re.compile(
    r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=", re.MULTILINE
)
SHELL_FOR_VARIABLE_RE = re.compile(
    r"^\s*for\s+([A-Z][A-Z0-9_]*)\s+in\b", re.MULTILINE
)
SHELL_WHILE_READ_VARIABLE_RE = re.compile(
    r"^\s*while\b[^\n]*\bread(?:\s+-[A-Za-z]+)*\s+"
    r"([A-Z][A-Z0-9_]*)\s*;",
    re.MULTILINE,
)


def deployable_files() -> list[Path]:
    return sorted(
        path
        for root in DEPLOYABLE_ROOTS
        if root.is_dir()
        for path in root.rglob("*")
        if path.is_file()
    )


def bash_source(path: Path) -> str:
    return "\n".join(BASH_BLOCK_RE.findall(path.read_text(encoding="utf-8")))


def shell_inputs(path: Path) -> set[str]:
    source = bash_source(path)
    definitions: dict[str, list[int]] = {}

    for pattern in (
        SHELL_ASSIGNMENT_RE,
        SHELL_FOR_VARIABLE_RE,
        SHELL_WHILE_READ_VARIABLE_RE,
    ):
        for match in pattern.finditer(source):
            line_end = source.find("\n", match.end())
            definition_position = len(source) if line_end < 0 else line_end
            definitions.setdefault(match.group(1), []).append(definition_position)

    inputs = set()
    for match in SHELL_VARIABLE_USE_RE.finditer(source):
        variable = match.group(1) or match.group(2)
        if not any(
            position < match.start() for position in definitions.get(variable, [])
        ):
            inputs.add(variable)
    return inputs


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

    def test_setup_defines_context_contract(self) -> None:
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

    def test_references_consume_only_explicit_inputs_before_definition(
        self,
    ) -> None:
        self.assertEqual(
            {path.name for path in REQUIRED_GITHUB_REFERENCES},
            set(REFERENCE_INPUTS),
        )
        for path in REQUIRED_GITHUB_REFERENCES:
            with self.subTest(path=path):
                self.assertEqual(REFERENCE_INPUTS[path.name], shell_inputs(path))

    def test_remote_validation_covers_fetch_and_push_destinations(self) -> None:
        setup = bash_source(ROOT / "lib/github/setup.md")
        self.assertIn("GITHUB_HOST=", setup)
        self.assertIn("git remote get-url --all", setup)
        self.assertIn("git remote get-url --push --all", setup)
        self.assertIn("PUSH_URL_COUNT", setup)
        self.assertRegex(
            setup,
            r'\[ "\$REMOTE_HOST" != "\$GITHUB_HOST" \]',
        )

    def test_push_branch_requires_verified_role_context(self) -> None:
        reference = bash_source(ROOT / "lib/github/commit-and-push.md")
        self.assertIn('owner|fork)', reference)
        self.assertIn(
            '[ "$PR_HEAD_BRANCH" != "$CURRENT_BRANCH" ]',
            reference,
        )
        self.assertIn("MAINTAINER_CHECKOUT_VERIFIED", reference)
        self.assertIn(
            'remote_targets_repo "$PUSH_REMOTE" "$EXPECTED_PUSH_REPO"',
            reference,
        )

    def test_author_workflow_requires_head_repository_push_permission(
        self,
    ) -> None:
        reference = bash_source(ROOT / "lib/github/detect-permission.md")
        self.assertIn(
            'HEAD_CAN_PUSH=$(gh api --hostname "$GITHUB_HOST" '
            '"repos/$HEAD_REPO"',
            reference,
        )
        self.assertIn('[ "$HEAD_CAN_PUSH" != "true" ]', reference)

    def test_rewritten_pushes_use_force_with_lease(self) -> None:
        reference = ROOT / "lib/github/commit-and-push.md"
        self.assertTrue(
            reference.is_file(), f"missing required reference: {reference}"
        )
        text = reference.read_text(encoding="utf-8")
        self.assertIn("git push --force-with-lease", text)
        self.assertNotRegex(text, r"git push\s+--force(?!-with-lease)")

    def test_clean_branches_uses_portable_safe_deletion_contract(self) -> None:
        skill = ROOT / "skills/clean-branches/SKILL.md"
        self.assertTrue(skill.is_file(), f"missing required skill: {skill}")
        if not skill.is_file():
            return

        text = skill.read_text(encoding="utf-8")
        self.assertIn("../../lib/github/setup.md", text)
        self.assertIn("DEFAULT_BRANCH", text)
        self.assertIn("headRefOid", text)
        self.assertRegex(
            text,
            r'git rev-parse .*\n.*headRefOid',
        )
        self.assertIn("Never delete from `$BASE_REMOTE`", text)

        approval = re.search(r"(?im)^## Explicit approval gate$", text)
        self.assertIsNotNone(approval)
        if approval is None:
            return

        destructive_commands = (
            "git branch -D",
            'git push "$PUSH_REMOTE" --delete',
        )
        for command in destructive_commands:
            with self.subTest(command=command):
                command_position = text.find(command)
                self.assertGreaterEqual(command_position, 0)
                self.assertLess(approval.start(), command_position)


if __name__ == "__main__":
    unittest.main()
