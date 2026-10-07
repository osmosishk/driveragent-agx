"""Model store command line: check a model package and put it into the store (docs/DEPLOY_MODEL.md).

  python -m tools.model_store_cli validate <package dir> [--store ~/agx-models]
  python -m tools.model_store_cli deploy <package dir> [--store ~/agx-models] [--user U]
  python -m tools.model_store_cli deploy --staged <store>/_incoming/<dir> [--store ~/agx-models] [--user U]

validate: manifest.yaml must pass controller.manifest.validate() for the folder <store>/<name>/<version> that the
package gets; every file of the manifest must have a relative path inside the package, must exist and must have the
sha256 of the manifest. The package must not contain symbolic links or the files that a build writes (build.json,
build.log). Exit 0 when valid, 1 when there is a problem (each problem is printed).

deploy: validate, refuse when <store>/<name>/<version> exists (owner rule M2: a version is never overwritten or
deleted), copy the package into <store>/_incoming/<name>-<version>-<random>/, check the sha256 values there again,
make the files read-only and rename the folder to <store>/<name>/<version> (one atomic os.rename). One audit line goes
into <store>/_state/audit.jsonl (source "command-line"). deploy does NOT build and does NOT activate: the catalog then
shows the version as NEEDS BUILD (ONNX only) or REGISTERED (engine). A package with the expected state FAILED is
refused (it could never be removed again).

--staged: the package is already in <store>/_incoming/ (tools/deploy_model.sh copied it there). It is renamed into
place after the same checks. A refused or failed staged package stays in _incoming for inspection.
"""
from __future__ import annotations

import argparse
import fcntl
import getpass
import os
import secrets
import shutil
import stat
import sys
from contextlib import contextmanager

import yaml

from controller import audit, catalog, manifest as mf
from controller.store import DEFAULT_ROOT, Store, sha256_file

INCOMING = "_incoming"
LOCK = ".deploy.lock"
BUILD_OUTPUTS = ("build.json", "build.log")   # written by controller/builder.py in the version folder
SOURCE = "command-line"


def store_root(store: str | None) -> str:
    return os.path.abspath(os.path.expanduser(store or DEFAULT_ROOT))


def _inside(path: str, folder: str) -> bool:
    """True when path is folder or a path below it (real paths)."""
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def read_manifest(pkg: str) -> tuple[dict | None, list[str]]:
    path = os.path.join(pkg, mf.MANIFEST)
    if not os.path.isfile(path):
        return None, [f"no {mf.MANIFEST} in {pkg}"]
    try:
        with open(path, encoding="utf-8") as f:
            d = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        return None, [f"{mf.MANIFEST} cannot be read: {e}"]
    if not isinstance(d, dict):
        return None, [f"{mf.MANIFEST} is not a YAML mapping"]
    return d, []


def target_folder(root: str, d: dict) -> str:
    """<store>/<name>/<version> of this manifest (name and version as written; validate() checks them)."""
    return os.path.join(root, str(d.get("name") or "?"), str(d.get("version") or "?"))


def file_problems(pkg: str, d: dict) -> list[str]:
    """Relative path inside the package, regular file, sha256 = manifest, for every file of the manifest."""
    probs = []
    files = d.get("files") if isinstance(d.get("files"), list) else []
    for i, f in enumerate(files):
        if not isinstance(f, dict) or not f.get("path"):
            continue                                   # validate() reports it
        p = str(f["path"])
        where = f"files[{i}] {p}"
        if os.path.isabs(p) or p.startswith("~"):
            probs.append(f"{where}: the path must be relative to the package folder (no absolute path)")
            continue
        if ".." in p.replace("\\", "/").split("/"):
            probs.append(f"{where}: the path must stay inside the package folder (no '..')")
            continue
        full = os.path.normpath(os.path.join(pkg, p))
        if not _inside(full, pkg):
            probs.append(f"{where}: the path must stay inside the package folder")
            continue
        if os.path.islink(full):
            probs.append(f"{where}: a symbolic link is not permitted (put the real file into the package)")
            continue
        if not os.path.isfile(full):
            probs.append(f"{where}: the file does not exist in the package")
            continue
        want = str(f.get("sha256") or "").lower()
        if not mf.SHA_RE.match(want):
            continue                                   # validate() reports it
        got = sha256_file(full)
        if got != want:
            probs.append(f"{where}: sha256 does not agree (manifest {want}, file {got})")
    return probs


