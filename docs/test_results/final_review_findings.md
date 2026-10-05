1. H1 | rules-docs | HIGH | CONFIRMED | R4 breach. pip installed packages outside .venv, and NIGHT_LOG does not record it.
   - Evidence: `/tmp/claude-1000/-home-tonyho/b9a1f96f-4259-44f3-959f-d0095d7e5c07/scratchpad/pylib/` holds `quickjs-1.19.4.dist-info` and `esprima-4.0.1.dist-info`. Both `INSTALLER` files contain "pip". Times: esprima 21:25:56, quickjs 21:26:41.
   - The wheels are in `~/.cache/pip/wheels/74/07/aa/.../quickjs-1.19.4-cp310-cp310-linux_aarch64.whl` (21:26:40) and `~/.cache/pip/wheels/7c/ad/8b/.../esprima-4.0.1-py3-none-any.whl` (21:25:55).
   - `docs/NIGHT_LOG.md:12` says "Installed in the venv only". Line 38 says that all pip installs were allowed installs.
   - Line 48 says "the skipped QuickJS page test passed when run with AGX_DASH_TEST_PYLIB". No output file supports this (R14).
   - Fix: add a NIGHT_LOG entry for the breach: time 21:25-21:26, target directory, the 2 packages, download from PyPI, wheels in `~/.cache/pip`. Save the real pytest output of the QuickJS run in `docs/test_results/`, or remove the claim from line 48. In future, install into `.venv` only, or keep the test skipped.

2. H2 | completeness + rules-docs (C1 = D2) | HIGH | CONFIRMED | The documented install command does not stop the transient units, and it makes root-owned directories.
   - Evidence: `docs/BLOCKERS.md:15` and `README.md:39` tell the owner to run `sudo bash .../systemd/install_units.sh`.
   - `systemd/install_units.sh:9` runs `systemctl --user stop agx-infer.service agx-dashboard.service agx-sim.service 2>/dev/null || true`. Under sudo this command goes to root, not to the manager of tonyho, and `|| true` hides the failure.
   - `install_units.sh:13` runs `mkdir -p "$P/data" "$P/logs" "$P/engines"` as root. `logs/` and `engines/` do not exist now (`ls`), so root will own them. The units run as `User=tonyho` with `Restart=on-failure` and `RestartSec=3` (`systemd/*.service:12,18,19`).
   - Result: the system agx-infer cannot bind 5560/5561 and restarts in a loop. The system dashboard moves to 8701 (`config/dashboard.yaml:2`). agx-sim continues to run. If agx-sim is stopped, `mode: sim` (`config/sources.yaml:9`) gives NO SIGNAL on all cameras, because no system unit replaces agx-sim. BLOCKERS does not say this.
   - Fix:
     - In BLOCKERS.md:15 and README.md:39, change the command to `bash systemd/install_units.sh` (run as tonyho; the script uses sudo where it must).
     - At the top of install_units.sh, add `[ "$EUID" -eq 0 ] && { echo "run as tonyho, not with sudo"; exit 1; }`.
     - Before `systemctl start`, check that ports 5560-5563 and 8700 are free.
     - Write a note about `mode: sim` and the missing sim unit.

3. M1 | security | MEDIUM | CONFIRMED | The dashboard uses plain HTTP and Basic auth on all interfaces.
   - Evidence: `config/dashboard.yaml:4` `bind: "0.0.0.0"` and `:9-10` `tls_certfile/keyfile: null`. `ss` shows `0.0.0.0:8700`. The comment at `:6-8` already accepts that the password goes across the network.
   - Fix: bind only to 127.0.0.1 and 100.64.0.20, with two sockets in `dashboard/main.py:bind_first_free`. Or set `tls_certfile` and `tls_keyfile` to a local self-signed certificate. Do not serve on 10.0.0.130 until TLS is on.

