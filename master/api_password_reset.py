"""
API Endpoint untuk Lupa Password.

2 endpoint:
- POST /api/auth/password/reset/         → kirim email reset link
- POST /api/auth/password/reset/confirm/ → set password baru dengan token

Bekerja buat SEMUA role (master/annotator/reviewer/guest).
Pake Django built-in token generator + SMTP (Brevo/Gmail).
"""
import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings

logger = logging.getLogger(__name__)
User = get_user_model()


def _email_ready():
    return bool(getattr(settings, "EMAIL_CONFIGURED", False))


def _site_url_for_request(request):
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
    """
    Nama file sebenarnya di disk (case-sensitive di Linux/Railway).

    Di macOS, logo3.png dan Logo3.png bisa jadi file yang sama; URL production
    harus pakai casing yang benar-benar ada setelah git clone di Linux.
    """
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
    paths = [
        base / "master" / "static" / "images" / resolved,
    ]
    if static_root:
        paths.append(static_root / "images" / resolved)
    return paths


def _email_logo_url(site_url, filename, *settings_keys):
    """
    URL HTTPS absolut untuk logo di email.

    Gmail & Brevo butuh URL publik (bukan {% static %} / base64 besar).
    Contoh: https://domain-anda/static/images/logo3.png
    """
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


# ============================================================
# SERIALIZERS
# ============================================================

class PasswordResetRequestSerializer(serializers.Serializer):
    """Body buat POST /api/auth/password/reset/"""
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Body buat POST /api/auth/password/reset/confirm/"""
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(min_length=8, write_only=True)
    confirm_password = serializers.CharField(min_length=8, write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({
                'confirm_password': 'Password konfirmasi gak sama.'
            })
        return attrs


# ============================================================
# VIEWS
# ============================================================

class PasswordResetRequestAPIView(APIView):
    """
    POST /api/auth/password/reset/

    Body: { "email": "user@example.com" }

    Behavior:
    - Kirim email berisi reset link kalo email kedaftar
    - Untuk security, response tetap success walaupun email tidak ada (cegah email enumeration)
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip().lower()

        # Cari user — kalo gak ada, tetep return success (security)
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response({
                'detail': 'Kalo email terdaftar, link reset password udah dikirim ke inbox lu.'
            })

        if not _email_ready():
            logger.error(
                "Email belum dikonfigurasi. Set BREVO_API_KEY (disarankan di Railway) "
                "atau EMAIL_HOST_USER + EMAIL_HOST_PASSWORD."
            )
            return Response({
                'detail': (
                    'Layanan email belum dikonfigurasi di server. '
                    'Hubungi admin untuk set BREVO_API_KEY di Railway.'
                ),
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Generate token + uid (pake Django built-in)
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))

        # Build reset URL
        site_url = _site_url_for_request(request)
        reset_url = f"{site_url}/reset-password/{uid}/{token}/"

        # Kirim email
        try:
            html_body = render_to_string('master/emails/password_reset.html', {
                'user': user,
                'reset_url': reset_url,
                'site_name': 'Anotasi Image',
                # Hanya logo1 + logo3 (tanpa logo2)
                'logo1_url': _email_logo_url(
                    site_url, 'logo1.png', 'EMAIL_LOGO1_URL', 'EMAIL_LOGO_URL',
                ),
                'logo3_url': _email_logo_url(
                    site_url, 'logo3.png', 'EMAIL_LOGO3_URL',
                ),
            })
            send_mail(
                subject='Reset Password — Anotasi Image',
                message=(
                    f"Halo {user.first_name or user.username},\n\n"
                    f"Lu request reset password. Klik link berikut buat set password baru:\n\n"
                    f"{reset_url}\n\n"
                    f"Link expire dalam 3 hari.\n\n"
                    f"Kalo lu gak request reset, abaikan email ini.\n\n"
                    f"— Tim Anotasi Image"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_body,
                fail_silently=False,
            )
        except Exception as e:
            logger.exception("Gagal kirim email reset password ke %s", user.email)
            payload = {
                'detail': 'Email gagal dikirim. Cek konfigurasi SMTP atau hubungi admin.',
            }
            if settings.DEBUG:
                payload['debug_error'] = str(e)
                payload['debug_reset_url'] = reset_url
            return Response(payload, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'detail': 'Link reset password udah dikirim. Cek inbox/spam folder.'
        })


class PasswordResetConfirmAPIView(APIView):
    """
    POST /api/auth/password/reset/confirm/

    Body:
    {
        "uid": "MQ",
        "token": "abc-123",
        "new_password": "passwordbaru123",
        "confirm_password": "passwordbaru123"
    }
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uid = serializer.validated_data['uid']
        token = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']

        # Decode uid → user_id → user
        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response({
                'detail': 'Link reset tidak valid atau corrupted.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Verify token (cek expiry + signature)
        if not default_token_generator.check_token(user, token):
            return Response({
                'detail': 'Link reset expired atau udah dipake. Request link baru.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Set password baru
        user.set_password(new_password)
        user.save(update_fields=['password'])

        return Response({
            'detail': 'Password berhasil di-reset. Lu bisa login pake password baru.',
            'email': user.email,
        })