def tree_problems(pkg: str) -> list[str]:
    """No symbolic links, no special files and no build output files anywhere in the package."""
    probs = []
    for dirpath, dirnames, filenames in os.walk(pkg):
        for n in dirnames + filenames:
            p = os.path.join(dirpath, n)
            rel = os.path.relpath(p, pkg)
            if os.path.islink(p):
                probs.append(f"{rel}: a symbolic link is not permitted in a package")
            elif n in filenames and not stat.S_ISREG(os.lstat(p).st_mode):
                probs.append(f"{rel}: only regular files and folders are permitted in a package")
        if dirpath == pkg:
            probs += [f"{n}: a package must not contain {n} (the build on this AGX writes it)"
                      for n in BUILD_OUTPUTS if n in filenames]
    return probs


def validate_package(pkg: str, root: str) -> tuple[dict | None, list[str]]:
    """(manifest dict, problems). The manifest is checked for the folder <store>/<name>/<version>."""
    pkg = os.path.abspath(pkg)
    if not os.path.isdir(pkg):
        return None, [f"{pkg} is not a folder"]
    d, probs = read_manifest(pkg)
    if d is None:
        return None, probs
    probs = mf.validate(d, target_folder(root, d))
    probs += tree_problems(pkg)
    probs += file_problems(pkg, d)
    return d, probs


def expected_state(pkg: str, root: str, d: dict) -> tuple[str, str | None]:
    """(catalog state, reason) of this package as a store version (no check, not live, no job)."""
    m = mf.Manifest(os.path.abspath(pkg), d, [])
    e = catalog.entry(m, Store(root), None, None, None, None)
    return e["state"], e["reason"]


def make_read_only(folder: str) -> None:
    """Files read-only (r--r--r--); folders stay writable, so that a build can add its engine and build.json."""
    for dirpath, _dirs, filenames in os.walk(folder):
        for n in filenames:
            p = os.path.join(dirpath, n)
            os.chmod(p, stat.S_IMODE(os.lstat(p).st_mode) & ~0o222)


