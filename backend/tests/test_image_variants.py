from PIL import Image

from app.services.image_variants import generate_variants, image_variants


def test_variants_preserve_original_hash_urls_and_repair_missing_derivatives(tmp_path):
    source = tmp_path / "story" / "cover.png"
    source.parent.mkdir()
    Image.effect_noise((1800, 1000), 30).convert("RGB").save(source)
    original = source.read_bytes()
    variants = generate_variants(source, "cover", tmp_path)
    assert [v["width"] for v in variants] == [640, 960, 1440]
    assert source.read_bytes() == original
    assert image_variants("/images/story/cover.png", tmp_path) == variants
    first = tmp_path / variants[0]["url"].removeprefix("/images/")
    assert first.stat().st_size < len(original) * 0.3
    modified = first.stat().st_mtime_ns
    assert generate_variants(source, "cover", tmp_path) == variants
    assert first.stat().st_mtime_ns == modified
    first.unlink()
    assert len(image_variants("/images/story/cover.png", tmp_path)) == 2
    assert generate_variants(source, "cover", tmp_path) == variants
    Image.new("RGB", (1800, 1000), "red").save(source)
    assert image_variants("/images/story/cover.png", tmp_path) == []
    assert generate_variants(source, "cover", tmp_path)[0]["url"] != variants[0]["url"]


def test_no_upscale_external_or_traversal_urls(tmp_path):
    source = tmp_path / "avatar.png"
    Image.new("RGB", (200, 300)).save(source)
    variants = generate_variants(source, "avatar", tmp_path)
    assert [(v["width"], v["height"]) for v in variants] == [(128, 192), (200, 300)]
    for url in [
        "https://example.org/images/avatar.png",
        "/images/%2e%2e/avatar.png",
        "/images/missing.png",
    ]:
        assert image_variants(url, tmp_path) == []