4. M2 | security | MEDIUM | CONFIRMED | The IP allowlist is too wide.
   - Evidence: `config/dashboard.yaml:13-22`, `dashboard/auth.py:22-25` `DEFAULT_ALLOW` and `dashboard/config.py:18` contain 10/8, 172.16/12 (this includes docker0), 192.168/16, 100.64/10, 169.254/16, fc00::/7 and fe80::/10. The IPv6 entries have no effect, because the socket is IPv4 only.
   - Fix: in all 3 places, use 127.0.0.0/8, 10.0.0.0/24, 100.64.0.180/32 and the operator tailscale /32 addresses. Remove the other entries.

5. M3 | security | MEDIUM | CONFIRMED | ZMQ PUB ports 5560 and 5561 listen on 0.0.0.0, with no authentication and no MAXMSGSIZE.
   - Evidence: `config/infer.yaml:15-16` (`results`/`status: "0.0.0.0"`). `ss` shows `0.0.0.0:5560` and `0.0.0.0:5561` for pid 2009184.
   - `infer/publish/results.py:199-200` and `infer/publish/status.py:117-118` set only SNDHWM and LINGER. Only `infer/admin.py:45` sets MAXMSGSIZE.
   - The exposure is confirmed. The memory DoS is plausible from libzmq behaviour, but I did not test it (load tests are forbidden).
   - Fix: add `self._sock.setsockopt(zmq.MAXMSGSIZE, 4096)` before `bind` in both publishers. In `config/infer.yaml`, bind to the RK link address (100.64.0.20 now, 10.42.0.1 later). Optional: a ZAP allow-list for 100.64.0.180.

6. M4 | security | MEDIUM (latent, rk mode only) | CONFIRMED | In rk mode, the UDP ingest takes frames from any source.
   - Evidence: `config/sources.yaml:16-17` `rk: "0.0.0.0"`. `infer/ingest/rx_proc.py:208,222` uses `recv_into`, and no file in `infer/ingest/*.py` calls `recvfrom`. Now `ss -ulnp` shows only 127.0.0.1:6000-6005 (sim mode).
   - Fix: set `bind_host.rk: "10.42.0.1"`. In `rx_proc.py`, use `recvfrom_into` and drop datagrams that do not come from the configured RK IP. Count the drops in the status.

7. M5 | safety-labels | MEDIUM | CONFIRMED | The soak report does not label its numbers SIMULATED (R13).
   - Evidence: in `tools/soak_report.py`, a case-insensitive grep for "sim" finds only line 97 (the process name `tools.rk_sim`). The model table (`:160-170`) gives fps and p50/p95/p99 with no source label.
   - Fix: count the status samples that have `node.simulated` true. Write a first line "INPUT SOURCE: SIMULATED (N of M samples)". Add a SIMULATED/LIVE/MIXED column to the camera table and the model table. Add a unit test that feeds simulated status lines and checks for "SIMULATED" in each table.

8. M6 | rules-docs (D3, with the line part of D4) | MEDIUM | CONFIRMED | `docs/RK_AGX_INTERFACE.md` has old line references.
   - `:91` cites `config/dashboard.yaml:28`. That line is `ping_interval_s`. The 5562 endpoint is at `:35`.
   - `:142` cites `framelink_rx.py:336-339`. Those lines are shm close code. The cam check is at `:505-508`.
   - `:143`, `:144` and `:146` cite the same wrong area.
   - `:204` cites `config/sources.yaml:42`, which is empty. `reassembly_timeout_s` is at `:51`.
   - `:155` cites `sources.yaml:45` for `h265_resync_on_loss`. The key is at `:55`.
   - `:455` cites `dashboard/auth.py:17`, which is empty. `REALM` is at `:20`.
   - The Reassembler defaults are at `common/framelink.py:154-155`.
   - Fix: get each reference again with `grep -n` and commit.

