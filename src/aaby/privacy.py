import base64
import binascii
import io
import re
import warnings

from PIL import Image, UnidentifiedImageError

from aaby.contracts import Screenshot
from aaby.errors import AgentError


def redact(text: str) -> str:
    text = re.sub(r"\b(?:sk-[\w-]{8,}|eyJ[\w-]+\.[\w-]+\.[\w-]+)\b", "[REDACTED]", text)
    text = re.sub(r"(?i)\bBearer\s+[^\s,;\"']+", "Bearer [REDACTED]", text)
    return re.sub(
        r"(?i)\b(password|token|api[_-]?key|secret)\s*[=:]\s*[^\s,;\"']+",
        r"\1=[REDACTED]", text,
    )


def image_url(screenshot: Screenshot) -> str:
    """Validate image size/encoding and re-encode to remove embedded metadata.

    Does not remove secrets visible in image pixels. Only synthetic pages are supported.
    """
    try:
        raw = base64.b64decode(screenshot.base64, validate=True)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                expected = "PNG" if screenshot.mime_type == "image/png" else "JPEG"
                if image.format != expected or image.width * image.height > 12_000_000:
                    raise AgentError("invalid_image")
                image.load()
                output = io.BytesIO()
                image.convert("RGB").save(output, format="PNG")
        return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    except (ValueError, binascii.Error, OSError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise AgentError("invalid_image") from error
