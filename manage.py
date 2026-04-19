#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks.

    PERUBAHAN: DJANGO_SETTINGS_MODULE sekarang pakai dotted path
    'Anotasi_Image.settings' bukan cuma 'settings'.

    Kenapa?
    - Lebih explicit & portable (nggak bergantung sys.path kebetulan)
    - Settings sekarang jadi MODULE (folder dengan __init__.py),
      bukan single file. Django auto pick dari __init__.py.
    - Di production, override via env var:
        DJANGO_SETTINGS_MODULE=Anotasi_Image.settings.production
    """
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Anotasi_Image.settings')

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()