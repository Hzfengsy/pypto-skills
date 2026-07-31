from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.skill_assertions import ROOT

HELPER = ROOT / "lib/github/scripts/prepare-and-push.sh"
TRANSACTION_HELPER = ROOT / "lib/github/scripts/push-transaction.sh"
VALIDATION_SANDBOX = ROOT / "lib/github/scripts/validation-sandbox.sh"


class CommitAndPushBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.temp_path = Path(self.temporary_directory.name)
        self.base_remote = self.temp_path / "base.git"
        self.push_remote = self.temp_path / "fork.git"
        self.attacker_remote = self.temp_path / "attacker.git"
        self.work = self.temp_path / "work"
        self.legacy_checkpoint = self.temp_path / "push.checkpoint"
        self.github_host = "ghe.example.test"
        self.base_repo = "base/project"
        self.push_repo = "contributor/project"
        self.base_url = f"ssh://git@{self.github_host}/{self.base_repo}.git"
        self.push_url = f"ssh://git@{self.github_host}/{self.push_repo}.git"
        self.attacker_url = f"ssh://git@{self.github_host}/attacker/project.git"

        self.bin_path = self.temp_path / "bin"
        self.bin_path.mkdir()
        self.write_transport_wrappers()
        self.trusted_validation_runner = self.write_trusted_validation_runner()
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "GIT_SSH_COMMAND": str(self.bin_path / "ssh"),
                "PATH": f"{self.bin_path}:{os.environ['PATH']}",
                "TEST_REAL_GIT": shutil.which("git") or "git",
                "TEST_REMOTE_MAP": json.dumps(
                    {
                        f"/{self.base_repo}.git": str(self.base_remote),
                        f"/{self.push_repo}.git": str(self.push_remote),
                        "/attacker/project.git": str(self.attacker_remote),
                    }
                ),
            }
        )

        for remote in (
            self.base_remote,
            self.push_remote,
            self.attacker_remote,
        ):
            self.git(
                self.temp_path,
                "init",
                "--bare",
                "--initial-branch=main",
                remote,
            )
        self.git(self.temp_path, "init", "--initial-branch=main", self.work)
        self.git(self.work, "config", "user.name", "Portable Tests")
        self.git(self.work, "config", "user.email", "portable@example.com")

        (self.work / "base.txt").write_text("base\n", encoding="utf-8")
        self.git(self.work, "add", "base.txt")
        self.git(self.work, "commit", "-m", "base")
        self.git(self.work, "remote", "add", "base", self.base_url)
        self.git(self.work, "push", "--set-upstream", "base", "main")

        self.git(self.work, "switch", "--create", "feature")
        (self.work / "feature.txt").write_text("feature\n", encoding="utf-8")
        self.git(self.work, "add", "feature.txt")
        self.git(self.work, "commit", "-m", "feature")
        self.git(self.work, "remote", "add", "contributor", self.push_url)
        self.git(
            self.work,
            "push",
            "--set-upstream",
            "contributor",
            "feature",
        )
        self.initial_feature_oid = self.git_output(self.work, "rev-parse", "HEAD")
        self.initial_base_oid = self.remote_oid(self.base_url, "main")

    def write_transport_wrappers(self) -> None:
        fake_ssh = self.bin_path / "ssh"
        fake_ssh.write_text(
            """#!/usr/bin/env python3
import json
import os
import shlex
import sys

parts = shlex.split(sys.argv[-1])
if len(parts) != 2 or parts[0] not in {"git-upload-pack", "git-receive-pack"}:
    raise SystemExit(91)
remote = json.loads(os.environ["TEST_REMOTE_MAP"]).get(parts[1])
if remote is None:
    raise SystemExit(92)
os.execvp(parts[0], [parts[0], remote])
""",
            encoding="utf-8",
        )
        fake_ssh.chmod(0o755)

        fake_git = self.bin_path / "git"
        fake_git.write_text(
            """#!/usr/bin/env python3
import os
import sys

if os.environ.get("FAIL_GIT_COMMAND") == (sys.argv[1] if len(sys.argv) > 1 else ""):
    sys.stderr.write("injected git failure\\n")
    raise SystemExit(73)
os.execv(os.environ["TEST_REAL_GIT"], [os.environ["TEST_REAL_GIT"], *sys.argv[1:]])
""",
            encoding="utf-8",
        )
        fake_git.chmod(0o755)

        fake_gh = self.bin_path / "gh"
        fake_gh.write_text(
            """#!/usr/bin/env sh
printf 'gh write escaped sandbox\\n' > "$TEST_GH_WRITE_MARKER"
exit 0
""",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)

    def write_trusted_validation_runner(self) -> Path:
        runner = self.bin_path / "trusted-validation-runner"
        runner.write_text(
            """#!/usr/bin/env bash
set -u
[ "$#" -eq 2 ] || exit 2
git cat-file -e "$1^{commit}" || exit 3
case "$2" in
  pass) exit 0 ;;
  fail) exit 17 ;;
  *) exit 19 ;;
esac
""",
            encoding="utf-8",
        )
        runner.chmod(0o755)
        return runner

    def git(
        self,
        cwd: Path,
        *arguments: object,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *(str(argument) for argument in arguments)],
            cwd=cwd,
            env=self.environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            self.fail(
                f"git {' '.join(str(argument) for argument in arguments)} failed:\n"
                f"{result.stdout}{result.stderr}"
            )
        return result

    def git_output(self, cwd: Path, *arguments: object) -> str:
        return self.git(cwd, *arguments).stdout.strip()

    def run_helper(
        self,
        *arguments: str,
        fail_git_command: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if not HELPER.is_file():
            self.fail(f"missing production helper: {HELPER}")
        environment = self.environment.copy()
        if fail_git_command is not None:
            environment["FAIL_GIT_COMMAND"] = fail_git_command
        return subprocess.run(
            [str(HELPER), *arguments],
            cwd=self.work,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def prepare(
        self,
        *,
        expected_base_host: str | None = None,
        expected_base_repo: str | None = None,
        expected_head_host: str | None = None,
        expected_head_repo: str | None = None,
        current_branch: str = "feature",
        push_branch: str = "feature",
        history_rewritten: bool = False,
        expected_remote_oid: str | None = None,
        fail_git_command: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object] | None]:
        expected_oid = (
            self.initial_feature_oid
            if expected_remote_oid is None
            else expected_remote_oid
        )
        result = self.run_helper(
            "prepare",
            expected_base_host or self.github_host,
            expected_base_repo or self.base_repo,
            expected_head_host or self.github_host,
            expected_head_repo or self.push_repo,
            "base",
            "main",
            "contributor",
            current_branch,
            push_branch,
            str(history_rewritten).lower(),
            expected_oid,
            fail_git_command=fail_git_command,
        )
        if result.returncode != 0:
            return result, None
        try:
            prepared = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail(f"prepare did not return JSON: {result.stdout!r}")
        self.assertIsInstance(prepared, dict)
        return result, prepared

    def push(
        self,
        prepared: dict[str, object],
        *,
        expected_base_host: str | None = None,
        expected_base_repo: str | None = None,
        expected_head_host: str | None = None,
        expected_head_repo: str | None = None,
        base_remote: str = "base",
        default_branch: str = "main",
        push_remote: str = "contributor",
        current_branch: str = "feature",
        push_branch: str = "feature",
        prepared_remote_oid: str | None = None,
        fail_git_command: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        remote_oid = (
            str(prepared["prepared_remote_oid"])
            if prepared_remote_oid is None
            else prepared_remote_oid
        )
        return self.run_helper(
            "push",
            expected_base_host or self.github_host,
            expected_base_repo or self.base_repo,
            expected_head_host or self.github_host,
            expected_head_repo or self.push_repo,
            base_remote,
            default_branch,
            push_remote,
            current_branch,
            push_branch,
            str(prepared["prepared_head_oid"]),
            str(prepared["prepared_base_oid"]),
            remote_oid,
            str(prepared["history_rewritten"]).lower(),
            fail_git_command=fail_git_command,
        )

    def run_transaction_script(self, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "bash",
                "-c",
                script,
                "_",
                str(TRANSACTION_HELPER),
                str(HELPER),
                self.initial_feature_oid,
                str(self.trusted_validation_runner),
                str(VALIDATION_SANDBOX),
            ],
            cwd=self.work,
            env=self.environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def run_validation_sandbox(
        self,
        command: str,
        *,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.assertTrue(
            VALIDATION_SANDBOX.is_file(),
            f"missing production validation sandbox: {VALIDATION_SANDBOX}",
        )
        return subprocess.run(
            [
                str(VALIDATION_SANDBOX),
                self.initial_feature_oid,
                command,
            ],
            cwd=self.work,
            env=environment or self.environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def validation_sandbox_is_operational(self) -> bool:
        probe = self.run_validation_sandbox(
            "test -f base.txt && test -f feature.txt && printf 'sandbox-probe\\n'"
        )
        return probe.returncode == 0 and "sandbox-probe" in probe.stdout

    def advance_remote(
        self,
        remote_url: str,
        branch: str,
        filename: str,
        content: str,
    ) -> str:
        writer = self.temp_path / f"writer-{filename}"
        self.git(
            self.temp_path,
            "clone",
            "--branch",
            branch,
            remote_url,
            writer,
        )
        self.git(writer, "config", "user.name", "Concurrent Writer")
        self.git(writer, "config", "user.email", "writer@example.com")
        (writer / filename).write_text(content, encoding="utf-8")
        self.git(writer, "add", filename)
        self.git(writer, "commit", "-m", f"advance {branch}")
        self.git(writer, "push", "origin", f"HEAD:{branch}")
        return self.git_output(writer, "rev-parse", "HEAD")

    def remote_oid(self, remote_url: str, branch: str) -> str:
        output = self.git_output(
            self.work,
            "ls-remote",
            "--heads",
            remote_url,
            f"refs/heads/{branch}",
        )
        return output.split()[0] if output else ""

    def test_autosquash_rewrite_survives_noop_prepare_and_uses_lease(
        self,
    ) -> None:
        self.git(self.work, "commit", "--amend", "-m", "feature rewritten")
        rewritten_oid = self.git_output(self.work, "rev-parse", "HEAD")

        result, prepared = self.prepare(history_rewritten=True)

        self.assertEqual(0, result.returncode, result.stderr)
        assert prepared is not None
        self.assertTrue(prepared["history_rewritten"])
        self.assertEqual(rewritten_oid, prepared["prepared_head_oid"])
        self.assertEqual(
            self.initial_feature_oid,
            prepared["prepared_remote_oid"],
        )
        pushed = self.push(prepared)
        self.assertEqual(0, pushed.returncode, pushed.stderr)
        self.assertEqual(rewritten_oid, self.remote_oid(self.push_url, "feature"))
        self.assertIn("leased", pushed.stdout)

    def test_concurrent_remote_update_after_prepare_is_refused(self) -> None:
        self.git(self.work, "commit", "--amend", "-m", "feature rewritten")
        result, prepared = self.prepare(history_rewritten=True)
        self.assertEqual(0, result.returncode, result.stderr)
        assert prepared is not None
        concurrent_oid = self.advance_remote(
            self.push_url,
            "feature",
            "concurrent.txt",
            "concurrent\n",
        )

        pushed = self.push(prepared)

        self.assertNotEqual(0, pushed.returncode)
        self.assertIn("remote head changed after prepare", pushed.stderr)
        self.assertEqual(concurrent_oid, self.remote_oid(self.push_url, "feature"))

    def test_base_advancement_before_prepare_is_rebased_and_returned(
        self,
    ) -> None:
        advanced_base_oid = self.advance_remote(
            self.base_url,
            "main",
            "advanced-base.txt",
            "advanced base\n",
        )
        old_feature_oid = self.git_output(self.work, "rev-parse", "HEAD")

        result, prepared = self.prepare()

        self.assertEqual(0, result.returncode, result.stderr)
        assert prepared is not None
        self.assertEqual(advanced_base_oid, prepared["prepared_base_oid"])
        self.assertTrue(prepared["history_rewritten"])
        self.assertNotEqual(old_feature_oid, prepared["prepared_head_oid"])
        pushed = self.push(prepared)
        self.assertEqual(0, pushed.returncode, pushed.stderr)
        self.assertEqual(
            prepared["prepared_head_oid"],
            self.remote_oid(self.push_url, "feature"),
        )

    def test_base_drift_after_prepare_is_refused(self) -> None:
        result, prepared = self.prepare()
        self.assertEqual(0, result.returncode, result.stderr)
        assert prepared is not None
        self.advance_remote(
            self.base_url,
            "main",
            "post-validation-base.txt",
            "post validation\n",
        )

        pushed = self.push(prepared)

        self.assertNotEqual(0, pushed.returncode)
        self.assertIn("base tip changed after prepare", pushed.stderr)
        self.assertEqual(
            self.initial_feature_oid,
            self.remote_oid(self.push_url, "feature"),
        )

    def test_base_retarget_before_prepare_is_refused(self) -> None:
        self.git(self.work, "push", self.attacker_url, "main:main")
        self.git(self.work, "remote", "set-url", "base", self.attacker_url)

        result, _ = self.prepare()

        self.assertNotEqual(0, result.returncode)
        self.assertIn("base remote base does not fetch from", result.stderr)
        self.assertEqual(
            self.initial_feature_oid,
            self.remote_oid(self.push_url, "feature"),
        )

    def test_base_retarget_after_prepare_with_same_oid_is_refused(self) -> None:
        advanced_base_oid = self.advance_remote(
            self.base_url,
            "main",
            "advanced-base-retarget.txt",
            "advanced base\n",
        )
        self.git(self.work, "fetch", "base", "main")
        self.git(
            self.work,
            "push",
            self.attacker_url,
            "refs/remotes/base/main:refs/heads/main",
        )
        self.assertEqual(advanced_base_oid, self.remote_oid(self.attacker_url, "main"))
        result, prepared = self.prepare()
        self.assertEqual(0, result.returncode, result.stderr)
        assert prepared is not None
        self.git(self.work, "remote", "set-url", "base", self.attacker_url)

        pushed = self.push(prepared)

        self.assertNotEqual(0, pushed.returncode)
        self.assertIn("base remote base does not fetch from", pushed.stderr)
        self.assertEqual(
            self.initial_feature_oid,
            self.remote_oid(self.push_url, "feature"),
        )

    def test_prepare_rejects_malformed_or_multiple_base_fetch_urls(self) -> None:
        policies = (
            (("not-a-github-url",), "does not fetch from"),
            ((self.base_url, self.base_url), "exactly one fetch URL"),
        )
        for urls, error in policies:
            with self.subTest(urls=urls):
                self.git(
                    self.work,
                    "config",
                    "--unset-all",
                    "remote.base.url",
                    check=False,
                )
                for url in urls:
                    self.git(
                        self.work,
                        "config",
                        "--add",
                        "remote.base.url",
                        url,
                    )

                result, _ = self.prepare()

                self.assertNotEqual(0, result.returncode)
                self.assertIn(error, result.stderr)
        self.assertEqual(
            self.initial_feature_oid,
            self.remote_oid(self.push_url, "feature"),
        )

    def test_local_head_drift_after_prepare_is_refused(self) -> None:
        result, prepared = self.prepare()
        self.assertEqual(0, result.returncode, result.stderr)
        assert prepared is not None
        (self.work / "drift.txt").write_text("drift\n", encoding="utf-8")
        self.git(self.work, "add", "drift.txt")
        self.git(self.work, "commit", "-m", "post validation drift")

        pushed = self.push(prepared)

        self.assertNotEqual(0, pushed.returncode)
        self.assertIn("local HEAD changed after prepare", pushed.stderr)
        self.assertEqual(
            self.initial_feature_oid,
            self.remote_oid(self.push_url, "feature"),
        )

    def test_non_rewrite_fast_forward_uses_explicit_arguments(self) -> None:
        (self.work / "follow-up.txt").write_text("follow up\n", encoding="utf-8")
        self.git(self.work, "add", "follow-up.txt")
        self.git(self.work, "commit", "-m", "follow up")
        follow_up_oid = self.git_output(self.work, "rev-parse", "HEAD")
        result, prepared = self.prepare()
        self.assertEqual(0, result.returncode, result.stderr)
        assert prepared is not None

        pushed = self.push(prepared)

        self.assertEqual(0, pushed.returncode, pushed.stderr)
        self.assertEqual(follow_up_oid, self.remote_oid(self.push_url, "feature"))
        self.assertIn("normal", pushed.stdout)

    def test_tampered_legacy_checkpoint_cannot_redirect_explicit_push(
        self,
    ) -> None:
        (self.work / "follow-up.txt").write_text("follow up\n", encoding="utf-8")
        self.git(self.work, "add", "follow-up.txt")
        self.git(self.work, "commit", "-m", "follow up")
        result, prepared = self.prepare()
        self.assertEqual(0, result.returncode, result.stderr)
        assert prepared is not None
        self.legacy_checkpoint.write_text(
            "PUSH_REMOTE=base\nPUSH_BRANCH=main\n"
            f"PREPARED_HEAD_OID={prepared['prepared_head_oid']}\n",
            encoding="utf-8",
        )

        pushed = self.push(prepared)

        self.assertEqual(0, pushed.returncode, pushed.stderr)
        self.assertEqual(self.initial_base_oid, self.remote_oid(self.base_url, "main"))
        self.assertEqual(
            prepared["prepared_head_oid"],
            self.remote_oid(self.push_url, "feature"),
        )

    def test_remote_url_retarget_after_validation_is_refused(self) -> None:
        result, prepared = self.prepare()
        self.assertEqual(0, result.returncode, result.stderr)
        assert prepared is not None
        self.git(
            self.work,
            "remote",
            "set-url",
            "contributor",
            self.attacker_url,
        )

        pushed = self.push(prepared)

        self.assertNotEqual(0, pushed.returncode)
        self.assertIn("does not target", pushed.stderr)
        self.assertEqual(
            self.initial_feature_oid,
            self.remote_oid(self.push_url, "feature"),
        )
        self.assertEqual("", self.remote_oid(self.attacker_url, "feature"))

    def test_attempt_to_push_base_default_branch_is_refused(self) -> None:
        result, prepared = self.prepare()
        self.assertEqual(0, result.returncode, result.stderr)
        assert prepared is not None

        pushed = self.push(
            prepared,
            expected_head_repo=self.base_repo,
            push_remote="base",
            push_branch="main",
            prepared_remote_oid=self.initial_base_oid,
        )

        self.assertNotEqual(0, pushed.returncode)
        self.assertIn("protected base branch", pushed.stderr)
        self.assertEqual(self.initial_base_oid, self.remote_oid(self.base_url, "main"))

    def test_create_route_names_branch_before_capture_and_preserves_default(
        self,
    ) -> None:
        self.git(self.work, "switch", "main")
        self.git(self.work, "switch", "--create", "new-feature")
        (self.work / "new.txt").write_text("new\n", encoding="utf-8")
        self.git(self.work, "add", "new.txt")
        self.git(self.work, "commit", "-m", "new feature")
        new_head = self.git_output(self.work, "rev-parse", "HEAD")

        result, prepared = self.prepare(
            current_branch="new-feature",
            push_branch="new-feature",
            expected_remote_oid="-",
        )

        self.assertEqual(0, result.returncode, result.stderr)
        assert prepared is not None
        pushed = self.push(
            prepared,
            current_branch="new-feature",
            push_branch="new-feature",
        )
        self.assertEqual(0, pushed.returncode, pushed.stderr)
        self.assertEqual(
            new_head,
            self.remote_oid(self.push_url, "new-feature"),
        )
        self.assertEqual(self.initial_base_oid, self.remote_oid(self.base_url, "main"))

    def test_prepare_fails_closed_when_status_inspection_fails(self) -> None:
        result, _ = self.prepare(fail_git_command="status")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("failed to inspect worktree status", result.stderr)
        self.assertEqual(
            self.initial_feature_oid,
            self.remote_oid(self.push_url, "feature"),
        )

    def test_prepare_fails_closed_when_rev_list_fails(self) -> None:
        result, _ = self.prepare(fail_git_command="rev-list")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("failed to count commits ahead", result.stderr)
        self.assertEqual(
            self.initial_feature_oid,
            self.remote_oid(self.push_url, "feature"),
        )

    def test_push_fails_closed_when_branch_inspection_fails(self) -> None:
        result, prepared = self.prepare()
        self.assertEqual(0, result.returncode, result.stderr)
        assert prepared is not None

        pushed = self.push(prepared, fail_git_command="branch")

        self.assertNotEqual(0, pushed.returncode)
        self.assertIn("failed to inspect current branch", pushed.stderr)
        self.assertEqual(
            self.initial_feature_oid,
            self.remote_oid(self.push_url, "feature"),
        )

    def test_push_rejects_malformed_authority_arguments(self) -> None:
        result, prepared = self.prepare()
        self.assertEqual(0, result.returncode, result.stderr)
        assert prepared is not None
        valid_arguments = [
            "push",
            self.github_host,
            self.base_repo,
            self.github_host,
            self.push_repo,
            "base",
            "main",
            "contributor",
            "feature",
            "feature",
            str(prepared["prepared_head_oid"]),
            str(prepared["prepared_base_oid"]),
            str(prepared["prepared_remote_oid"]),
            str(prepared["history_rewritten"]).lower(),
        ]
        malformed = (
            (1, "ghe..example.test", "EXPECTED_HOST"),
            (2, "../project", "EXPECTED_REPO"),
            (3, "ghe..example.test", "EXPECTED_HOST"),
            (4, "../project", "EXPECTED_REPO"),
            (5, "-base", "invalid Git remote"),
            (6, "-main", "not a valid branch"),
            (10, "deadbeef", "PREPARED_HEAD_OID"),
            (12, "deadbeef", "PREPARED_REMOTE_OID"),
            (13, "yes", "HISTORY_REWRITTEN"),
        )
        for index, value, error in malformed:
            with self.subTest(argument=index, value=value):
                arguments = valid_arguments.copy()
                arguments[index] = value
                pushed = self.run_helper(*arguments)
                self.assertNotEqual(0, pushed.returncode)
                self.assertIn(error, pushed.stderr)
        self.assertEqual(
            self.initial_feature_oid,
            self.remote_oid(self.push_url, "feature"),
        )

    def test_validation_sandbox_uses_only_the_exact_committed_snapshot(
        self,
    ) -> None:
        (self.work / "uncommitted-secret.txt").write_text(
            "host-only\n",
            encoding="utf-8",
        )
        if not self.validation_sandbox_is_operational():
            self.skipTest("bubblewrap isolation is unavailable and fails closed")

        result = self.run_validation_sandbox(
            "test -f base.txt && test -f feature.txt && "
            "test ! -e uncommitted-secret.txt && test ! -e .git"
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_validation_sandbox_rejects_direct_git_push(self) -> None:
        operational = self.validation_sandbox_is_operational()

        result = self.run_validation_sandbox(
            "printf 'sandbox-started\\n'; "
            f"git push {shlex.quote(self.push_url)} "
            "HEAD:refs/heads/validation-attack"
        )

        self.assertNotEqual(0, result.returncode)
        if operational:
            self.assertIn("sandbox-started", result.stdout)
        self.assertEqual(
            "",
            self.remote_oid(self.push_url, "validation-attack"),
        )

    def test_validation_sandbox_rejects_gh_write(self) -> None:
        marker = self.temp_path / "gh-write-marker"
        environment = self.environment.copy()
        environment["TEST_GH_WRITE_MARKER"] = str(marker)
        operational = self.validation_sandbox_is_operational()

        result = self.run_validation_sandbox(
            "printf 'sandbox-started\\n'; "
            "gh api --method POST repos/base/project/issues",
            environment=environment,
        )

        self.assertNotEqual(0, result.returncode)
        if operational:
            self.assertIn("sandbox-started", result.stdout)
        self.assertFalse(marker.exists())

    def test_validation_sandbox_hides_token_ssh_and_home_credentials(self) -> None:
        host_home = self.temp_path / "credentialed-home"
        ssh_directory = host_home / ".ssh"
        ssh_directory.mkdir(parents=True)
        (ssh_directory / "id_rsa").write_text("host-private-key\n", encoding="utf-8")
        environment = self.environment.copy()
        environment.update(
            {
                "GH_TOKEN": "host-gh-token",
                "GITHUB_TOKEN": "host-github-token",
                "HOME": str(host_home),
                "SSH_AUTH_SOCK": str(self.temp_path / "host-agent.sock"),
            }
        )
        operational = self.validation_sandbox_is_operational()

        result = self.run_validation_sandbox(
            "printf 'sandbox-started\\n'; "
            'if [ -n "${GH_TOKEN:-}" ] || [ -n "${GITHUB_TOKEN:-}" ] || '
            '[ -n "${SSH_AUTH_SOCK:-}" ]; then exit 0; fi; '
            'cat "$HOME/.ssh/id_rsa"',
            environment=environment,
        )

        self.assertNotEqual(0, result.returncode)
        if operational:
            self.assertIn("sandbox-started", result.stdout)

    def test_validation_sandbox_cannot_write_outside_snapshot(self) -> None:
        marker = self.temp_path / "outside-validation-marker"
        operational = self.validation_sandbox_is_operational()

        result = self.run_validation_sandbox(
            f"printf 'sandbox-started\\n'; touch {shlex.quote(str(marker))}"
        )

        self.assertNotEqual(0, result.returncode)
        if operational:
            self.assertIn("sandbox-started", result.stdout)
        self.assertFalse(marker.exists())

    def test_transaction_disables_repository_configured_commit_hooks(self) -> None:
        hook_marker = self.temp_path / "hook-marker"
        hooks = self.temp_path / "untrusted-hooks"
        hooks.mkdir()
        hook = hooks / "pre-commit"
        hook.write_text(
            "#!/usr/bin/env sh\n"
            f"printf 'hook ran\\n' > {shlex.quote(str(hook_marker))}\n"
            "git push contributor HEAD:refs/heads/hook-attack\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
        self.git(self.work, "config", "core.hooksPath", str(hooks))

        result = self.run_transaction_script(
            r"""
source "$1" || exit 90
commit_change() {
  printf 'hook-safe\n' > hook-safe.txt
  git add hook-safe.txt
  git commit -m 'hook safe transaction'
}
VALIDATION_COMMAND=pass pr_push_transaction "$2" commit_change "$4" \
  ghe.example.test base/project ghe.example.test contributor/project \
  base main contributor feature feature
"""
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(hook_marker.exists())
        self.assertEqual("", self.remote_oid(self.push_url, "hook-attack"))
        self.assertEqual(
            self.git_output(self.work, "rev-parse", "HEAD"),
            self.remote_oid(self.push_url, "feature"),
        )

    def test_failed_validation_then_fresh_transaction_recaptures_and_pushes(
        self,
    ) -> None:
        result = self.run_transaction_script(
            r"""
source "$1" || exit 90
rewrite_change() {
  printf 'retry rewrite\n' >> feature.txt
  git add feature.txt
  git commit --amend --no-edit
  HISTORY_REWRITTEN=true
}
no_change() { :; }
if VALIDATION_COMMAND=fail pr_push_transaction "$2" rewrite_change "$4" \
  ghe.example.test base/project ghe.example.test contributor/project \
  base main contributor feature feature; then
  exit 91
fi
REMOTE_AFTER_FAIL=$(git ls-remote --heads contributor refs/heads/feature |
  awk 'NR == 1 {print $1}') || exit 1
[ "$REMOTE_AFTER_FAIL" = "$3" ] || exit 92
VALIDATION_COMMAND=pass pr_push_transaction "$2" no_change "$4" \
  ghe.example.test base/project ghe.example.test contributor/project \
  base main contributor feature feature
"""
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("readonly variable", result.stderr)
        self.assertIn("Push mode: leased", result.stdout)
        self.assertEqual(
            self.git_output(self.work, "rev-parse", "HEAD"),
            self.remote_oid(self.push_url, "feature"),
        )

    def test_successive_fix_iterations_recapture_updated_remote_lease(
        self,
    ) -> None:
        result = self.run_transaction_script(
            r"""
source "$1" || exit 90
iteration_one() {
  printf 'one\n' > iteration.txt
  git add iteration.txt
  git commit -m 'iteration one'
}
iteration_two() {
  printf 'two\n' >> iteration.txt
  git add iteration.txt
  git commit --amend --no-edit
  HISTORY_REWRITTEN=true
}
VALIDATION_COMMAND=pass pr_push_transaction "$2" iteration_one "$4" \
  ghe.example.test base/project ghe.example.test contributor/project \
  base main contributor feature feature || exit 1
FIRST_PUSHED=$(git rev-parse HEAD) || exit 1
FIRST_REMOTE=$(git ls-remote --heads contributor refs/heads/feature |
  awk 'NR == 1 {print $1}') || exit 1
[ "$FIRST_REMOTE" = "$FIRST_PUSHED" ] || exit 93
VALIDATION_COMMAND=pass pr_push_transaction "$2" iteration_two "$4" \
  ghe.example.test base/project ghe.example.test contributor/project \
  base main contributor feature feature
"""
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("readonly variable", result.stderr)
        self.assertIn("Push mode: normal", result.stdout)
        self.assertIn("Push mode: leased", result.stdout)
        self.assertEqual(
            self.git_output(self.work, "rev-parse", "HEAD"),
            self.remote_oid(self.push_url, "feature"),
        )


if __name__ == "__main__":
    unittest.main()
