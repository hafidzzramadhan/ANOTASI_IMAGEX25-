"""
WSGI config for Anotasi_Image project.

Lokasi: Anotasi_Image/Anotasi_Image/wsgi.py

Expose WSGI callable as module-level variable `application`.
Dipakai sama production server (gunicorn, uwsgi) buat serve Django.

Dokumentasi: https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Anotasi_Image.settings')

application = get_wsgi_application()