"""Create bounded, private image copies for local model inference."""
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import tempfile

from PIL import Image, ImageOps, UnidentifiedImageError

from .workflow import WalkerError

MAX_SOURCE_BYTES = 12 * 1024 * 1024
MAX_SOURCE_PIXELS = 40_000_000
DEFAULT_MAX_EDGE = 384
_CACHE_VERSION = b"dog-walk-inference-jpeg-v1\0"
_FORMATS = {"PNG", "JPEG", "WEBP"}


def prepare_inference_image(image_path, conversation_path, *, max_edge=DEFAULT_MAX_EDGE):
    """Return a cached, bounded JPEG path without modifying the saved attachment.

    The source must be a regular image file directly contained by the
    conversation's attachments directory. Decoding is limited to 40 MP and
    the encoded image's longest edge defaults to 384 px.
    """
    if not isinstance(max_edge, int) or isinstance(max_edge, bool) or not 64 <= max_edge <= 2048:
        raise ValueError("max_edge must be an integer from 64 through 2048")

    chat_root = Path(conversation_path).resolve()
    attachments = chat_root / "attachments"
    source = Path(image_path)
    if source.is_symlink():
        raise WalkerError("A saved image attachment is no longer available")
    source = source.resolve()
    if not source.is_relative_to(attachments) or source.parent != attachments or not source.is_file():
        raise WalkerError("A saved image attachment is no longer available")
    try:
        if source.stat().st_size > MAX_SOURCE_BYTES:
            raise WalkerError("Image attachments must be smaller than 12 MB")
        content = source.read_bytes()
    except OSError as exc:
        raise WalkerError("A saved image attachment is no longer available") from exc
    if len(content) > MAX_SOURCE_BYTES:
        raise WalkerError("Image attachments must be smaller than 12 MB")

    inference = attachments / "inference"
    if inference.is_symlink():
        raise WalkerError("The private image cache is not available")
    inference.mkdir(mode=0o700, exist_ok=True)
    inference = inference.resolve()
    if not inference.is_relative_to(attachments) or inference.parent != attachments:
        raise WalkerError("The private image cache is not available")
    try:
        inference.chmod(0o700)
    except OSError as exc:
        raise WalkerError("The private image cache is not available") from exc

    key = sha256(_CACHE_VERSION + str(len(content)).encode() + b"\0" + str(max_edge).encode() + b"\0" + content).hexdigest()
    destination = inference / (key + ".jpg")
    if destination.is_symlink():
        raise WalkerError("The private image cache is not available")
    if destination.is_file():
        return destination

    try:
        with Image.open(BytesIO(content)) as opened:
            if opened.format not in _FORMATS:
                raise WalkerError("Use a PNG, JPEG, or WebP image attachment")
            width, height = opened.size
            if width <= 0 or height <= 0 or width * height > MAX_SOURCE_PIXELS:
                raise WalkerError("Image is too large to process safely (maximum 40 megapixels)")
            opened.load()  # Decode now so corrupt/truncated input fails before inference.
            image = ImageOps.exif_transpose(opened)
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                flattened = Image.new("RGB", rgba.size, "white")
                flattened.paste(rgba, mask=rgba.getchannel("A"))
                image = flattened
            else:
                image = image.convert("RGB")
            image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            fd, temporary = tempfile.mkstemp(prefix=".inference-", suffix=".jpg", dir=inference)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as output:
                    image.save(output, format="JPEG", quality=88, optimize=True)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, destination)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
            image.close()
            if not destination.is_relative_to(chat_root) or destination.is_symlink():
                raise WalkerError("The private image cache is not available")
            return destination
    except WalkerError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise WalkerError("Image is too large to process safely (maximum 40 megapixels)") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise WalkerError("This image is corrupt or cannot be decoded safely") from exc

