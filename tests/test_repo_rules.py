"""Repository rule (owner, 2026-10-07): a test log larger than 1 MB goes to test_logs/, which git ignores.
Commit only the summary (the result document and a line in docs/test_results/RAW_LOGS.md)."""
import os
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT_BYTES = 1_000_000     # "1 MB"
LOG_EXT = (".log", ".jsonl", ".ndjson", ".csv", ".tsv", ".out", ".txt", ".json")


def _git(*args) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", ROOT, *args], capture_output=True)
    except OSError:
        pytest.skip("git is not available")


def test_no_tracked_test_log_is_larger_than_1_mb():
    r = _git("ls-files", "-z")
    if r.returncode != 0:
        pytest.skip("not a git work tree")
    big = []
    for p in (x for x in r.stdout.decode("utf-8").split("\0") if x):
        f = os.path.join(ROOT, p)
        if p.lower().endswith(LOG_EXT) and os.path.isfile(f) and os.path.getsize(f) > LIMIT_BYTES:
            big.append((p, os.path.getsize(f)))
    assert not big, f"test logs larger than 1 MB must go to test_logs/ (ignored); commit only the summary: {big}"


def test_test_logs_folder_is_ignored_and_raw_logs_index_exists():
    r = _git("check-ignore", "-q", "test_logs/t8/x.jsonl")
    if r.returncode == 128:
        pytest.skip("not a git work tree")
    assert r.returncode == 0, "test_logs/ must be in .gitignore"
    assert os.path.isfile(os.path.join(ROOT, "docs", "test_results", "RAW_LOGS.md"))
