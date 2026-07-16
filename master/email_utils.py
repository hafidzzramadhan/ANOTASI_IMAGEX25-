"""
Helper bersama untuk pengiriman email (reset password, aktivasi akun, dll).

Dipake oleh master/views.py dan master/api_password_reset.py biar konsisten
(site url, logo url) dan gak duplikat logic.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def email_ready():
    return bool(getattr(settings, "EMAIL_CONFIGURED", False))


def site_url_for_request(request):
    """Pakai SITE_URL dari env; kalau masih localhost di production, ambil dari request."""
    configured = getattr(settings, "SITE_URL", "").rstrip("/")
    local_defaults = {
        "",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    }
    if configured and (configured not in local_defaults or settings.DEBUG):
        return configured
    if request is not None:
        return request.build_absolute_uri("/").rstrip("/")
    return configured or "http://localhost:8000"


def _resolve_static_image_filename(filename):
    """Nama file sebenarnya di disk (case-sensitive di Linux/Railway)."""
    images_dir = settings.BASE_DIR / "master" / "static" / "images"
    if images_dir.is_dir():
        target = filename.lower()
        for path in images_dir.iterdir():
            if path.is_file() and path.name.lower() == target:
                return path.name
    static_root = getattr(settings, "STATIC_ROOT", None)
    if static_root:
        collected = static_root / "images"
        if collected.is_dir():
            target = filename.lower()
            for path in collected.iterdir():
                if path.is_file() and path.name.lower() == target:
                    return path.name
    return filename


def _logo_file_candidates(filename):
    """Lokasi file logo (sumber dev + hasil collectstatic di Railway)."""
    resolved = _resolve_static_image_filename(filename)
    base = settings.BASE_DIR
    static_root = getattr(settings, "STATIC_ROOT", None)
    paths = [base / "master" / "static" / "images" / resolved]
    if static_root:
        paths.append(static_root / "images" / resolved)
    return paths


def email_logo_url(site_url, filename, *settings_keys):
    """URL HTTPS absolut untuk logo di email (Gmail & Brevo butuh URL publik)."""
    for key in settings_keys:
        custom = getattr(settings, key, "") or ""
        if custom:
            return custom.strip()

    resolved = _resolve_static_image_filename(filename)
    static_url = getattr(settings, "STATIC_URL", "/static/").rstrip("/")
    url = f"{site_url}{static_url}/images/{resolved}"

    if not any(p.is_file() for p in _logo_file_candidates(filename)):
        logger.warning("File logo tidak ada di server: %s → URL: %s", filename, url)

    return url