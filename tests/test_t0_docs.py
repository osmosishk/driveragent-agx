"""T0 test: audit and cleanup proposal exist; every proposal row has an exact command and an undo."""
import os
import re

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")


def _rows():
    """The rows of the main table (the table with the header "| # | Item | ..."). Other tables are not read."""
    rows, inside = [], False
    for ln in open(os.path.join(D, "CLEANUP_PROPOSAL.md"), encoding="utf-8"):
        if ln.startswith("| # | Item"):
            inside = True
            continue
        if not inside:
            continue
        if not ln.startswith("|"):
            break
        if re.match(r"^\|\s*-", ln):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", ln.strip())[1:-1]]
        rows.append(cells)
    return rows


def test_files_exist():
    for f in ("AGX_AUDIT.md", "CLEANUP_PROPOSAL.md"):
        p = os.path.join(D, f)
        assert os.path.getsize(p) > 1000, f


def test_every_row_has_command_and_undo():
    rows = _rows()
    assert len(rows) > 50
    bad = [r for r in rows if len(r) != 8 or not r[6] or not r[7] or r[6] in ("-", "?") or r[7] in ("-", "?")]
    assert not bad, bad[:3]
    # proposal words of the night task 2026-10-08: KEEP / DISABLE / MOVE / DELETE, optionally after "SAVE FIRST, then";
    # a short note in parentheses or after ";" or "," may follow
    allowed = re.compile(r"^(SAVE FIRST, then )?(KEEP|DISABLE|MOVE|DELETE)\b")
    assert all(allowed.match(r[5].replace("*", "").strip()) for r in rows), [r[5] for r in rows if not allowed.match(r[5].replace("*", "").strip())][:5]


def test_save_first_rows_on_top():
    props = [r[5] for r in _rows()]
    n = sum(p.startswith("SAVE FIRST") for p in props)
    assert all(p.startswith("SAVE FIRST") for p in props[:n]), "SAVE FIRST rows must be the first rows"
