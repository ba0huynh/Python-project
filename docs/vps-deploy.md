# GoXe Backend — Dokploy (`Dockerfile`) Deployment Notes

Notes from running the backend locally against `.env` and configuring `Dockerfile` for standalone Dokploy deployment.

---

## 1. Local Verification Results (Current `.env`)

- **Shell `DEBUG` override**: The Windows shell had `DEBUG=release` set, and `load_dotenv()` in `config/settings.py` does not override existing OS environment variables, so `settings.DEBUG` evaluated to `False` despite `DEBUG=True` in `.env`.
- **Database & Migrations (`db.sqlite3`)**:
  - `manage.py migrate --check` initially exited `1` (5 unapplied `core` migrations).
  - `manage.py migrate --noinput` applied `core.0006_alter_driverprofile_current_latitude_and_more` through `core.0010_alter_driverprofile_current_heading_and_more` (`OK`).
  - `manage.py seed --force` completed (`Total Customers: 16`, `Total Drivers: 18`, `Total Rides: 42`, superuser `admin1`).
- **System Checks**:
  - `manage.py check`: 2 warnings — `goxe.W001` (`SMS_BACKEND` is `ConsoleBackend`) and `goxe.W002` (`REDIS_URL` unset, using in-memory channel layer).
  - `manage.py check --deploy`: 4 warnings — `goxe.W001`, `goxe.W002`, `security.W009` (`SECRET_KEY` uses `django-insecure-` prefix), and `security.W021` (`SECURE_HSTS_PRELOAD` not `True`).
- **Daphne ASGI Server (`config.asgi:application`)**:
  - **With `DEBUG=False` (`DEBUG=release` in shell)**:
    - `GET /api/health/` returned `200 {"status":"ok"}` (`SECURE_REDIRECT_EXEMPT` exempts `/api/health/`).
    - `GET /admin/login/` and `GET /api/auth/login/` failed with a TLS handshake timeout (`_ssl.c:993`) because `SECURE_SSL_REDIRECT` defaulted to `True` and redirected plain HTTP on port `8000` to `https://`.
    - Logged `UserWarning: No directory at: .../be/staticfiles/` locally (inside Docker, `collectstatic --noinput` builds `staticfiles/` during `docker build`).
  - **With `DEBUG=True` (matching `.env`)**:
    - `manage.py ride_worker --once` exited `0`.
    - `GET /api/health/` returned `200`.
    - `GET /admin/login/` returned `200`.
    - `POST /api/auth/login/` (`0912345678`) succeeded and `POST /api/rides/estimate/` returned live Geoapify routes and fares (`bike`: 28000, `car4`: 57000, `car7`: 69000).

---

## 2. Issues & Pitfalls When Deploying `Dockerfile` to Dokploy

1. **SQLite Persistence Across Redeploys (`USE_SQLITE=True`)**
   - `config/settings.py` reads `SQLITE_PATH` (defaulting locally to `db.sqlite3`), and `Dockerfile` sets `ENV SQLITE_PATH=/data/db.sqlite3` with `VOLUME ["/data"]` owned by the container user (`goxe`, UID `10001`).
   - In Dokploy (**Application -> Advanced -> Mounts**), add a **Volume Mount** to `/data` (e.g., Volume Name: `goxe-sqlite`, Mount Path: `/data`) so `db.sqlite3` survives Dokploy rebuilds/redeploys.
   - If you use a **Bind Mount** instead of a Volume Mount, set host folder ownership to UID `10001` (`chown -R 10001:10001 /path/on/vps`), otherwise SQLite will fail with a read-only database error.
   - Keep **Replicas = 1** when using SQLite or without Redis.

2. **If Switching to PostgreSQL (`USE_SQLITE=False`)**
   - Do **not** use `localhost` in `DATABASE_URL` or `DB_HOST` inside Dokploy — `localhost` points to the backend container itself. Use the internal database hostname from Dokploy's PostgreSQL service instead.

3. **`SECRET_KEY` Warning (`security.W009`)**
   - Replace the `django-insecure-...` dev key before production:
     ```bash
     python -c "import secrets; print(secrets.token_urlsafe(50))"
     ```

