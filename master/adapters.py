import re

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialAccount
from django.contrib import messages
from django.shortcuts import redirect, resolve_url

from .auth_utils import ensure_unverified_email_address, is_email_verified
from .email_utils import send_activation_email
from .models import CustomUser


GOOGLE_PROVIDER = 'google'


class CustomAccountAdapter(DefaultAccountAdapter):
    """
    Satu pintu redirect setelah login normal maupun Google.
    `master:home` butuh role/akses master, jadi lobby adalah halaman aman
    untuk user baru, guest, annotator, reviewer, dan master.
    """

    def get_login_redirect_url(self, request):
        return resolve_url('master:lobby')

    def get_signup_redirect_url(self, request):
        return resolve_url('master:lobby')


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Google OAuth dipisah tegas:
    - process=login: hanya autentikasi akun yang sudah ada, aktif, verified,
      dan memang terhubung/tervalidasi via Google.
    - process=signup: buat atau kirim ulang verifikasi email, lalu redirect
      ke login. Tidak ada auto-login sebelum activation link dipakai.
    """

    def pre_social_login(self, request, sociallogin):
        if sociallogin.account.provider != GOOGLE_PROVIDER:
            return

        process = sociallogin.state.get('process', 'login')
        email = self._get_google_email(sociallogin)

        if process == 'signup':
            self._handle_google_signup(request, sociallogin, email)
            return

        self._handle_google_login(request, sociallogin, email)

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)

        if not getattr(user, 'username', None):
            user.username = self._unique_username(data.get('email', '') or 'user')

        return user

    def save_user(self, request, sociallogin, form=None):
        """
        Auto-signup via allauth tidak boleh membuat user baru di belakang layar.
        Semua pembuatan user Google ditangani eksplisit di _handle_google_signup.
        """
        raise ImmediateHttpResponse(self._blocked_response(
            request,
            'Akun tidak ditemukan. Silakan daftar terlebih dahulu.',
            'master:login',
        ))

    def is_auto_signup_allowed(self, request, sociallogin):
        return False

    def can_authenticate_by_email(self, login, email):
        return login.account.provider == GOOGLE_PROVIDER

    def _handle_google_login(self, request, sociallogin, email):
        if not email:
            raise ImmediateHttpResponse(self._blocked_response(
                request,
                'Akun tidak ditemukan. Silakan daftar terlebih dahulu.',
                'master:login',
            ))

        account = self._existing_google_account_for_login(sociallogin, email)
        if account is None:
            raise ImmediateHttpResponse(self._blocked_response(
                request,
                'Akun tidak ditemukan. Silakan daftar terlebih dahulu.',
                'master:login',
            ))

        user = account.user
        if user.email.lower() != email.lower():
            raise ImmediateHttpResponse(self._blocked_response(
                request,
                'Email Google tidak sesuai dengan akun aplikasi.',
                'master:login',
            ))

        if not user.is_active:
            raise ImmediateHttpResponse(self._blocked_response(
                request,
                'Akun Anda sedang nonaktif. Hubungi admin.',
                'master:login',
            ))

        if not is_email_verified(user, email):
            ensure_unverified_email_address(user)
            send_activation_email(request, user)
            raise ImmediateHttpResponse(self._blocked_response(
                request,
                'Email belum diverifikasi. Link verifikasi baru sudah dikirim ke email Anda.',
                'master:login',
                level='success',
            ))

        sociallogin.user = user
        sociallogin.account = account

    def _handle_google_signup(self, request, sociallogin, email):
        if not email:
            raise ImmediateHttpResponse(self._blocked_response(
                request,
                'Google tidak mengirim email. Gunakan akun Google dengan email valid.',
                'master:signup',
            ))

        user = CustomUser.objects.filter(email__iexact=email).first()
        if user:
            self._sync_google_profile(user, sociallogin)

            if is_email_verified(user, email):
                if not user.is_active:
                    raise ImmediateHttpResponse(self._blocked_response(
                        request,
                        'Akun Anda sedang nonaktif. Hubungi admin.',
                        'master:login',
                    ))

                account = self._ensure_google_social_account(request, user, sociallogin)
                sociallogin.user = user
                sociallogin.account = account
                return

            user.is_active = False
            user.save(update_fields=['first_name', 'last_name', 'is_active'])
            ensure_unverified_email_address(user)
            self._ensure_google_social_account(request, user, sociallogin)
            send_activation_email(request, user)
            raise ImmediateHttpResponse(self._blocked_response(
                request,
                'Email verifikasi sudah dikirim ulang. Silakan cek inbox Anda.',
                'master:login',
                level='success',
            ))

        user = CustomUser.objects.create(
            username=self._unique_username(email),
            email=email,
            first_name=sociallogin.account.extra_data.get('given_name', '') or '',
            last_name=sociallogin.account.extra_data.get('family_name', '') or '',
            role='guest',
            is_active=False,
        )
        user.set_unusable_password()
        user.save(update_fields=['password'])
        ensure_unverified_email_address(user)
        self._ensure_google_social_account(request, user, sociallogin)
        send_activation_email(request, user)
        raise ImmediateHttpResponse(self._blocked_response(
            request,
            'Akun berhasil dibuat. Cek email Anda untuk verifikasi sebelum login.',
            'master:login',
            level='success',
        ))

    def _existing_google_account_for_login(self, sociallogin, email):
        if sociallogin.account.pk and sociallogin.account.provider == GOOGLE_PROVIDER:
            return sociallogin.account

        try:
            return SocialAccount.objects.select_related('user').get(
                provider=GOOGLE_PROVIDER,
                uid=sociallogin.account.uid,
            )
        except SocialAccount.DoesNotExist:
            return None

    def _ensure_google_social_account(self, request, user, sociallogin):
        existing = SocialAccount.objects.filter(
            provider=GOOGLE_PROVIDER,
            uid=sociallogin.account.uid,
        ).select_related('user').first()

        if existing and existing.user_id != user.id:
            raise ImmediateHttpResponse(self._blocked_response(
                request,
                'Akun Google ini sudah terhubung ke user lain.',
                'master:login',
            ))

        account, _ = SocialAccount.objects.update_or_create(
            provider=GOOGLE_PROVIDER,
            uid=sociallogin.account.uid,
            defaults={
                'user': user,
                'extra_data': sociallogin.account.extra_data,
            },
        )
        return account

    def _sync_google_profile(self, user, sociallogin):
        data = sociallogin.account.extra_data
        user.first_name = data.get('given_name', '') or user.first_name
        user.last_name = data.get('family_name', '') or user.last_name

    def _get_google_email(self, sociallogin):
        for email_address in sociallogin.email_addresses:
            if email_address.email:
                return email_address.email.strip().lower()
        return (sociallogin.account.extra_data.get('email') or '').strip().lower()

    def _unique_username(self, email):
        base = re.sub(r'[^a-zA-Z0-9_]', '', email.split('@')[0]) or 'user'
        username = base
        suffix = 1
        while CustomUser.objects.filter(username=username).exists():
            suffix += 1
            username = f"{base}{suffix}"
        return username

    def _blocked_response(self, request, message, redirect_name, level='error'):
        getattr(messages, level)(request, message)
        return redirect(redirect_name)
