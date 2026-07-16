import re

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.account.models import EmailAddress
from .models import CustomUser


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):

    def pre_social_login(self, request, sociallogin):
        """
        Kalau email dari Google sudah terdaftar sebagai user biasa (dibuat
        manual / lewat signup form), sambungkan ke akun itu alih-alih
        membuat user baru -> mencegah IntegrityError di field email (unique).
        """
        if sociallogin.is_existing:
            return

        email = (sociallogin.account.extra_data.get('email') or '').strip()
        if not email:
            return

        try:
            existing_user = CustomUser.objects.get(email__iexact=email)
        except CustomUser.DoesNotExist:
            return

        sociallogin.connect(request, existing_user)

    def populate_user(self, request, sociallogin, data):
        """
        ACCOUNT_USER_MODEL_USERNAME_FIELD = None -> allauth TIDAK mengisi
        username otomatis, padahal CustomUser.username wajib & unique.
        Generate username unik manual di sini.
        """
        user = super().populate_user(request, sociallogin, data)

        if not getattr(user, 'username', None):
            email = data.get('email', '') or ''
            base = re.sub(r'[^a-zA-Z0-9_]', '', email.split('@')[0]) or 'user'
            username = base
            suffix = 1
            while CustomUser.objects.filter(username=username).exists():
                suffix += 1
                username = f"{base}{suffix}"
            user.username = username

        return user

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)

        data = sociallogin.account.extra_data
        user.email = data.get('email', '') or user.email
        user.first_name = data.get('given_name', '') or user.first_name
        user.last_name = data.get('family_name', '') or user.last_name
        if not user.role:
            user.role = 'guest'
        user.is_active = True
        user.save()

        if user.email:
            EmailAddress.objects.update_or_create(
                user=user,
                email=user.email,
                defaults={'verified': True, 'primary': True},
            )

        return user