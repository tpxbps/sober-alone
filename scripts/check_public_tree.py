"""Fail when the public source candidate contains private or generated artifacts."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MAX_BLOB_BYTES = 5 * 1024 * 1024
MEDIA_SUFFIXES = {
    ".aac",
    ".avi",
    ".flac",
    ".m4a",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".wav",
    ".webm",
}
DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
DENIED_PARTS = {
    ".claude",
    ".local-data",
    ".pnpm-store",
    ".uv-cache",
    "chroma",
    "dist",
    "node_modules",
}
DENIED_PREFIXES = ("backend/data/", "frontend/public/audio/")
DENIED_NAMES = {"beian-icon.png"}
SECRET_PATTERNS = {
    "generic sk token": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def candidate_paths() -> list[PurePosixPath]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [PurePosixPath(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]


def is_denied(path: PurePosixPath) -> str | None:
    normalized = path.as_posix()
    lowered_parts = {part.lower() for part in path.parts}
    if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
        return "environment file"
    if path.suffix.lower() in MEDIA_SUFFIXES:
        return "generated or bundled audio/video"
    if path.suffix.lower() in DATABASE_SUFFIXES:
        return "runtime database"
    if lowered_parts & DENIED_PARTS:
        return "generated/private directory"
    if normalized.lower().startswith(DENIED_PREFIXES):
        return "legacy runtime directory"
    if path.name.lower() in DENIED_NAMES:
        return "out-of-scope asset"
    return None


def scan_text(path: Path) -> list[str]:
    if path.name == ".env.example":
        findings = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            sensitive_name = any(marker in name.upper() for marker in ("KEY", "TOKEN", "SECRET"))
            if sensitive_name and value.strip():
                findings.append(f"non-empty secret field in .env.example:{line_number}")
        return findings

    if path.stat().st_size > 1_000_000:
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    return [label for label, pattern in SECRET_PATTERNS.items() if pattern.search(content)]


def main() -> int:
    failures: list[str] = []
    paths = candidate_paths()
    for relative in paths:
        absolute = ROOT / Path(*relative.parts)
        if not absolute.is_file():
            continue
        reason = is_denied(relative)
        if reason:
            failures.append(f"{relative.as_posix()}: {reason}")
            continue
        size = absolute.stat().st_size
        if size >= MAX_BLOB_BYTES:
            failures.append(
                f"{relative.as_posix()}: {size} bytes exceeds the {MAX_BLOB_BYTES}-byte limit"
            )
        for finding in scan_text(absolute):
            failures.append(f"{relative.as_posix()}: {finding}")

    if failures:
        print("Public-tree audit failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    largest = max(
        ((ROOT / Path(*path.parts)).stat().st_size, path.as_posix())
        for path in paths
        if (ROOT / Path(*path.parts)).is_file()
    )
    print(
        f"Public-tree audit passed: {len(paths)} files; largest={largest[1]} ({largest[0]} bytes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
