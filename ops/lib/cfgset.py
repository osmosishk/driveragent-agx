#!/usr/bin/env python3
"""Change single values in a YAML config file and keep all comments and the layout (ops/install.sh).

  cfgset.py FILE KEY VALUE [KEY VALUE ...]     set scalars or flow lists by a dotted path (ports.results 5570)
  cfgset.py --append FILE KEY ITEM [COMMENT]   add one item to a block list (allow_cidrs), when it is not there
  cfgset.py --get FILE KEY                     print the value as JSON (null when the key is missing)

VALUE is YAML text: 8720, "~/agx-models", sim, [a, b], null. The tool changes only the value text of the line of
the key; the comment at the end of the line stays. A key with a block value (a list or a mapping on the next lines)
gets the new value on its own line; the old block lines go. A missing key is added: at the end of the file (top
level) or as the last child of its parent mapping. Keys in lists ("cameras[0].port") and in flow mappings
({warn: 70}) are not supported: the tool stops with an error.

After the change the tool reads the file again with yaml.safe_load and compares each value. The file is written
(atomic replace, same mode) only when all values agree. Exit 0 = done, 1 = error (nothing written).
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile

import yaml

KEY_RE = re.compile(r"^(?P<ind>[ ]*)(?P<key>[A-Za-z0-9_][A-Za-z0-9_.-]*|\"[^\"]*\"|'[^']*'):(?P<rest>[ \t].*|)$")


def split_comment(text: str) -> tuple[str, str]:
    """('value', ' # comment') of the text after 'key:'. A '#' inside quotes is not a comment."""
    q = None
    for i, ch in enumerate(text):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == "#" and (i == 0 or text[i - 1] in " \t"):
            j = i
            while j > 0 and text[j - 1] in " \t":
                j -= 1
            return text[:j], text[j:]
    return text.rstrip(), ""


def is_skip(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#") or s in ("---", "...")


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def scan(lines: list[str]) -> dict:
    """{dotted path: line index} of all mapping keys outside lists."""
    out: dict[str, int] = {}
    stack: list[tuple[int, str | None]] = []   # (indent, key or None for a list item)
    for i, line in enumerate(lines):
        if is_skip(line):
            continue
        ind = indent_of(line)
        body = line[ind:]
        while stack and stack[-1][0] >= ind:
            stack.pop()
        if body.startswith("- ") or body == "-":
            stack.append((ind, None))
            continue
        m = KEY_RE.match(line)
        if not m:
            continue
        key = m.group("key").strip("\"'")
        if any(k is None for _i, k in stack):
            stack.append((ind, None))          # a key inside a list item: never a target
            continue
        path = ".".join([k for _i, k in stack] + [key])
        out.setdefault(path, i)
        stack.append((ind, key))
    return out


def block_end(lines: list[str], i: int) -> int:
    """Index after the block value of the key on line i (child lines; trailing comments and blank lines stay)."""
    ind = indent_of(lines[i])
    last = i
    for j in range(i + 1, len(lines)):
        if is_skip(lines[j]):
            continue
        ji = indent_of(lines[j])
        body = lines[j][ji:]
        if ji > ind or (ji == ind and (body.startswith("- ") or body == "-")):
            last = j
            continue
        break
    return last + 1


def get_path(data, path: str):
    cur = data
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def set_value(lines: list[str], path: str, value: str) -> list[str]:
    keys = scan(lines)
    if path in keys:
        i = keys[path]
        m = KEY_RE.match(lines[i])
        val, com = split_comment(m.group("rest"))
        if val.strip().startswith(("|", ">")):
            raise SystemExit(f"ERROR: {path}: a multi-line string value is not supported")
        end = block_end(lines, i) if not val.strip() else i + 1
        new = f"{m.group('ind')}{m.group('key')}: {value}"
        if com:
            new += com
        return lines[:i] + [new + "\n"] + lines[end:]
    parent, _, leaf = path.rpartition(".")
    if not parent:
        tail = [] if not lines or lines[-1].endswith("\n") else ["\n"]
        return lines + tail + [f"{leaf}: {value}\n"]
    if parent not in keys:
        raise SystemExit(f"ERROR: {path}: the parent key {parent} is not in the file")
    p = keys[parent]
    m = KEY_RE.match(lines[p])
    pval, _c = split_comment(m.group("rest"))
    if pval.strip():
        raise SystemExit(f"ERROR: {path}: the parent key {parent} has an inline value (not a block mapping)")
    end = block_end(lines, p)
    child_ind = None
    for j in range(p + 1, end):
        if not is_skip(lines[j]):
            child_ind = indent_of(lines[j])
            if lines[j][child_ind:].startswith("-"):
                raise SystemExit(f"ERROR: {path}: the parent key {parent} is a list (keys in lists are not supported)")
            break
    if child_ind is None:
        child_ind = indent_of(lines[p]) + 2
    return lines[:end] + [" " * child_ind + f"{leaf}: {value}\n"] + lines[end:]


def append_item(lines: list[str], path: str, item: str, comment: str) -> tuple[list[str], bool]:
    data = yaml.safe_load("".join(lines)) or {}
    cur = get_path(data, path)
    if not isinstance(cur, list):
        raise SystemExit(f"ERROR: {path} is not a list in the file")
    if yaml.safe_load(item) in cur:
        return lines, False
    keys = scan(lines)
    i = keys[path]
    m = KEY_RE.match(lines[i])
    val, _c = split_comment(m.group("rest"))
    if val.strip():
        raise SystemExit(f"ERROR: {path}: only a block list (one '- item' per line) is supported")
    end = block_end(lines, i)
    item_ind = indent_of(lines[i]) + 2
    for j in range(i + 1, end):
        if not is_skip(lines[j]):
            item_ind = indent_of(lines[j])
            break
    text = " " * item_ind + f"- {item}"
    if comment:
        text = f"{text:<27}  # {comment}"
    return lines[:end] + [text + "\n"] + lines[end:], True


def write_atomic(path: str, text: str) -> None:
    mode = os.stat(path).st_mode & 0o777
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".cfgset.", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "--get":
        with open(argv[1], encoding="utf-8") as f:
            print(json.dumps(get_path(yaml.safe_load(f) or {}, argv[2])))
        return 0
    if argv and argv[0] == "--append" and len(argv) in (4, 5):
        path, key, item = argv[1], argv[2], argv[3]
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        new, changed = append_item(lines, key, item, argv[4] if len(argv) == 5 else "")
        if changed:
            got = get_path(yaml.safe_load("".join(new)) or {}, key)
            if not isinstance(got, list) or yaml.safe_load(item) not in got:
                print(f"ERROR: {path}: {key} does not contain {item} after the change; nothing written", file=sys.stderr)
                return 1
            write_atomic(path, "".join(new))
        print(("added" if changed else "present") + f" {key}: {item}")
        return 0
    if len(argv) < 3 or len(argv) % 2 == 0:
        print(__doc__, file=sys.stderr)
        return 1
    path = argv[0]
    pairs = list(zip(argv[1::2], argv[2::2]))
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    for key, value in pairs:
        if "\n" in value:
            print(f"ERROR: {key}: a value must be one line", file=sys.stderr)
            return 1
        lines = set_value(lines, key, value)
    data = yaml.safe_load("".join(lines)) or {}
    for key, value in pairs:
        if get_path(data, key) != yaml.safe_load(value):
            print(f"ERROR: {path}: {key} reads as {get_path(data, key)!r}, not {value}; nothing written", file=sys.stderr)
            return 1
    write_atomic(path, "".join(lines))
    for key, value in pairs:
        print(f"set {key}: {value}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001  (one clear line, no traceback for the operator)
        print(f"ERROR: cfgset: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
