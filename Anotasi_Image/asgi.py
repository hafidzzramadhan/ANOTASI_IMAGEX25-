"""
ASGI config for Anotasi_Image project.

Lokasi: Anotasi_Image/Anotasi_Image/asgi.py

Expose ASGI callable as module-level variable `application`.
Dipakai kalau lu nanti pake async server (Daphne, Uvicorn) —
misal utk WebSocket (Django Channels) atau Server-Sent Events.

Untuk sekarang ga kepake, tapi bagusnya tetep ada biar ready.

Dokumentasi: https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Anotasi_Image.settings')

application = get_asgi_application()