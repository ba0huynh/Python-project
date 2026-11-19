# GoXe backend image: the same image runs the web server (default CMD) and the
# dispatcher worker (`python manage.py ride_worker`). See docker-compose.yml.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Static files for /admin (served by WhiteNoise). Settings need a key to import.
RUN SECRET_KEY=collectstatic-only ALLOWED_HOSTS=localhost python manage.py collectstatic --noinput

RUN useradd --create-home --uid 10001 goxe && chown -R goxe /app
USER goxe

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/', timeout=4)"

CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "--proxy-headers", "config.asgi:application"]