9. M7 | rules-docs | MEDIUM | CONFIRMED | `docs/RK_TASKS.md:94` is false and has a wrong line reference.
   - Evidence: the document says agx-infer is "Not running at the time of writing". But `ActiveEnterTimestamp=23:11:04`, and the RK_TASKS commit 9c28a6a is at 23:24:32.
   - It cites `infer/main.py:202` for `--mode`. Line 202 is `th.join(self.stop_timeout_s)`. The argument is at `:213`. Line 95 has the same wrong reference.
   - Fix: write that the 3 transient user units are running. Change both references to `infer/main.py:213`.

10. M8 | operations | MEDIUM | CONFIRMED | A FAILED model does not recover, and the process stays up, so systemd does not restart it.
    - Evidence: `infer/models/manager.py:109-120`. `report_error` calls `fail()` after `fail_after_errors` (3) errors in sequence. `fail()` sets FAILED and `stop_event`.
    - `infer/runner.py:244-247`: a scheduling error is fatal and the worker returns.
    - A grep of `manager.py`, `main.py` and `runner.py` finds no restart, retry or backoff path.
    - Fix: add a supervisor that starts a FAILED model again with backoff (30 s, up to 10 min). Or exit non-zero when all enabled models are FAILED for more than 60 s, so that `Restart=on-failure` applies.

11. M9 | operations | MEDIUM | CONFIRMED | The units stop when the last session of tonyho ends.
    - Evidence: `loginctl show-user tonyho`: `Linger=no`, Sessions 407, 3 and 1 (session 1 is tty2). Correction to the reviewer: `/var/lib/systemd/linger` exists but is empty (count=0).
    - Fix: tonight, do not log out of tty2. In the morning, the owner runs `loginctl enable-linger tonyho` (approval needed) or installs the system units after H2 is fixed.

12. M10 | operations | MEDIUM | CONFIRMED | No overnight recorder is running, so the soak report will have no input data (R14).
    - Evidence: `ps` shows no `status_log`, `sysmon` or `soak` process. There is no `tests/out/night_*` file.
    - Fix: start `tools.sysmon` (interval 5 s) and `tools.status_log` (every 10 s) as `systemd-run --user` transient units. Write their output to `tests/out/night_*.jsonl`.

13. M11 | completeness (C2 + D10) | MEDIUM (downgraded from HIGH: the run is not finished) | CONFIRMED | The owner documents are not complete, and some files are not committed.
    - Evidence: `docs/MORNING_REPORT.md` does not exist. `README.md:7` and `:84` refer to it. `git status` shows `?? README.md` and ` M docs/NIGHT_LOG.md`.
    - Fix: write `docs/MORNING_REPORT.md` with these parts: T0-T8 and A-F status with an evidence file for each, the SIMULATED statement, blockers B1-B6, owner actions, soak result and gaps. Then commit `README.md`, `NIGHT_LOG.md` and the report.

14. M12 | completeness | MEDIUM | CONFIRMED | The models were never tested with NV12 at the RK sizes.
    - Evidence: `docs/test_results/T4_RESULT.md:188-189` says that H.265 passthrough sends 1280x720 on all cameras. `docs/test_results/t4/sim_driving.yaml:17` has `fmt: h265`. The NV12 evidence is ingest only (T3 probe files). The running agx-sim has no `--fmt nv12`.
    - Fix: mark this as NOT TESTED in the report. Later, when load tests are permitted, run `tools/svc.sh start sim --fmt nv12` with agx-infer and `tools.rk_result_client` for 5 minutes, and record fps, latency and lost frames.

15. M13 | completeness | MEDIUM | CONFIRMED | The dashboard does not show last_error, errors_total or queue_ms.
    - Evidence: `infer/models/manager.py:452-460` sends these fields. `dashboard/infer_views.py` and `dashboard/static/app.js` have 0 hits. The live `/api/models` keys do not include them. `T4_RESULT.md:182-184` records this as a known limit.
    - Fix: pass these fields through `infer_views.py` to `/api/models`, and show them in the model row in `app.js`.

16. M14 | completeness | MEDIUM | CONFIRMED | The log viewer reads user units only, and agx-sim is not in the allowed list.
    - Evidence: `dashboard/collectors/services.py:221` always uses `--user-unit=`. `config/dashboard.yaml:62` is `log_units: [agx-infer, agx-dashboard]`.
    - Fix: when the system unit is active, use `journalctl -u <unit>`, else use `--user-unit`. Add `agx-sim` to `log_units`.

