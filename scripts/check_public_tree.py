"""Check Git objects before publishing; never edit or remove worktree files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

DOCUMENTS = {
    "README.md",
    "PROJECT.md",
    "LICENSE",
    "frontend/public/lobby/NotoSerifSC-OFL.txt",
}
ROOT_FILES = {".gitattributes", ".gitignore", ".nvmrc", ".python-version", *DOCUMENTS}
ROOT_DIRS = {"backend", "frontend", "fixtures", "scripts", ".github", ".githooks"}
JSON_FILES = {
    "backend/app/data/sample.json",
    "fixtures/clue-citations.json",
    "fixtures/clue-citation-eval.json",
    "fixtures/gameplay-eval.json",
    "frontend/components.json",
    "frontend/package.json",
    "frontend/tsconfig.json",
    "frontend/tsconfig.app.json",
    "frontend/tsconfig.node.json",
}
FORBIDDEN_PARTS = {
    "docs",
    "notes",
    "reports",
    "screenshots",
    "recordings",
    "output",
    "tmp",
    "temp",
    ".local-data",
    ".codex",
    ".agents",
    ".claude",
    ".idea",
    ".vscode",
    "ops",
    "node_modules",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "playwright-report",
    "test-results",
    "private",
    "backups",
}
DOCUMENT_SUFFIXES = {
    ".md",
    ".mdx",
    ".markdown",
    ".rst",
    ".txt",
    ".pdf",
    ".doc",
    ".docx",
}
RUNTIME_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".jsonl",
    ".csv",
    ".har",
    ".sarif",
    ".mp4",
    ".webm",
    ".mp3",
    ".wav",
    ".zip",
    ".tar",
    ".gz",
    ".pem",
    ".key",
    ".p12",
    ".pyc",
}
FIXTURES = {
    "fixtures/clue-citations.json": (
        "backend/tests/test_evidence_citations.py",
        "frontend/src/lib/clueReferences.test.ts",
    ),
    "fixtures/clue-citation-eval.json": ("backend/scripts/clue_citation_eval.py",),
    "fixtures/gameplay-eval.json": ("backend/scripts/gameplay_eval.py",),
}
SECRET_PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        rb"\b(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})\b"
    ),
    re.compile(
        rb"(?i)(?:api[_-]?key|secret|access[_-]?token|password)\s*[=:]\s*[\"']([A-Za-z0-9+/=_-]{32,})[\"']"
    ),
]


def git(*args: str, input_data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *args], input=input_data, check=True, capture_output=True
    ).stdout


def path_errors(path: str) -> list[str]:
    p = PurePosixPath(path)
    lower = path.lower()
    errors = []
    if p.parts[0] not in ROOT_DIRS and path not in ROOT_FILES:
        errors.append(
            "unapproved root path; keep implementation in an existing source directory"
        )
    if {part.lower() for part in p.parts} & FORBIDDEN_PARTS:
        errors.append(
            "local/runtime directory; move to an ignored local directory and untrack"
        )
    if p.suffix.lower() in DOCUMENT_SUFFIXES and path not in DOCUMENTS:
        errors.append(
            "document not allowlisted; put essential instructions in PROJECT.md, keep notes local"
        )
    if p.suffix.lower() == ".json" and path not in JSON_FILES:
        errors.append(
            "unregistered data file; register its implementation consumer or keep it local"
        )
    if p.suffix.lower() in {".yaml", ".yml"} and path not in {
        ".github/workflows/ci.yml",
        "frontend/pnpm-lock.yaml",
    }:
        errors.append("unregistered configuration/data file; keep reports local")
    if p.suffix.lower() in RUNTIME_SUFFIXES or lower.endswith(("-wal", "-shm")):
        errors.append("runtime, archive or credential file; keep local and untrack")
    if ".env" in p.name.lower() and path != "backend/.env.example":
        errors.append("environment file; only backend/.env.example may be public")
    if p.suffix.lower() not in {".py", ".ts", ".tsx", ".js"} and re.search(
        r"(?:^|[/_.-])(?:memory|report|handoff|scratch|evaluation-results|credentials)(?:[/_.-]|$)",
        lower,
    ):
        errors.append("process record or private material; keep local and untrack")
    return errors


def content_errors(path: str, data: bytes) -> list[str]:
    errors = path_errors(path)
    if len(data) > 5 * 1024 * 1024:
        errors.append(
            "file exceeds 5 MiB; reduce the product asset or keep generated output local"
        )
    if any(pattern.search(data) for pattern in SECRET_PATTERNS):
        errors.append(
            "possible credential; remove it and rotate any exposed real credential"
        )
    return errors


def tree_files(ref: str | None) -> dict[str, str]:
    if ref is None:
        rows = git("ls-files", "--stage", "-z").split(b"\0")
    else:
        rows = git("ls-tree", "-r", "-z", ref).split(b"\0")
    files = {}
    for row in rows:
        if not row:
            continue
        metadata, name = row.split(b"\t", 1)
        fields = metadata.split()
        if fields[0] not in {b"100644", b"100755"}:
            raise ValueError(f"unsupported file mode: {name.decode('utf-8')}")
        if ref is None and fields[2] != b"0":
            raise ValueError("resolve index conflicts before checking the public tree")
        files[name.decode("utf-8")] = fields[1 if ref is None else 2].decode()
    return files


def check_tree(ref: str | None, *, contracts: bool = True) -> list[str]:
    files = tree_files(ref)
    errors = []
    blobs = {}
    objects = list(dict.fromkeys(files.values()))
    batch = git("cat-file", "--batch", input_data=("\n".join(objects) + "\n").encode())
    by_oid = {}
    offset = 0
    for oid in objects:
        end = batch.index(b"\n", offset)
        size = int(batch[offset:end].split()[-1])
        by_oid[oid] = batch[end + 1 : end + 1 + size]
        offset = end + size + 2
    for path, oid in files.items():
        data = by_oid[oid]
        blobs[path] = data
        errors.extend(f"{path}: {error}" for error in content_errors(path, data))
    if not contracts:
        return errors
    for path in DOCUMENTS | set(FIXTURES):
        if path not in files:
            errors.append(f"{path}: required public file missing")
    for path, consumers in FIXTURES.items():
        if path not in files:
            continue
        try:
            json.loads(blobs[path])
        except ValueError:
            errors.append(f"{path}: invalid JSON fixture")
        for consumer in consumers:
            if PurePosixPath(path).name.encode() not in blobs.get(consumer, b""):
                errors.append(
                    f"{path}: expected consumer {consumer} missing its fixture reference"
                )
    for path in ("README.md", "PROJECT.md"):
        for target in re.findall(
            r"!?\[[^\]]*\]\(([^)]+)\)", blobs.get(path, b"").decode("utf-8")
        ):
            target = target.strip("<>").split("#", 1)[0]
            parsed = urlparse(target)
            if parsed.scheme:
                if parsed.scheme != "https" or not parsed.netloc:
                    errors.append(f"{path}: invalid public link {target}")
            elif target and unquote(target).removeprefix("./") not in files:
                errors.append(f"{path}: link target absent from public tree: {target}")
    return errors


def outgoing(local_sha: str, remote_sha: str) -> list[str]:
    args = ["rev-list", "--reverse", local_sha]
    if remote_sha != "0" * 40:
        args.extend(["^" + remote_sha])
    else:
        args.extend(["--not", "--remotes"])
    return git(*args).decode().splitlines()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--pre-push", action="store_true")
    parser.add_argument("--range", dest="revision_range")
    args = parser.parse_args()
    targets: list[str | None] = [None] if args.staged else ["HEAD"]
    if args.pre_push:
        targets = []
        for line in sys.stdin:
            _local_ref, local_sha, _remote_ref, remote_sha = line.split()
            if local_sha != "0" * 40:
                targets.extend(outgoing(local_sha, remote_sha))
                targets.append(local_sha)
    if args.revision_range:
        targets.extend(
            git("rev-list", "--reverse", args.revision_range).decode().splitlines()
        )
    failed = False
    for ref in dict.fromkeys(targets):
        errors = check_tree(ref)
        if errors:
            failed = True
            print(f"Public tree rejected ({ref or 'index'}):", file=sys.stderr)
            for error in errors:
                print("  " + error, file=sys.stderr)
    if not failed:
        print(f"Public tree passed ({len(set(targets))} Git trees).")
    return int(failed)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"Public tree check failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
