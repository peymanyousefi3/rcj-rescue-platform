FROM python:3.15-alpine@sha256:20a82dbc2783112ddb91d1534603f802d222a3e63e593cd002eb2ac534e70211
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.runtime.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.runtime.lock
RUN adduser -D -u 10001 arena
COPY --chown=arena:arena . .
RUN mkdir -p /app/var/private /app/staticfiles && chown -R arena:arena /app/var /app/staticfiles
USER arena
RUN DJANGO_DEBUG=1 python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "180", "--access-logfile", "-", "--access-logformat", "%(m)s %(s)s %(b)s %(L)s"]
