import os
from pathlib import Path

from PIL import Image
import pytest

from dog_walker.vision import DEFAULT_MAX_EDGE, MAX_SOURCE_BYTES, prepare_inference_image
from dog_walker.workflow import WalkerError


def image_fixture(root, name="source.png", size=(1254, 1900), color=(25, 80, 130, 128)):
    path = root / name
    Image.new("RGBA", size, color).save(path)
    return path


def test_inference_image_is_bounded_private_and_does_not_change_original(tmp_path):
    chat = tmp_path / "chat"
    attachments = chat / "attachments"
    attachments.mkdir(parents=True)
    source = image_fixture(attachments)
    original = source.read_bytes()

    result = prepare_inference_image(source, chat)

    assert result == prepare_inference_image(source, chat)
    assert result.parent == attachments / "inference"
    assert result.stat().st_mode & 0o777 == 0o600
    assert result.parent.stat().st_mode & 0o777 == 0o700
    with Image.open(result) as processed:
        assert processed.format == "JPEG"
        assert processed.mode == "RGB"
        assert max(processed.size) == DEFAULT_MAX_EDGE
        assert processed.getpixel((0, 0)) != (25, 80, 130)  # Alpha was composited on white.
    assert source.read_bytes() == original


def test_exif_orientation_is_applied_before_resize(tmp_path):
    chat = tmp_path / "chat"
    attachments = chat / "attachments"
    attachments.mkdir(parents=True)
    source = attachments / "oriented.jpg"
    image = Image.new("RGB", (600, 300), "red")
    exif = Image.Exif()
    exif[274] = 6
    image.save(source, exif=exif)

    with Image.open(prepare_inference_image(source, chat)) as processed:
        assert processed.size == (192, 384)


def test_rejects_corrupt_oversize_and_escaping_sources(tmp_path):
    chat = tmp_path / "chat"
    attachments = chat / "attachments"
    attachments.mkdir(parents=True)
    corrupt = attachments / "corrupt.png"
    corrupt.write_bytes(b"\x89PNG\r\n\x1a\nnot really a png")
    with pytest.raises(WalkerError, match="corrupt or cannot be decoded"):
        prepare_inference_image(corrupt, chat)

    huge = attachments / "huge.png"
    huge.write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
    with pytest.raises(WalkerError, match="smaller than 12 MB"):
        prepare_inference_image(huge, chat)

    outside = image_fixture(tmp_path, "outside.png", (10, 10))
    with pytest.raises(WalkerError, match="no longer available"):
        prepare_inference_image(outside, chat)


def test_rejects_decompression_bomb_before_decode(tmp_path, monkeypatch):
    chat = tmp_path / "chat"
    attachments = chat / "attachments"
    attachments.mkdir(parents=True)
    source = attachments / "bomb.png"
    source.write_bytes(b"test image bytes")

    class Header:
        format = "PNG"
        size = (8000, 5001)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def load(self):
            raise AssertionError("oversized image must not be decoded")

    monkeypatch.setattr("dog_walker.vision.Image.open", lambda _: Header())

    with pytest.raises(WalkerError, match="maximum 40 megapixels"):
        prepare_inference_image(source, chat)


def test_rejects_symlinked_attachment_and_cache_directory(tmp_path):
    chat = tmp_path / "chat"
    attachments = chat / "attachments"
    attachments.mkdir(parents=True)
    original = image_fixture(tmp_path, "outside.png", (10, 10))
    link = attachments / "linked.png"
    link.symlink_to(original)
    with pytest.raises(WalkerError, match="no longer available"):
        prepare_inference_image(link, chat)

    link.unlink()
    (attachments / "inference").symlink_to(tmp_path, target_is_directory=True)
    local = image_fixture(attachments, "local.png", (10, 10))
    with pytest.raises(WalkerError, match="private image cache"):
        prepare_inference_image(local, chat)


def test_max_edge_is_bounded():
    with pytest.raises(ValueError, match="max_edge"):
        prepare_inference_image("unused", "unused", max_edge=4096)
