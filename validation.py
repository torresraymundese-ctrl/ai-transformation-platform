"""Small, explicit validation helpers for untrusted HTTP input."""

import re
from urllib.parse import urlsplit


class ValidationError(ValueError):
    """Raised when client-supplied data violates a public input contract."""


MOBILE_PATTERN = re.compile(r"^1[3-9]\d{9}$")
IDEMPOTENCY_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalized_mobile(value):
    """Return a canonical mainland mobile number without exposing input in errors."""
    if not isinstance(value, str):
        raise ValidationError("phone must be text")
    normalized = re.sub(r"[\s-]", "", value)
    for prefix in ("+86", "0086"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    if not MOBILE_PATTERN.fullmatch(normalized):
        raise ValidationError("phone has an invalid value")
    return normalized


def validated_email(value):
    if not isinstance(value, str):
        raise ValidationError("email must be text")
    value = value.strip()
    if len(value) > 254:
        raise ValidationError("email is too long")
    if value and not EMAIL_PATTERN.fullmatch(value):
        raise ValidationError("email has an invalid value")
    return value


def validated_wechat(value):
    if not isinstance(value, str):
        raise ValidationError("wechat must be text")
    value = value.strip()
    if len(value) > 64:
        raise ValidationError("wechat is too long")
    return value


def validated_submission_key(value):
    if not isinstance(value, str) or not IDEMPOTENCY_PATTERN.fullmatch(value):
        raise ValidationError("submission_key has an invalid value")
    return value.lower()


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
