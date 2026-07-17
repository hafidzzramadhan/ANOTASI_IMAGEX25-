from allauth.account.models import EmailAddress


def is_email_verified(user, email=None):
    """Cek status verifikasi email internal aplikasi via django-allauth."""
    if not user or not getattr(user, 'pk', None):
        return False

    email = (email or user.email or '').strip()
    if not email:
        return False

    return EmailAddress.objects.filter(
        user=user,
        email__iexact=email,
        verified=True,
    ).exists()


def ensure_unverified_email_address(user):
    """Pastikan record EmailAddress ada dan belum verified untuk flow aktivasi."""
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={'verified': False, 'primary': True},
    )


def mark_email_verified(user):
    """Tandai email utama user sebagai verified setelah activation token valid."""
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={'verified': True, 'primary': True},
    )
