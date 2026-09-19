import hashlib

import httpx
import pytest

from app.core.static_images import ImageStaticFiles


@pytest.mark.asyncio
async def test_only_content_addressed_clue_images_are_cached_immutably(tmp_path):
    data = b"immutable derivative"
    folder = tmp_path / "scripts/s/clues"
    folder.mkdir(parents=True)
    name = f"asset-{hashlib.sha256(data).hexdigest()}.webp"
    (folder / name).write_bytes(data)
    (folder / "mutable.webp").write_bytes(data)
    (folder / "preview.json").write_text("{}")
    app = ImageStaticFiles(directory=tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
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