@contextmanager
def deploy_lock(incoming: str):
    """One deploy at a time in this store (flock on <store>/_incoming/.deploy.lock)."""
    with open(os.path.join(incoming, LOCK), "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def next_step(name: str, version: str, state: str) -> str:
    if state == "NEEDS BUILD":
        return (f"Next step: build the engine on this AGX (build action of {name}@{version}: "
                "docs/MODEL_CONTROL_API.md or the dashboards), then wait for READY and activate it.")
    if state == "REGISTERED":
        return f"Next step: the controller runs the checks of {name}@{version}. When it is READY, activate it."
    if state == "NO ADAPTER":
        return f"Next step: add an adapter for this type (docs/ADD_MODEL_TYPE.md). {name}@{version} cannot run now."
    return "Next step: see the reason in the catalog (GET /api/models/catalog)."


class Deployer:
    def __init__(self, root: str, user: str):
        self.root = root
        self.user = user
        self.state_dir = os.path.join(root, "_state")
        self.incoming = os.path.join(root, INCOMING)

    def _audit(self, d: dict | None, result: str, reason: str | None, **extra) -> None:
        name = audit.clean((d or {}).get("name"), 48) or None
        version = audit.clean((d or {}).get("version"), 32) or None
        rec = audit.append(self.state_dir, SOURCE, self.user, "deploy", name, version, result,
                           None if reason is None else reason[:500], **extra)
        if rec.get("audit_write_error"):
            print(f"WARNING: the audit line was not written: {rec['audit_write_error']}", file=sys.stderr)

    def refuse(self, d: dict | None, probs: list[str], **extra) -> int:
        for p in probs:
            print(f"PROBLEM: {p}", file=sys.stderr)
        self._audit(d, "refused", "; ".join(probs), **extra)
        print("REFUSED: nothing was changed in the store.", file=sys.stderr)
        return 1

    def deploy(self, pkg: str, staged: bool) -> int:
        pkg = os.path.abspath(pkg)
        if not os.path.isdir(self.root):
            print(f"PROBLEM: the store {self.root} does not exist (check --store)", file=sys.stderr)
            return 1
        os.makedirs(self.incoming, exist_ok=True)
        extra = {"package": audit.clean(pkg, 200)}
        if staged:
            if os.path.realpath(os.path.dirname(pkg)) != os.path.realpath(self.incoming) or os.path.islink(pkg):
                return self.refuse(None, [f"--staged needs a folder directly in {self.incoming} (got {pkg})"], **extra)
        elif _inside(pkg, self.root):
            return self.refuse(None, [f"the package {pkg} is in the store already: give a folder outside "
                                      f"{self.root}, or use --staged for a folder in {self.incoming}"], **extra)
        d, probs = validate_package(pkg, self.root)
        if not probs:
            state, reason = expected_state(pkg, self.root, d)
            if state == "FAILED":
                probs = [f"the catalog would show this version as FAILED ({reason}); a version cannot be removed "
                         "from the store, so it is not deployed"]
        if probs:
            rc = self.refuse(d, probs, **extra)
            if staged:
                print(f"The package stays in {pkg} for inspection. Remove it with: rm -r '{pkg}'", file=sys.stderr)
            return rc
        name, version = str(d["name"]), str(d["version"])
        target = os.path.join(self.root, name, version)
        work = pkg
        try:
            with deploy_lock(self.incoming):
                if os.path.lexists(target):
                    rc = self.refuse(d, [f"{target} exists: a version is never overwritten (owner rule M2). "
                                         "Give the package a new version"], **extra)
                    if staged:
                        print(f"The package stays in {pkg}. Remove it with: rm -r '{pkg}'", file=sys.stderr)
                    return rc
                if not staged:
                    work = os.path.join(self.incoming, f"{name}-{version}-{secrets.token_hex(4)}")
                    print(f"copy {pkg} -> {work}")
                    shutil.copytree(pkg, work, symlinks=True)
                again = tree_problems(work) + file_problems(work, d)   # the copy, and the staged upload
                if again:
                    if not staged:
                        shutil.rmtree(work, ignore_errors=True)
                    return self.refuse(d, ["after the copy: " + p for p in again], **extra)
                make_read_only(work)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.rename(work, target)
        except OSError as e:
            print(f"FAILED: {e}", file=sys.stderr)
            if not staged and work != pkg and os.path.isdir(work):
                shutil.rmtree(work, ignore_errors=True)
            self._audit(d, "failed", f"{type(e).__name__}: {e}", **extra)
            return 1
        state, reason = expected_state(target, self.root, d)
        self._audit(d, "ok", None, state=state, **extra)
        print(f"DEPLOYED {mf.key(name, version)} -> {target}")
        print(f"Expected state in the catalog: {state}" + (f" ({reason})" if reason else ""))
        print(next_step(name, version, state))
        return 0


def cmd_validate(args) -> int:
    root = store_root(args.store)
    d, probs = validate_package(args.package, root)
    for p in probs:
        print(f"PROBLEM: {p}")
    if probs:
        print(f"NOT VALID: {len(probs)} problem(s)")
        return 1
    state, reason = expected_state(args.package, root, d)
    print(f"VALID: {mf.key(str(d['name']), str(d['version']))} -> {target_folder(root, d)}")
    print(f"Expected state after deploy: {state}" + (f" ({reason})" if reason else ""))
    return 0


def cmd_deploy(args) -> int:
    root = store_root(args.store)
    user = args.user or os.environ.get("USER") or getpass.getuser()
    return Deployer(root, user).deploy(args.staged or args.package, staged=bool(args.staged))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.model_store_cli", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="check a model package (no change)")
    v.add_argument("package")
    v.add_argument("--store", default=DEFAULT_ROOT)
    dp = sub.add_parser("deploy", help="put a model package into the store (no build, no activation)")
    dp.add_argument("package", nargs="?")
    dp.add_argument("--staged", metavar="DIR", help=f"a package folder in <store>/{INCOMING}/")
    dp.add_argument("--store", default=DEFAULT_ROOT)
    dp.add_argument("--user", help="the person for the audit line (default: $USER)")
    args = ap.parse_args(argv)
    if args.cmd == "deploy" and bool(args.package) == bool(args.staged):
        ap.error("deploy needs a package folder or --staged <folder>, not both")
    return cmd_validate(args) if args.cmd == "validate" else cmd_deploy(args)


if __name__ == "__main__":
    sys.exit(main())
