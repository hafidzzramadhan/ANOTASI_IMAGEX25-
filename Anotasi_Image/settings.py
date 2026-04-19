"""
Django settings for Anotasi_Image project.

Lokasi: Anotasi_Image/Anotasi_Image/settings.py
Aktif via: DJANGO_SETTINGS_MODULE=Anotasi_Image.settings
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# ============================================================================
# PATHS & ENV
# ============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent  # = Anotasi_Image/
load_dotenv(BASE_DIR.parent / '.env')              # baca .env di root project

# ============================================================================
# CORE
# ============================================================================
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-CHANGE-ME-in-production")
DEBUG = os.getenv("DEBUG", "True").lower() == "true"

# ALLOWED_HOSTS — strict by default, override via .env utk add lebih
ALLOWED_HOSTS = [h.strip() for h in os.getenv(
    "ALLOWED_HOSTS",
    "localhost,127.0.0.1"
).split(",") if h.strip()]

# ============================================================================
# APPS
# ============================================================================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',

    # Third-party
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'crispy_forms',
    'crispy_bootstrap4',

    # Local apps (eksplisit AppConfig — biar signal & ready() ke-load)
    'master.apps.MasterConfig',
    'annotator.apps.AnnotatorConfig',
    'reviewer.apps.ReviewerConfig',
]

# ============================================================================
# MIDDLEWARE
# ============================================================================
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# ============================================================================
# URLS / WSGI
# ============================================================================
ROOT_URLCONF = 'Anotasi_Image.urls'
WSGI_APPLICATION = 'Anotasi_Image.wsgi.application'

# ============================================================================
# TEMPLATES
# ============================================================================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ============================================================================
# DATABASE — PostgreSQL (production-ready)
# ============================================================================
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'anotasi_image'),
        'USER': os.getenv('DB_USER', 'anotasi_user'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'CONN_MAX_AGE': 60,  # connection pooling — reuse 60 detik
    }
}

# ============================================================================
# AUTH
# ============================================================================
AUTH_USER_MODEL = 'master.CustomUser'

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',           # admin / username login
    'allauth.account.auth_backends.AuthenticationBackend', # allauth (email/social)
]

LOGIN_URL = 'master:login'
LOGIN_REDIRECT_URL = 'master:home'
LOGOUT_REDIRECT_URL = 'master:login'
ANNOTATOR_LOGIN_URL = 'annotator:signin'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ============================================================================
# DJANGO ALLAUTH (format baru — TIDAK wrap di dict)
# ============================================================================
SITE_ID = 1
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USERNAME_BLACKLIST = ['admin', 'staff', 'superuser']
# Email verification — 'none' utk dev biar gampang, 'mandatory' utk production
ACCOUNT_EMAIL_VERIFICATION = os.getenv(
    "ACCOUNT_EMAIL_VERIFICATION",
    "none" if DEBUG else "mandatory"
)

# ============================================================================
# SOCIAL AUTH (Google)
# ============================================================================
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': os.getenv('GOOGLE_CLIENT_ID', ''),
            'secret': os.getenv('GOOGLE_CLIENT_SECRET', ''),
            'key': '',
        },
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
    }
}
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_REQUIRED = True
SOCIALACCOUNT_ADAPTER = 'master.adapters.CustomSocialAccountAdapter'

# ============================================================================
# CRISPY FORMS
# ============================================================================
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# ============================================================================
# I18N / TIMEZONE
# ============================================================================
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Jakarta'  # ← WIB (sebelumnya UTC, ga relevan utk tim ID)
USE_I18N = True
USE_TZ = True

# ============================================================================
# STATIC & MEDIA
# ============================================================================
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / 'master' / 'static',
    # Tambah folder static lain kalau perlu (jangan masukkin output collectstatic)
]
STATIC_ROOT = BASE_DIR / 'staticfiles_collected'  # output collectstatic (di-gitignore)

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR.parent / 'media'  # = root project / media (sesuai struktur lama)

# ============================================================================
# UPLOAD CONSTRAINTS
# ============================================================================
ALLOWED_UPLOAD_EXTENSIONS = ['.zip', '.rar', '.7zip']
MAX_UPLOAD_SIZE = 52428800  # 50 MB

# ============================================================================
# DEFAULTS
# ============================================================================
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ============================================================================
# EMAIL
# ============================================================================
if DEBUG:
    # Dev: email di-print ke terminal, ga kirim beneran
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    # Production: SMTP Gmail (atau ganti ke SES/Mailgun/dll)
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# ============================================================================
# AI API (annotator integration)
# ============================================================================
AI_API_URL = os.getenv(
    "AI_API_URL",
    "https://pursue-various-engineer-corporate.trycloudflare.com/api/proses-gambar/"
)

# ============================================================================
# SECURITY (production hardening — auto-aktif kalau DEBUG=False)
# ============================================================================
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000  # 1 tahun
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'