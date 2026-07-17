"""
Helper bersama untuk pengiriman email (reset password, aktivasi akun, dll).

Dipake oleh master/views.py dan master/api_password_reset.py biar konsisten
(site url, logo url) dan gak duplikat logic.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .tokens import account_activation_token

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


def send_activation_email(request, user):
    """Kirim email aktivasi akun dengan template master/emails/activation_email.html."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = account_activation_token.make_token(user)
    activation_path = reverse('master:activate', kwargs={'uidb64': uid, 'token': token})
    site_url = site_url_for_request(request)
    activation_url = f"{site_url}{activation_path}"

    html_body = render_to_string('master/emails/activation_email.html', {
        'user': user,
        'activation_url': activation_url,
        'site_name': 'Anotasi Image',
        'logo1_url': email_logo_url(site_url, 'logo1.png', 'EMAIL_LOGO1_URL', 'EMAIL_LOGO_URL'),
        'logo3_url': email_logo_url(site_url, 'logo3.png', 'EMAIL_LOGO3_URL'),
    })

    send_mail(
        subject='Verifikasi Email — Anotasi Image',
        message=(
            f"Halo {user.first_name or user.username},\n\n"
            f"Terima kasih sudah mendaftar di Anotasi Image. "
            f"Klik link berikut untuk verifikasi email dan mengaktifkan akun Anda:\n\n"
            f"{activation_url}\n\n"
            f"Jika Anda tidak merasa mendaftar, abaikan email ini.\n\n"
            f"— Tim Anotasi Image"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        html_message=html_body,
        fail_silently=False,
    )
