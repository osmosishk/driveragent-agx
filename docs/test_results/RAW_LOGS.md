# Test logs larger than 1 MB

Rule (owner, 2026-10-07): a test log larger than 1 MB (1,000,000 bytes) goes to `test_logs/` in the
repository folder, which git ignores. Commit only the summary: the result document of the test and one line
in this file. `tests/test_repo_rules.py` checks the rule: no tracked `.log`, `.jsonl`, `.ndjson`, `.csv`,
`.tsv`, `.out`, `.txt` or `.json` file is larger than 1 MB, and git ignores `test_logs/`.

The logs below were in git before the rule. They are now on AGX02 in `test_logs/` (the same sub-folders).
The full files stay in the git history: commit `b38f303` (also on GitHub, osmosishk/driveragent-agx) is
the last commit that has them, for example `git show b38f303:docs/test_results/t4/t4_status.jsonl`.
Documents that name `docs/test_results/...` for these files mean this old place. Times are AGX02 local time
(BST). Check a file with `sha256sum`.

| Old path in git | Now on AGX02 | Bytes | Lines | sha256 | Time span (BST) | Summary |
|---|---|---|---|---|---|---|
| `docs/test_results/nv12/nv12_status.jsonl` | `test_logs/nv12/nv12_status.jsonl` | 3,025,616 | 301 | `bf2933ae4512ccd0e2a81cc02b65de7e81d2d26b65674467b0afd2a3fae7ca76` | 2026-10-06 00:02:08 .. 00:07:08 | docs/test_results/nv12/NV12_MODEL_TEST.md |
| `docs/test_results/t4/t4_status.jsonl` | `test_logs/t4/t4_status.jsonl` | 2,959,448 | 300 | `98b8870719740b89071c4856633f8807b0f01f942f3e89be82849c8053ce5bd6` | 2026-10-05 23:02:05 .. 23:07:04 | docs/test_results/T4_RESULT.md |
| `docs/test_results/t8/night_journal.log` | `test_logs/t8/night_journal.log` | 2,677,662 | 7,056 | `6f01e256d3c2c525124e14fe45f8f3918acb7505a2505827a55c0577738392f2` | 2026-10-05 21:41:47 .. 2026-10-06 05:20:23 | docs/test_results/t8/T8_NIGHT_RUN.md; docs/MORNING_REPORT.md section 4.5 |
| `docs/test_results/t8/night_status.jsonl` | `test_logs/t8/night_status.jsonl` | 18,842,947 | 1,868 | `9f9f908e08bfac72fdf17001a5ea41231bcd2761237acb2d4a3f9c9d859ac801` | 2026-10-06 00:08:47 .. 05:19:57 | docs/test_results/t8/T8_NIGHT_RUN.md; docs/MORNING_REPORT.md section 4.5 |
| `docs/test_results/t8/night_sysmon.jsonl` | `test_logs/t8/night_sysmon.jsonl` | 1,401,717 | 1,867 | `41bb41df36677755c8bb5019b7bb58b89408ffc9339941d0b5ff65edb5915ace` | 2026-10-06 00:08:57 .. 05:19:57 | docs/test_results/t8/T8_NIGHT_RUN.md; docs/MORNING_REPORT.md section 4.5 |
| `docs/test_results/t8/soak_status.jsonl` | `test_logs/t8/soak_status.jsonl` | 18,135,123 | 1,801 | `2b8faddd9b0a6fd045e98607ececc18c012ab4c9541204df230577c0955797c0` | 2026-10-06 00:08:47 .. 00:38:47 | docs/MORNING_REPORT.md section 4.4 |
| `docs/test_results/t8/soak_sysmon.jsonl` | `test_logs/t8/soak_sysmon.jsonl` | 1,376,180 | 1,830 | `41c7845bfc9125e1b281cdcbd9f27aec7a899f1feb2aecf18953e15b1a6d9a34` | 2026-10-06 00:08:48 .. 00:39:17 | docs/MORNING_REPORT.md section 4.4 |
