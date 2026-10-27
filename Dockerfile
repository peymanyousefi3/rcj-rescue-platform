FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.runtime.lock ./
RUN pip install --no-cache-dir -r requirements.runtime.lock
RUN useradd --create-home --uid 10001 arena
COPY --chown=arena:arena . .
RUN mkdir -p /app/var/private /app/staticfiles && chown -R arena:arena /app/var /app/staticfiles
USER arena
RUN DJANGO_DEBUG=1 python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "180", "--access-logfile", "-", "--access-logformat", "%(m)s %(s)s %(b)s %(L)s"]
