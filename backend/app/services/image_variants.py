"""Responsive, immutable image derivatives. Originals are never overwritten."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PIL import Image, ImageOps

from app.core.config import settings

logger = logging.getLogger(__name__)
VARIANT_VERSION = 1
WIDTHS = {"cover": (640, 960, 1440), "avatar": (128, 512)}


def _signature(path: Path) -> list[int]:
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns]


def _manifest(path: Path) -> Path:
    return path.with_name(path.name + ".variants.json")


def _source(url: str, root: Path) -> Path | None:
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/images/"):
        return None
    path = (root / unquote(parsed.path.removeprefix("/images/"))).resolve()
    return path if path.is_relative_to(root.resolve()) and path.is_file() else None


def image_variants(url: str | None, root: Path | None = None) -> list[dict]:
    """Only advertise completed derivatives matching the current original."""
    root = Path(root or settings.image_dir).resolve()
    try:
        source = _source(url or "", root)
        if source is None:
            return []
        manifest = json.loads(_manifest(source).read_text(encoding="utf-8"))
        if manifest.get("version") != VARIANT_VERSION or manifest["source_stat"] != _signature(
            source
        ):
            return []
        return [
            item
            for item in manifest["variants"]
            if isinstance(item.get("width"), int)
            and item["width"] > 0
            and _source(item.get("url", ""), root) is not None
        ]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def generate_variants(source: Path, kind: str, root: Path | None = None) -> list[dict]:
    root = Path(root or settings.image_dir).resolve()
    source = source.resolve(strict=True)
    if not source.is_relative_to(root) or kind not in WIDTHS:
        raise ValueError("Image must be inside the configured image root")
    url = "/images/" + source.relative_to(root).as_posix()
    existing = image_variants(url, root)
    if existing:
        with Image.open(source) as original:
            expected = {
                min(width, ImageOps.exif_transpose(original).width) for width in WIDTHS[kind]
            }
        if {item["width"] for item in existing} == expected:
            return existing
    signature = _signature(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:20]
    folder = source.parent / "_variants" / f"{source.stem}-{digest}-v{VARIANT_VERSION}"
    folder.mkdir(parents=True, exist_ok=True)
    variants = []
    with Image.open(source) as original:
        original = ImageOps.exif_transpose(original).convert(
            "RGBA" if "A" in original.getbands() else "RGB"
        )
        for width in sorted({min(width, original.width) for width in WIDTHS[kind]}):
            target = folder / f"{kind}-{width}.webp"
            if not target.exists():
                resized = original.copy()
                resized.thumbnail((width, original.height), Image.Resampling.LANCZOS)
                temporary = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
                try:
                    resized.save(
                        temporary, format="WEBP", quality=80 if width <= 960 else 86, method=6
                    )
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
            with Image.open(target) as derivative:
                variants.append(
                    {
                        "url": "/images/" + target.relative_to(root).as_posix(),
                        "width": derivative.width,
                        "height": derivative.height,
                    }
                )
    if signature != _signature(source):
        raise ValueError("Original changed during resizing; retry with the current original")
    manifest = {
        "version": VARIANT_VERSION,
        "source_stat": signature,
        "source_hash": digest,
        "kind": kind,
        "variants": variants,
    }
    target = _manifest(source)
    temporary = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(manifest), encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return variants


def prepare_variants(source: Path, kind: str) -> None:
    try:
        generate_variants(source, kind)
    except (OSError, ValueError, Image.DecompressionBombError):
        logger.warning("Image derivatives unavailable; retaining original", exc_info=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=settings.image_dir)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    totals = {"originals": 0, "original_bytes": 0, "small_variant_bytes": 0, "failed": 0}
    for source in root.rglob("*"):
        if (
            not source.is_file()
            or "_variants" in source.parts
            or source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}
        ):
            continue
        kind = (
            "cover" if source.stem == "cover" else "avatar" if "avatars" in source.parts else None
        )
        if not kind:
            continue
        totals["originals"] += 1
        totals["original_bytes"] += source.stat().st_size
        if not args.dry_run:
            try:
                variants = generate_variants(source, kind, root)
                totals["small_variant_bytes"] += _source(variants[0]["url"], root).stat().st_size
            except (OSError, ValueError, Image.DecompressionBombError):
                totals["failed"] += 1
    print(json.dumps(totals))
    return bool(totals["failed"])


if __name__ == "__main__":
    raise SystemExit(main())
