"""Shared fixtures. Unit tests are hermetic; integration tests resolve a real
NON-PROD system via `creds` and are opt-in (`-m integration`)."""

from __future__ import annotations

import json
import subprocess

import pytest


@pytest.fixture
def nonprod_system_id() -> str:
    """A non-prod creds id for integration tests. Skips cleanly if none is found.

    Never returns a prod (env:prd) entry — integration writes must never touch prod.
    """
    try:
        out = subprocess.run(
            ["creds", "find", "sbx"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("`creds` CLI not available")
    if out.returncode != 0 or not out.stdout.strip():
        pytest.skip("no non-prod system found via `creds find sbx`")
    try:
        entry = json.loads(out.stdout)[0]
    except (json.JSONDecodeError, IndexError, KeyError):
        pytest.skip("could not parse a non-prod system from `creds find`")
    if str(entry.get("env", "")).lower() == "prd":
        pytest.skip("resolved system is prod; refusing to use it in tests")
    return str(entry["id"])
