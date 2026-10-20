# AGENTS.md

> **Repository Context & Agent Guidance**  
> This file provides architecture details, conventions, environment configurations, and workflow instructions for AI agents and developers working on this codebase.

---

## 1. Project Overview

This is a Python **Django 6.1** backend application running on **Python 3.12**. It is configured for **PostgreSQL** as the primary relational database with full **Django ORM** integration, automated migrations, seed data management, and containerized database support via Docker Compose.

The project currently has a solid foundational base (`core` app) with starter entities, ready to be expanded once business domain specifications are defined.

---

## 2. Technology Stack

| Layer | Technology | Details |
|---|---|---|
| **Language** | Python 3.12 | Managed via virtual environment (`.venv`) |
| **Framework** | Django 6.1.2 | Full-featured backend framework |
| **ORM** | Django ORM | Built-in object-relational mapping |
| **Database Driver** | `psycopg` 3.3.6 (Binary) | Native async/sync modern PostgreSQL driver for Python |
| **Database Config** | `dj-database-url` & `python-dotenv` | 12-Factor App environment configuration |
| **Primary Database** | PostgreSQL 16 | Defaults to `localhost:5432` (`django_db`) |
| **Offline Fallback** | SQLite3 | Enabled when `USE_SQLITE=True` in `.env` |
| **Containers** | Docker & Docker Compose | Pre-configured `docker-compose.yml` for PostgreSQL |

---

## 3. Directory Layout

```text
├── .env                  # Local environment variables (ignored by Git)
├── .env.example          # Environment variables template
├── .gitignore            # Git ignore rules for Python, Django, venv, and DB
├── docker-compose.yml    # Standalone PostgreSQL 16 container definition
├── requirements.txt      # Pinned Python package dependencies
├── manage.py             # Django command-line runner
├── AGENTS.md             # This document
├── README.md             # User-facing onboarding documentation
├── config/               # Project-level configuration
│   ├── __init__.py
│   ├── asgi.py           # ASGI entrypoint
│   ├── settings.py       # Django settings (DB, apps, middleware)
│   ├── urls.py           # Root URL routing
│   └── wsgi.py           # WSGI entrypoint
└── core/                 # Foundation / Core app
    ├── admin.py          # Admin model registrations
    ├── apps.py           # App configuration
    ├── models.py         # BaseModel and domain entities (SampleEntity)
    ├── views.py          # View handlers
    ├── tests.py          # Unit tests
    ├── migrations/       # Database migrations
    │   └── 0001_initial.py
    └── management/
        └── commands/
            └── seed.py   # Data seeding command (`python manage.py seed`)
```

---

## 4. Database Setup & Configuration

Database settings are dynamically evaluated in [`config/settings.py`](file:///c:/Users/huynh/OneDrive/Documents/github/Python%20project/config/settings.py).

### Environment Variables ([`.env`](file:///c:/Users/huynh/OneDrive/Documents/github/Python%20project/.env))

```dotenv
DEBUG=True
SECRET_KEY=django-insecure-3#_8c-92kt*32hu)=@^*6gh7#(-&rz6(#vi7rkxo=$pd9=+pue
ALLOWED_HOSTS=*

# Option A: Connection string (recommended)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/django_db

# Option B: Discrete parameters
DB_ENGINE=django.db.backends.postgresql
DB_NAME=django_db
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost
DB_PORT=5432

# Toggle SQLite for offline testing or CI without Postgres
USE_SQLITE=False
```

### Running PostgreSQL locally

1. **Via Docker Compose**:
   ```bash
   docker compose up -d
   ```
2. **Via Local PostgreSQL Service**:
   Ensure PostgreSQL is running on port `5432` and database `django_db` exists:
   ```sql
   CREATE DATABASE django_db;
   ```

---

## 5. Entities & ORM Architecture

All models are defined using Django ORM.

### Base Model ([`core/models.py`](file:///c:/Users/huynh/OneDrive/Documents/github/Python%20project/core/models.py))

```python
class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']
```
*Every entity in new apps should inherit from `BaseModel` to maintain standard UUID keys and audit timestamps.*

### Starter Entity ([`SampleEntity`](file:///c:/Users/huynh/OneDrive/Documents/github/Python%20project/core/models.py))
- Demonstrates typed fields (`CharField`, `TextField`, `BooleanField`, `JSONField`).
- Status state choices (`draft`, `active`, `archived`).
- Registered in [`core/admin.py`](file:///c:/Users/huynh/OneDrive/Documents/github/Python%20project/core/admin.py) with search and filters.

---

## 6. Migrations & Seeding Workflows

### Generating & Applying Migrations

When altering or creating models:
```powershell
# 1. Create migration files
.\.venv\Scripts\python.exe manage.py makemigrations

# 2. Apply migrations to the database
.\.venv\Scripts\python.exe manage.py migrate
```

### Database Seeding

A custom management command is implemented in [`core/management/commands/seed.py`](file:///c:/Users/huynh/OneDrive/Documents/github/Python%20project/core/management/commands/seed.py):

```powershell
# Seed initial demo entities
.\.venv\Scripts\python.exe manage.py seed

# Clear existing records and re-seed fresh records
.\.venv\Scripts\python.exe manage.py seed --clear
```

---

## 7. Developer & Agent Commands Cheatsheet

Always use the project's virtual environment (`.venv`):

- **Activate Virtual Environment (PowerShell)**:
  ```powershell
  .\.venv\Scripts\Activate.ps1
  ```
- **Run Development Server**:
  ```powershell
  python manage.py runserver
  ```
- **Create Admin User**:
  ```powershell
  python manage.py createsuperuser
  ```
- **Run System Checks**:
  ```powershell
  python manage.py check
  ```
- **Install New Python Package**:
  ```powershell
  pip install <package-name>
  pip freeze | Out-File -FilePath requirements.txt -Encoding utf8
  ```

---

## 8. Instructions for Future Agents

1. **When User Reveals Project Type**:
   - Create dedicated apps using `python manage.py startapp <app_name>`.
   - Register the new app in `INSTALLED_APPS` inside [`config/settings.py`](file:///c:/Users/huynh/OneDrive/Documents/github/Python%20project/config/settings.py).
   - Inherit models from `core.models.BaseModel`.
   - Add seed routines to `core/management/commands/seed.py` or create app-specific seeders.
   - Run `makemigrations` and `migrate`.
2. **Environment & Secrets**:
   - Never commit sensitive production credentials to `.env`. Keep templates in `.env.example`.
3. **Database Rules**:
   - Maintain PostgreSQL compatibility (avoid SQLite-exclusive SQL syntax).
