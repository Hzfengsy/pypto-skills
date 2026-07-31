from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.skill_assertions import ROOT

HELPER = ROOT / "lib/github/scripts/prepare-and-push.sh"


class CommitAndPushBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.temp_path = Path(self.temporary_directory.name)
        self.base_remote = self.temp_path / "base.git"
        self.push_remote = self.temp_path / "fork.git"
        self.work = self.temp_path / "work"
        self.checkpoint = self.temp_path / "push.checkpoint"

        self.git(
            self.temp_path, "init", "--bare", "--initial-branch=main", self.base_remote
        )
        self.git(
            self.temp_path, "init", "--bare", "--initial-branch=main", self.push_remote
        )
        self.git(self.temp_path, "init", "--initial-branch=main", self.work)
        self.git(self.work, "config", "user.name", "Portable Tests")
        self.git(self.work, "config", "user.email", "portable@example.com")

        (self.work / "base.txt").write_text("base\n", encoding="utf-8")
        self.git(self.work, "add", "base.txt")
        self.git(self.work, "commit", "-m", "base")
        self.git(self.work, "remote", "add", "base", self.base_remote)
        self.git(self.work, "push", "--set-upstream", "base", "main")

        self.git(self.work, "switch", "--create", "feature")
        (self.work / "feature.txt").write_text("feature\n", encoding="utf-8")
        self.git(self.work, "add", "feature.txt")
        self.git(self.work, "commit", "-m", "feature")
        self.git(
            self.work,
            "remote",
            "add",
            "contributor",
            self.push_remote,
        )
        self.git(
            self.work,
            "push",
            "--set-upstream",
            "contributor",
            "feature",
        )
        self.initial_feature_oid = self.git_output(self.work, "rev-parse", "HEAD")

    def git(
        self,
        cwd: Path,
        *arguments: object,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *(str(argument) for argument in arguments)],
            cwd=cwd,
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
        command: str,
        *,
        history_rewritten: bool = False,
        expected_remote_oid: str = "-",
    ) -> subprocess.CompletedProcess[str]:
        if not HELPER.is_file():
            self.fail(f"missing production helper: {HELPER}")
        arguments = [str(HELPER), command, str(self.checkpoint)]
        if command == "prepare":
            arguments.extend(
                [
                    "base",
                    "main",
                    "contributor",
                    "feature",
                    "feature",
                    str(history_rewritten).lower(),
                    expected_remote_oid,
                ]
            )
        return subprocess.run(
            arguments,
            cwd=self.work,
            check=False,
            capture_output=True,
            text=True,
        )

    def checkpoint_values(self) -> dict[str, str]:
        return dict(
            line.split("=", 1)
            for line in self.checkpoint.read_text(encoding="utf-8").splitlines()
        )

    def advance_remote(
        self,
        remote: Path,
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
            remote,
            writer,
        )
        self.git(writer, "config", "user.name", "Concurrent Writer")
        self.git(writer, "config", "user.email", "writer@example.com")
        (writer / filename).write_text(content, encoding="utf-8")
        self.git(writer, "add", filename)
        self.git(writer, "commit", "-m", f"advance {branch}")
        self.git(writer, "push", "origin", f"HEAD:{branch}")
        return self.git_output(writer, "rev-parse", "HEAD")

    def remote_oid(self, remote: Path, branch: str) -> str:
        output = self.git_output(
            self.work,
            "ls-remote",
            "--heads",
            remote,
            f"refs/heads/{branch}",
        )
        return output.split()[0] if output else ""

    def test_autosquash_rewrite_survives_noop_prepare_rebase_and_uses_lease(
        self,
    ) -> None:
        self.git(self.work, "commit", "--amend", "-m", "feature rewritten")
        rewritten_oid = self.git_output(self.work, "rev-parse", "HEAD")
        self.assertNotEqual(self.initial_feature_oid, rewritten_oid)

        prepared = self.run_helper(
            "prepare",
            history_rewritten=True,
            expected_remote_oid=self.initial_feature_oid,
        )
        self.assertEqual(0, prepared.returncode, prepared.stderr)
        checkpoint = self.checkpoint_values()
        self.assertEqual("true", checkpoint["HISTORY_REWRITTEN"])
        self.assertEqual(rewritten_oid, checkpoint["PREPARED_HEAD_OID"])
        self.assertEqual(
            self.initial_feature_oid,
            checkpoint["PREPARED_REMOTE_OID"],
        )

        pushed = self.run_helper("push")
        self.assertEqual(0, pushed.returncode, pushed.stderr)
        self.assertEqual(rewritten_oid, self.remote_oid(self.push_remote, "feature"))
        self.assertIn("leased", pushed.stdout)

    def test_concurrent_remote_update_after_prepare_is_refused_and_preserved(
        self,
    ) -> None:
        self.git(self.work, "commit", "--amend", "-m", "feature rewritten")
        prepared = self.run_helper(
            "prepare",
            history_rewritten=True,
            expected_remote_oid=self.initial_feature_oid,
        )
        self.assertEqual(0, prepared.returncode, prepared.stderr)
        concurrent_oid = self.advance_remote(
            self.push_remote,
            "feature",
            "concurrent.txt",
            "concurrent\n",
        )

        pushed = self.run_helper("push")
        self.assertNotEqual(0, pushed.returncode)
        self.assertIn("remote head changed after prepare", pushed.stderr)
        self.assertEqual(concurrent_oid, self.remote_oid(self.push_remote, "feature"))

    def test_base_advancement_before_prepare_is_rebased_and_checkpointed(
        self,
    ) -> None:
        advanced_base_oid = self.advance_remote(
            self.base_remote,
            "main",
            "advanced-base.txt",
            "advanced base\n",
        )
        old_feature_oid = self.git_output(self.work, "rev-parse", "HEAD")

        prepared = self.run_helper(
            "prepare",
            expected_remote_oid=self.initial_feature_oid,
        )
        self.assertEqual(0, prepared.returncode, prepared.stderr)
        checkpoint = self.checkpoint_values()
        self.assertEqual(advanced_base_oid, checkpoint["PREPARED_BASE_OID"])
        self.assertEqual("true", checkpoint["HISTORY_REWRITTEN"])
        self.assertNotEqual(old_feature_oid, checkpoint["PREPARED_HEAD_OID"])
        self.git(
            self.work,
            "merge-base",
            "--is-ancestor",
            advanced_base_oid,
            checkpoint["PREPARED_HEAD_OID"],
        )

        pushed = self.run_helper("push")
        self.assertEqual(0, pushed.returncode, pushed.stderr)
        self.assertEqual(
            checkpoint["PREPARED_HEAD_OID"],
            self.remote_oid(self.push_remote, "feature"),
        )

    def test_base_drift_after_prepare_is_refused(self) -> None:
        prepared = self.run_helper(
            "prepare",
            expected_remote_oid=self.initial_feature_oid,
        )
        self.assertEqual(0, prepared.returncode, prepared.stderr)
        self.advance_remote(
            self.base_remote,
            "main",
            "post-validation-base.txt",
            "post validation\n",
        )

        pushed = self.run_helper("push")
        self.assertNotEqual(0, pushed.returncode)
        self.assertIn("base tip changed after prepare", pushed.stderr)
        self.assertEqual(
            self.initial_feature_oid,
            self.remote_oid(self.push_remote, "feature"),
        )

    def test_local_head_drift_after_prepare_is_refused(self) -> None:
        prepared = self.run_helper(
            "prepare",
            expected_remote_oid=self.initial_feature_oid,
        )
        self.assertEqual(0, prepared.returncode, prepared.stderr)
        (self.work / "drift.txt").write_text("drift\n", encoding="utf-8")
        self.git(self.work, "add", "drift.txt")
        self.git(self.work, "commit", "-m", "post validation drift")

        pushed = self.run_helper("push")
        self.assertNotEqual(0, pushed.returncode)
        self.assertIn("local HEAD changed after prepare", pushed.stderr)
        self.assertEqual(
            self.initial_feature_oid,
            self.remote_oid(self.push_remote, "feature"),
        )

    def test_non_rewrite_fast_forward_uses_normal_push(self) -> None:
        (self.work / "follow-up.txt").write_text("follow up\n", encoding="utf-8")
        self.git(self.work, "add", "follow-up.txt")
        self.git(self.work, "commit", "-m", "follow up")
        follow_up_oid = self.git_output(self.work, "rev-parse", "HEAD")

        prepared = self.run_helper(
            "prepare",
            expected_remote_oid=self.initial_feature_oid,
        )
        self.assertEqual(0, prepared.returncode, prepared.stderr)
        checkpoint = self.checkpoint_values()
        self.assertEqual("false", checkpoint["HISTORY_REWRITTEN"])

        pushed = self.run_helper("push")
        self.assertEqual(0, pushed.returncode, pushed.stderr)
        self.assertEqual(follow_up_oid, self.remote_oid(self.push_remote, "feature"))
        self.assertIn("normal", pushed.stdout)


if __name__ == "__main__":
    unittest.main()
