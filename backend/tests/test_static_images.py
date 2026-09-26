import hashlib
import mimetypes

import httpx
import pytest

from app.core.static_images import ImageStaticFiles


@pytest.mark.asyncio
async def test_only_content_addressed_clue_images_are_cached_immutably(tmp_path, monkeypatch):
    monkeypatch.setattr(mimetypes, "guess_type", lambda *args, **kwargs: ("text/plain", None))
    monkeypatch.setattr(mimetypes, "guess_file_type", lambda *args, **kwargs: ("text/plain", None))
    data = b"immutable derivative"
    folder = tmp_path / "scripts/s/clues"
    folder.mkdir(parents=True)
    name = f"asset-{hashlib.sha256(data).hexdigest()}.webp"
    (folder / name).write_bytes(data)
    (folder / "mutable.webp").write_bytes(data)
    (folder / "preview.json").write_text("{}")
    app = ImageStaticFiles(directory=tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/scripts/s/clues/{name}")
        assert response.content == data
        assert response.headers["content-type"] == "image/webp"
        assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
        cached = await client.get(
            f"/scripts/s/clues/{name}", headers={"If-None-Match": response.headers["etag"]}
        )
        assert cached.status_code == 304
        assert cached.headers["cache-control"] == response.headers["cache-control"]
        for path in ("mutable.webp", "preview.json"):
            assert "immutable" not in (await client.get(f"/scripts/s/clues/{path}")).headers.get(
                "cache-control", ""
            )


@pytest.mark.asyncio
async def test_hashed_avatar_variant_is_immutable_but_original_is_not(tmp_path):
    folder = tmp_path / "scripts/s/_variants/portrait-1234567890abcdef1234-v1"
    folder.mkdir(parents=True)
    (folder / "avatar-96.webp").write_bytes(b"avatar")
    (tmp_path / "portrait.png").write_bytes(b"original")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ImageStaticFiles(directory=tmp_path)),
        base_url="http://test",
    ) as client:
        derived = await client.get(
            "/scripts/s/_variants/portrait-1234567890abcdef1234-v1/avatar-96.webp"
        )
        assert "immutable" in derived.headers["cache-control"]
        assert "immutable" not in (await client.get("/portrait.png")).headers.get(
            "cache-control", ""
        )
