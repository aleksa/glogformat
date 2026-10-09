"""Shared helpers for glogformat tests."""

import os
import unittest
from unittest.mock import patch

LOGGING_ENV_VARS: tuple[str, ...] = (
    "LOG_LEVEL",
    "LOG_COLOR",
    "NO_COLOR",
    "FORCE_COLOR",
)


def isolate_logging_env(test_case: unittest.TestCase) -> None:
    """Hide glogformat's environment variables for the duration of a test.

    Without this, a NO_COLOR or LOG_LEVEL set in the developer's shell changes
    test outcomes. The real environment is restored when the test finishes.

    Args:
        test_case: Test whose cleanup restores the environment.
    """
    patcher = patch.dict(os.environ)
    patcher.start()
    test_case.addCleanup(patcher.stop)
    for name in LOGGING_ENV_VARS:
        os.environ.pop(name, None)