4. **Dokploy Traefik HTTPS, `SECURE_SSL_REDIRECT`, and `CSRF_TRUSTED_ORIGINS`**
   - When `DEBUG=False`, `config/settings.py` sets `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` and `SECURE_SSL_REDIRECT = True`.
   - With Dokploy HTTPS enabled on your domain (Traefik terminates TLS and forwards `X-Forwarded-Proto: https` to port `8000`):
     - Keep `SECURE_SSL_REDIRECT=True` (default).
     - Set `CSRF_TRUSTED_ORIGINS=https://your-domain.com` (required for `/admin` login).
     - Set `NUM_PROXIES=1` (so DRF rate limiting uses the real client IP behind Traefik).
   - If testing temporarily over plain `http://` (before TLS certificate is active), set `SECURE_SSL_REDIRECT=False`.

5. **`ALLOWED_HOSTS`**
   - Set `ALLOWED_HOSTS=your-domain.com` (avoid `*` in production).
   - `Dockerfile`'s `HEALTHCHECK` automatically reads `ALLOWED_HOSTS` and sends its first non-wildcard host in the `Host` header to `http://127.0.0.1:8000/api/health/`, so Docker/Dokploy healthchecks pass even when `127.0.0.1` is not in `ALLOWED_HOSTS`.

6. **Single-Container Mode (No Redis / Console SMS)**
   - With no `REDIS_URL` set, `RIDE_WORKER_EMBEDDED` defaults to `True` (the ride dispatcher runs inside Daphne via `core/consumers.py`), and `InMemoryChannelLayer` + `LocMemCache` handle WebSockets and throttling inside the single container (`goxe.W002`).
   - `SMS_BACKEND` defaults to `accounts.sms.ConsoleBackend` (`goxe.W001`): OTP codes are written to Dokploy container logs until a real SMS provider is plugged in.

7. **Commit & Push Local Changes Before Deploying**
   - Commit and push your local changes (`.env.example`, `Dockerfile`, `config/settings.py`, `docs/vps-deploy.md`) to your Git branch so Dokploy builds the updated `Dockerfile`.

---

## 3. Dokploy Setup Checklist (`Dockerfile` Build Type)

1. **Application -> General -> Build Type**: `Dockerfile` (Docker File: `Dockerfile`, Build Context: `.`, Port: `8000`).
2. **Application -> Domains**: Add your domain pointing to container port `8000` with HTTPS enabled.
3. **Application -> Advanced -> Mounts** (only needed if `USE_SQLITE=True`):
   - **Type**: `Volume Mount`
   - **Volume Name**: `goxe-sqlite`
   - **Mount Path**: `/data`
4. **Application -> Environment (School Project / Allow-All Config)**:

   ```dotenv
   DEBUG=False
   SECRET_KEY="django-insecure-3#_8c-92kt*32hu)=@^*6gh7#(-&rz6(#vi7rkxo=$pd9=+pue"
   ALLOWED_HOSTS=*
   CORS_ALLOWED_ORIGINS=*
   NUM_PROXIES=1

   # Option 1: Persistent SQLite on /data volume (1 replica)
   USE_SQLITE=True

   # Option 2: External / Dokploy PostgreSQL instead of SQLite
   # USE_SQLITE=False
   # DATABASE_URL=postgresql://postgres:<password>@<dokploy-postgres-host>:5432/django_db

   GEOAPIFY_API_KEY=<your-geoapify-key>
   SMS_BACKEND=accounts.sms.ConsoleBackend
   ```

   > **Notes on `*` settings**:
   > - `ALLOWED_HOSTS=*` allows all hosts.
   > - `CORS_ALLOWED_ORIGINS=*` (or `CORS_ALLOW_ALL_ORIGINS=True`) allows all browser origins even when `DEBUG=False` (`config/settings.py` handles `*` safely without triggering `corsheaders.E014`).
   > - Leave `CSRF_TRUSTED_ORIGINS` unset (do not set `CSRF_TRUSTED_ORIGINS=*` — Django requires full `https://domain` values, and same-origin `/admin` login over HTTPS works automatically behind Dokploy Traefik via `X-Forwarded-Proto: https`).
   > - If you access the app over plain `http://` without HTTPS/TLS in Dokploy, also add `SECURE_SSL_REDIRECT=False`.

5. **On every Dokploy deploy/restart**, `Dockerfile` `CMD` automatically runs:
   1. `python manage.py migrate --noinput`
   2. `python manage.py seed --force` (idempotent: creates demo accounts/`admin1` if missing, skips duplicate demo rides if rides already exist)
   3. `exec daphne -b 0.0.0.0 -p 8000 --proxy-headers config.asgi:application`
