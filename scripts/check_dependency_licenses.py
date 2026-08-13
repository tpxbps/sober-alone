"""Audit installed Python and pnpm package metadata for denied licenses."""

from __future__ import annotations

import importlib.metadata
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DENIED = re.compile(r"(?<!L)GPL(?:-|\b)|AGPL|SSPL|BUSL|Commons Clause", re.IGNORECASE)
KNOWN_LICENSES = {"zhipuai": "MIT"}


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def python_lock_packages() -> set[tuple[str, str]]:
    data = tomllib.loads((ROOT / "backend" / "uv.lock").read_text(encoding="utf-8"))
    return {(normalize(package["name"]), package["version"]) for package in data["package"]}


def python_metadata() -> list[tuple[str, str, str]]:
    locked = python_lock_packages()
    rows: list[tuple[str, str, str]] = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name", "")
        key = (normalize(name), distribution.version)
        if key not in locked:
            continue
        license_text = (distribution.metadata.get("License-Expression") or "").strip()
        if not license_text:
            classifiers = distribution.metadata.get_all("Classifier") or []
            license_text = "; ".join(
                value.removeprefix("License :: ")
                for value in classifiers
                if value.startswith("License :: ")
            )
        if not license_text:
            license_text = (distribution.metadata.get("License") or "").strip()
        license_text = license_text or KNOWN_LICENSES.get(normalize(name), "UNKNOWN")
        rows.append((name, distribution.version, license_text))
    return rows


def node_metadata() -> list[tuple[str, str, str]]:
    store = ROOT / "frontend" / "node_modules" / ".pnpm"
    rows: dict[tuple[str, str], tuple[str, str, str]] = {}
    if not store.exists():
        raise RuntimeError("frontend/node_modules is missing; run the frozen pnpm install first")
    for manifest in store.glob("*/node_modules/**/package.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        name = data.get("name")
        version = data.get("version")
        if not name or not version:
            continue
        value = data.get("license", "UNKNOWN")
        if isinstance(value, dict):
            value = value.get("type", "UNKNOWN")
        elif isinstance(value, list):
            value = " OR ".join(
                item.get("type", "UNKNOWN") if isinstance(item, dict) else str(item)
                for item in value
            )
        rows[(name, version)] = (name, version, str(value or "UNKNOWN"))
    return sorted(rows.values(), key=lambda row: (row[0].lower(), row[1]))


def main() -> int:
    try:
        rows = python_metadata() + node_metadata()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    denied = [row for row in rows if DENIED.search(row[2])]
    unknown = [row for row in rows if row[2] == "UNKNOWN"]
    if denied:
        print("Denied dependency licenses:", file=sys.stderr)
        for name, version, license_text in denied:
            print(f"- {name}=={version}: {license_text}", file=sys.stderr)
        return 1
    print(
        f"Dependency-license audit passed: {len(rows)} installed packages; "
        f"unknown metadata={len(unknown)}"
    )
    if unknown:
        print("Unknown metadata (manual notice review required):")
        for name, version, _ in unknown:
            print(f"- {name}=={version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
