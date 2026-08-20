"""Lazy HTML-to-PDF adapter for the optional native WeasyPrint runtime."""


def render_pdf(html: str, base_url: str) -> bytes:
    """Render trusted report HTML without importing WeasyPrint at app startup."""
    from weasyprint import HTML

    return HTML(string=html, base_url=base_url).write_pdf()
