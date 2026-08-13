"""Generate a deterministic SPDX 2.3 dependency SBOM from both lock files."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "sbom.spdx.json"


def spdx_id(ecosystem: str, name: str, version: str) -> str:
    digest = hashlib.sha256(f"{ecosystem}:{name}:{version}".encode()).hexdigest()[:16]
    return f"SPDXRef-Package-{ecosystem}-{digest}"


def python_packages() -> set[tuple[str, str, str]]:
    data = tomllib.loads((ROOT / "backend" / "uv.lock").read_text(encoding="utf-8"))
    return {("pypi", package["name"], package["version"]) for package in data["package"]}


def split_pnpm_key(key: str) -> tuple[str, str] | None:
    key = key.strip().strip("'\"")
    if key.startswith("@"):
        separator = key.rfind("@")
        if separator <= key.find("/"):
            return None
    else:
        separator = key.find("@")
    if separator <= 0:
        return None
    name, version = key[:separator], key[separator + 1 :]
    version = version.split("(", 1)[0]
    return (name, version) if name and version else None


def node_packages() -> set[tuple[str, str, str]]:
    packages: set[tuple[str, str, str]] = set()
    in_packages = False
    for line in (ROOT / "frontend" / "pnpm-lock.yaml").read_text(encoding="utf-8").splitlines():
        if line == "packages:":
            in_packages = True
            continue
        if in_packages and line == "snapshots:":
            break
        if not in_packages:
            continue
        match = re.match(r"^  (.+):$", line)
        if not match:
            continue
        parsed = split_pnpm_key(match.group(1))
        if parsed:
            packages.add(("npm", parsed[0], parsed[1]))
    return packages


def make_package(ecosystem: str, name: str, version: str) -> dict[str, object]:
    package_id = spdx_id(ecosystem, name, version)
    purl = f"pkg:{ecosystem}/{quote(name, safe='@/')}@{quote(version, safe='.-_+')}"
    return {
        "SPDXID": package_id,
        "name": name,
        "versionInfo": version,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION",
        "copyrightText": "NOASSERTION",
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": purl,
            }
        ],
    }


def main() -> None:
    dependencies = sorted(python_packages() | node_packages())
    packages = [make_package(*dependency) for dependency in dependencies]
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "sober-alone-0.1.0-dependencies",
        "documentNamespace": "https://github.com/tpxbps/sober-alone/sbom/v0.1.0",
        "creationInfo": {
            "created": "2026-08-13T00:00:00Z",
            "creators": ["Tool: scripts/generate_sbom.py"],
            "licenseListVersion": "3.26",
        },
        "packages": packages,
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": package["SPDXID"],
            }
            for package in packages
        ],
    }
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} with {len(packages)} packages")


if __name__ == "__main__":
    main()
