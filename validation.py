"""Small, explicit validation helpers for untrusted HTTP input."""

from urllib.parse import urlsplit


class ValidationError(ValueError):
    """Raised when client-supplied data violates a public input contract."""


def text(data, name, *, maximum, required=False, default=""):
    value = data.get(name, default)
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be text")
    value = value.strip()
    if required and not value:
        raise ValidationError(f"{name} is required")
    if len(value) > maximum:
        raise ValidationError(f"{name} is too long")
    return value


def choice(data, name, allowed, *, default=None):
    value = data.get(name, default)
    if value not in allowed:
        raise ValidationError(f"{name} has an invalid value")
    return value


def integer(data, name, *, minimum, maximum, default=None):
    raw = data.get(name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be an integer") from None
    if value < minimum or value > maximum:
        raise ValidationError(f"{name} is outside the allowed range")
    return value


def external_url(data, name, *, required=False):
    value = text(data, name, maximum=2048, required=required)
    if not value:
        return ""
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValidationError(f"{name} must be an absolute HTTP(S) URL")
    return value


def safe_external_url(value):
    """Return a display-safe external URL, including for legacy database rows."""
    try:
        return external_url({"url": value or ""}, "url")
    except ValidationError:
        return ""
