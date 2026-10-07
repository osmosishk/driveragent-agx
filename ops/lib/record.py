#!/usr/bin/env python3
"""The install record data/install-<instance>.json of ops/install.sh (what install made, what it kept).

  record.py update RECORD --instance I --repo R --store S --made F --kept F --units J --options J
      F = a file with lines "<kind>\\t<path>" (empty file = none). J = a JSON object.
      Paths that an earlier run made stay in "made" (a second run keeps them: uninstall still removes them).
  record.py add-made RECORD KIND PATH         add one path to "made" (no other change)
  record.py list RECORD [made|kept]           print "<kind>\\t<path>" lines
  record.py get RECORD KEY                    print one top-level value as JSON
  record.py uninstalled RECORD KIND...        remove these kinds from "made" and add an "uninstall" event

The record has no secret (no password, no token). Mode 600, atomic write.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import time

SCHEMA = "agx-install-record/1"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path: str, d: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".install.", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, sort_keys=True)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_pairs(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if "\t" in line:
                kind, p = line.split("\t", 1)
                out.append({"kind": kind, "path": p})
    return out


def opt(args: list[str], name: str) -> str:
    i = args.index(name)
    return args[i + 1]


def cmd_update(rec: str, args: list[str]) -> int:
    d = load(rec)
    made_old = d.get("made") if isinstance(d.get("made"), list) else []
    made_new = read_pairs(opt(args, "--made"))
    t = now_iso()
    seen = {m["path"] for m in made_old if isinstance(m, dict)}
    for m in made_new:
        if m["path"] not in seen:
            made_old.append(dict(m, t=t))
            seen.add(m["path"])
    kept_all = read_pairs(opt(args, "--kept"))
    # "kept_last_run" = what an earlier run did NOT make (a file of the owner): uninstall never removes it.
    kept = [k for k in kept_all if k["path"] not in seen]
    runs = d.get("runs") if isinstance(d.get("runs"), list) else []
    runs.append({"t": t, "made": [m["path"] for m in made_new], "kept": [k["path"] for k in kept_all],
                 "options": json.loads(opt(args, "--options"))})
    d.update({
        "schema": SCHEMA,
        "instance": opt(args, "--instance"),
        "repo": opt(args, "--repo"),
        "store": opt(args, "--store"),
        "user": os.environ.get("USER") or str(os.getuid()),
        "host": socket.gethostname(),
        "first_run": d.get("first_run") or t,
        "last_run": t,
        "made": made_old,
        "kept_last_run": kept,
        "units": json.loads(opt(args, "--units")),
        "runs": runs[-20:],
    })
    save(rec, d)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, rec, rest = argv[0], argv[1], argv[2:]
    if cmd == "update":
        return cmd_update(rec, rest)
    d = load(rec)
    if cmd == "add-made" and len(rest) == 2:
        made = d.setdefault("made", [])
        if rest[1] not in {m.get("path") for m in made if isinstance(m, dict)}:
            made.append({"kind": rest[0], "path": rest[1], "t": now_iso()})
        save(rec, d)
        return 0
    if cmd == "list":
        which = rest[0] if rest else "made"
        rows = d.get("made" if which == "made" else "kept_last_run") or []
        for m in rows:
            if isinstance(m, dict) and m.get("path"):
                print(f"{m.get('kind', '?')}\t{m['path']}")
        return 0
    if cmd == "get" and len(rest) == 1:
        print(json.dumps(d.get(rest[0])))
        return 0
    if cmd == "uninstalled":
        kinds = set(rest)
        gone = [m for m in d.get("made") or [] if isinstance(m, dict) and m.get("kind") in kinds]
        d["made"] = [m for m in d.get("made") or [] if not (isinstance(m, dict) and m.get("kind") in kinds)]
        d.setdefault("uninstalls", []).append({"t": now_iso(), "removed": [m.get("path") for m in gone]})
        save(rec, d)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