17. M15 | completeness | MEDIUM | CONFIRMED | The MQTT publisher has no test and no document.
    - Evidence: `grep -li mqtt tests/*.py` finds no file (rc=1). README.md and docs/*.md mention MQTT only in NIGHT_LOG:12 (the package install).
    - Fix: add a test that checks that `start_mqtt()` returns None and opens no socket when MQTT is disabled. With a mocked paho client, check the topic, the interval and the `simulated` key. Add a README section with this R11 warning: "enable only with owner approval".

18. M16 | completeness | MEDIUM | CONFIRMED | A new engineer cannot set up the system from git.
    - Evidence: there is no `requirements*`, `pyproject*` or `setup.*` file. README has no set-up section.
    - Fix: add `requirements-venv.txt` (from `pip list --local --format=freeze`). Add a "Set-up" section: venv with `--system-site-packages`, `.env.example` copied to `.env` with mode 600, and JetPack/TensorRT 10.3.0.

19. R1 | rules-docs (D4) | MEDIUM | REFUTED | The reviewer said that `config/sources.yaml` has no `h265_resync_on_loss` key.
    - Evidence: `config/sources.yaml:55` is `h265_resync_on_loss: true`. Only the line number in the document is wrong, and M6 covers it.

20. Low findings (not verified, kept as the reviewers wrote them):
    - L1 | security S5 | UNVERIFIED-LOW | Parallel requests get around the failed-login delay, and `_fails.clear()` resets all counts (`dashboard/auth.py:110-119,140-145`). Fix: count failures per IP and send 429 at once above the limit. Remove only the oldest entries.
    - L2 | security S6 | UNVERIFIED-LOW | The admin socket 5563 and the internal socket 5562 have no authentication (loopback only). Fix: use `ipc://` sockets in a 0700 directory below the project.
    - L3 | security S7 | UNVERIFIED-LOW | If MQTT is enabled, it can send credentials without TLS and send data off the machine (`dashboard/mqtt_pub.py:42-44`). Fix: refuse to start when a user is set and TLS is off. Write the R11 note in `.env.example`.
    - L4 | safety-labels L2 | UNVERIFIED-LOW | The dashboard treats a missing `simulated` flag as live data (`dashboard/collectors/infer_status.py:43-48,177-178,298,308`, `dashboard/infer_views.py:145,262`). Fix: treat a missing or non-bool flag as simulated, and add a test.
    - L5 | safety-labels L3 | UNVERIFIED-LOW | Some `/api/health` objects have `simulated: true` but no `label` (`dashboard/app.py:195`, `dashboard/infer_views.py:364`). Fix: add `"label": "SIMULATED"`.
    - L6 | safety-labels L4 | UNVERIFIED-LOW | `tools.model_ctl list` shows fps and results with no SIMULATED label (`tools/model_ctl.py:58-62`). Fix: add a SOURCE column or a header line.
    - L7 | safety-labels L5 | UNVERIFIED-LOW | The trajectory text on the snapshot does not say "not for control" (`infer/draw.py:149-151`). Fix: add "display only, not for control".
    - L8 | safety-labels L6 | UNVERIFIED-LOW | The DTCP control outputs (`mu`, `sigma`, `pred_speed`) reach `adapter.postprocess` (`infer/runner.py:256-258`). Fix: give the adapter only the keys in `adapter.ENGINE_OUTPUTS`, and add a test.
    - L9 | safety-labels L7 | UNVERIFIED-LOW | Legacy control code is in `infer/models/legacy/driverguard/`, and `dashboard/collectors/old_procs.py:12` does not match it. Fix: add an ImportError guard to these files, add the patterns to `old_procs.py`, and add an import test.
    - L10 | rules-docs D6 | UNVERIFIED-LOW | The command in `docs/test_results/T7_RESULT.md:44-45` does not agree with its output. Fix: show the real pipeline, or run the command again and paste the real output.
    - L11 | rules-docs D7 | UNVERIFIED-LOW | The R1 notes in NIGHT_LOG:36-41 are old or incomplete: gstreamer registry, `~/.local` anyio `.pyc`, `/tmp/pytest-of-tonyho`, the transient files in `/run/user`. Fix: record them. Run pytest with `PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 --basetemp=tests/out/pytest`.
    - L12 | rules-docs D8 | UNVERIFIED-LOW | The T1 SNTP probe sent packets to public NTP servers (R11, NIGHT_LOG:41). Fix: the owner decides. Do not use external probes again.
    - L13 | rules-docs D9 + completeness C15 | UNVERIFIED-LOW | Some evidence is not in git: the uPlot source and full sha256, and `tests/out/full_suite*.log`. Fix: record uPlot in `docs/COPIED_FILES.md`, and copy the logs to `docs/test_results/`.
    - L14 | operations O4 | UNVERIFIED-LOW | The journal is volatile (no `/var/log/journal`; confirmed by `ls` during this check). Fix: before any reboot, run `journalctl --user-unit 'agx-*' -o short-iso > tests/out/night_journal.log`.
    - L15 | operations O5 | UNVERIFIED-LOW | Some error logs have no rate limit (`infer/publish/results.py:321`, `infer/publish/internal.py:40`). Fix: use a rate-limited logger like `dashboard/auth.py` `_log_limited`.
    - L16 | operations O6 | UNVERIFIED-LOW | The dashboard RSS increased from 65.7 to 71.8 MB while its buffers filled. Fix: sample again after 00:00. Examine the cause if the growth is more than 5 MB/h.
    - L17 | operations O7 | UNVERIFIED-LOW | `--collect` removes a failed unit and its exit status (`tools/svc.sh:31-34`). Fix: for long runs, do not use `--collect`, or use `RestartSec=10`.
    - L18 | operations O8 | UNVERIFIED-LOW | Time sync offset is about 62 ms and `clock_method` is none. Fix: write the limit in the report.
    - L19 | operations O9 | UNVERIFIED-LOW | capnp writes a PWD warning. Fix: add `--setenv=PWD="$P"` in `tools/svc.sh:33`.
    - L20 | completeness C5 | LOW (downgraded from MEDIUM) | CONFIRMED fact: `config/dashboard.yaml:96-99` has limits only for temp, ram and disk. I did not check the requirement text. Fix: add warn/crit limits for cpu, gpu, swap, power, ping, loss and frame_age, and colour them in `app.js`.
    - L21 | completeness C9 | UNVERIFIED-LOW | README has no "Notes and limits" section: UDP port conflicts, flaky test, rk mode, T8 tools, Linger. Fix: add the section.
    - L22 | completeness C10 | UNVERIFIED-LOW | The node version shows `72fe859-dirty`, but the running code is 74b2af3. Fix: give this mapping in the report.
    - L23 | completeness C11 | UNVERIFIED-LOW | The cam4 and cam5 tiles show black frames. Fix: say this in the report, and use a session that has a picture on these cameras.
    - L24 | completeness C12 | UNVERIFIED-LOW | The page was never tested in a browser. Fix: take a local headless screenshot, or say "not tested in a browser" in the report.
    - L25 | completeness C13 | UNVERIFIED-LOW | Part D (link) is partly done: ping goes over tailscale, and there is no clock offset. Fix: mark D as PARTIAL with B4 and B5.
    - L26 | completeness C14 | UNVERIFIED-LOW | The history has few series, and the 1 s data is in memory only. Fix: add the series, and write the restart behaviour in the report.
    - L27 | completeness C16 | UNVERIFIED-LOW | Some items do not show on the dashboard: orphan PID 86637 "python3 -" (it is running, confirmed by `ps`), the 6th embedded engine, and the camera `last_error`. Fix: write them in the report, and show the camera `last_error` on the tile.