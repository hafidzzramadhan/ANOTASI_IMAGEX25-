release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
web: gunicorn Anotasi_Image.wsgi --log-file -
