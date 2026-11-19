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
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import os, urllib.request; hosts = [h.strip() for h in os.getenv('ALLOWED_HOSTS', '').split(',') if h.strip() and h.strip() != '*']; host = ('health' + hosts[0] if hosts[0].startswith('.') else hosts[0]) if hosts else ''; req = urllib.request.Request('http://127.0.0.1:8000/api/health/', headers={'Host': host} if host else {}); urllib.request.urlopen(req, timeout=4)"

CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py seed --force && exec daphne -b 0.0.0.0 -p 8000 --proxy-headers config.asgi:application"]
