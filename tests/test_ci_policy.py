from __future__ import annotations

import os
import unittest
from unittest import mock

from tests.ci_policy import REQUIRE_BWRAP_ENV, enforce_validation_sandbox


class CIIsolationPolicyTests(unittest.TestCase):
    def test_operational_sandbox_is_accepted(self) -> None:
        enforce_validation_sandbox(True)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_unavailable_sandbox_skips_outside_ci(self) -> None:
        with self.assertRaisesRegex(
            unittest.SkipTest,
            "bubblewrap isolation is unavailable",
        ):
            enforce_validation_sandbox(False)

    @mock.patch.dict(
        os.environ,
        {"PYPTO_SKILLS_REQUIRE_BWRAP": "1"},
        clear=True,
    )
    def test_unavailable_sandbox_fails_when_ci_requires_it(self) -> None:
        self.assertEqual("PYPTO_SKILLS_REQUIRE_BWRAP", REQUIRE_BWRAP_ENV)
        with self.assertRaisesRegex(
            AssertionError,
            "PYPTO_SKILLS_REQUIRE_BWRAP=1",
        ):
            enforce_validation_sandbox(False)


if __name__ == "__main__":
    unittest.main()
