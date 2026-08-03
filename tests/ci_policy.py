from __future__ import annotations

import os
import unittest

REQUIRE_BWRAP_ENV = "PYPTO_SKILLS_REQUIRE_BWRAP"


def enforce_validation_sandbox(operational: bool) -> None:
    if operational:
        return

    message = "bubblewrap isolation is unavailable and fails closed"
    if os.environ.get(REQUIRE_BWRAP_ENV) == "1":
        raise AssertionError(f"{message}; {REQUIRE_BWRAP_ENV}=1")
    raise unittest.SkipTest(message)
