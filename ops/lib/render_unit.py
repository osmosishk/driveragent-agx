#!/usr/bin/env python3
"""Make a systemd unit file from a template of ops/units/ (ops/install.sh).

  render_unit.py TEMPLATE OUT --instance I --repo R --python P [--user U --group G] [--user-site]

Placeholders: @INSTANCE@ @REPO@ @REPO_TEXT@ @PYTHON@ @USER@ @GROUP@ @NOUSERSITE_LINE@.
A "%" in a path becomes "%%" (systemd specifier). A path with a double quote, a backslash or a line break is
refused (it cannot be written safely in a unit file). OUT "-" = standard output.
"""
from __future__ import annotations

import os
import re
import sys


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    tpl, out, rest = argv[0], argv[1], argv[2:]
    vals = {"--instance": "", "--repo": "", "--python": "", "--user": "", "--group": ""}
    user_site = "--user-site" in rest
    for k in vals:
        if k in rest:
            vals[k] = rest[rest.index(k) + 1]
    for k in ("--repo", "--python"):
        v = vals[k]
        if not v.startswith("/") or any(c in v for c in '"\\\n\r'):
            print(f"ERROR: {k} {v!r}: an absolute path without a double quote, a backslash or a line break is necessary",
                  file=sys.stderr)
            return 1
    esc = {k: v.replace("%", "%%") for k, v in vals.items()}
    nus = ("# PYTHONNOUSERSITE is not set (ops/install.sh --user-site): the user site ~/.local is used."
           if user_site else "Environment=PYTHONNOUSERSITE=1")
    with open(tpl, encoding="utf-8") as f:
        text = f.read()
    for ph, v in (("@INSTANCE@", esc["--instance"]), ("@REPO_TEXT@", esc["--repo"]), ("@REPO@", esc["--repo"]),
                  ("@PYTHON@", esc["--python"]), ("@USER@", esc["--user"]), ("@GROUP@", esc["--group"]),
                  ("@NOUSERSITE_LINE@", nus)):
        text = text.replace(ph, v)
    left = sorted(set(re.findall(r"@[A-Z_]+@", text)))
    if left:
        print(f"ERROR: placeholders left in {tpl}: {left}", file=sys.stderr)
        return 1
    if out == "-":
        sys.stdout.write(text)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(out, 0o644)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
