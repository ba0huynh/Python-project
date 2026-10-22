# Django Project

A clean, modern Django 6.1 project configured with Python 3.12 and virtual environment support.

## Customer authentication for the ride-hailing app

Implemented phone/password customer registration and login, JWT refresh rotation,
logout, and authenticated profile retrieval with PostgreSQL migrations and tests.

See [API documentation and setup (Vietnamese)](docs/customer-auth.md).
API base path: `/api/auth/`. The root `/` has no application page.

---

## Quick Start

### 1. Activate the Virtual Environment

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\Activate.ps1
```

*(If script execution is disabled in PowerShell, you can run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`, or run directly with `.venv\Scripts\python.exe`)*

**Windows (Command Prompt):**
```cmd
.venv\Scripts\activate.bat
```

---

### 2. Run the Development Server

```powershell
python manage.py runserver
```
or without activating the environment:
```powershell
.\.venv\Scripts\python.exe manage.py runserver
```

Then open your browser at **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**.

---

### 3. Create a Superuser (Admin Access)

To log in to the Django admin panel ([http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)):

```powershell
python manage.py createsuperuser
```

---

### 4. Create a New App

To create an app (for example, `blog` or `accounts`):

```powershell
python manage.py startapp myapp
```

Then register `'myapp',` in `INSTALLED_APPS` inside [config/settings.py](file:///c:/Users/huynh/OneDrive/Documents/github/Python%20project/config/settings.py).

---

### 5. Managing Dependencies

All installed packages are recorded in [requirements.txt](file:///c:/Users/huynh/OneDrive/Documents/github/Python%20project/requirements.txt).
To install additional packages:
```powershell
pip install <package-name>
pip freeze > requirements.txt
```
