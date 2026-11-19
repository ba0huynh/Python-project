"""
Django settings for GoXe. Everything that differs between machines comes from
environment variables (or be/.env, see .env.example).

Production: DEBUG=False (the default) requires SECRET_KEY, ALLOWED_HOSTS and
REDIS_URL. Run `python manage.py check --deploy` before going live.
"""
import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ('true', '1', 'yes', 'on')


def env_list(name, default=''):
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


DEBUG = env_bool('DEBUG', False)

SECRET_KEY = os.getenv('SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('SECRET_KEY must be set when DEBUG is off.')
    SECRET_KEY = 'django-insecure-dev-only-key-do-not-use-in-production'

# In DEBUG any host is fine so phones on the LAN can reach the dev server.
ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', '*' if DEBUG else '')
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured('ALLOWED_HOSTS must be set when DEBUG is off.')
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')


INSTALLED_APPS = [
    'daphne',  # must be first: runserver then serves HTTP + WebSocket (ASGI)
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Local Apps
    'core',
    'accounts',
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'channels',
    'corsheaders',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'


# Database: PostgreSQL (DATABASE_URL or DB_* vars). USE_SQLITE=True for quick local work.
if env_bool('USE_SQLITE'):
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
elif os.getenv('DATABASE_URL'):
    DATABASES = {
        'default': dj_database_url.parse(
            os.environ['DATABASE_URL'], conn_max_age=60, conn_health_checks=True,
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.postgresql'),
            'NAME': os.getenv('DB_NAME', 'django_db'),
            'USER': os.getenv('DB_USER', 'postgres'),
            'PASSWORD': os.getenv('DB_PASSWORD', 'postgres'),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
            'CONN_MAX_AGE': 60,
            'CONN_HEALTH_CHECKS': True,
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Times are stored in UTC; "today" for earnings is Vietnam time.
LANGUAGE_CODE = 'vi'
TIME_ZONE = 'Asia/Ho_Chi_Minh'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage' if DEBUG
        else 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}


# Redis: shared cache (throttling, geocoding) and WebSocket layer across processes.
REDIS_URL = os.getenv('REDIS_URL', '')
if REDIS_URL:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': REDIS_URL}}
    CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels_redis.core.RedisChannelLayer', 'CONFIG': {'hosts': [REDIS_URL]}}
    }
else:
    # Single process only (local development). core/checks.py warns about this in production.
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
    CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


# API clients authenticate with Authorization: Bearer <access token>.
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework_simplejwt.authentication.JWTAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'user': os.getenv('THROTTLE_USER', '300/min'),
        'auth': os.getenv('THROTTLE_AUTH', '10/min'),
        'otp': os.getenv('THROTTLE_OTP', '5/min'),
        'estimate': '30/min',
        'booking': '10/min',
        'geo': '60/min',
        'location': '120/min',
    },
    'DEFAULT_PARSER_CLASSES': ['rest_framework.parsers.JSONParser'],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'NUM_PROXIES': int(os.getenv('NUM_PROXIES', '0')) or None,
}
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=int(os.getenv('JWT_ACCESS_MINUTES', '15'))),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=int(os.getenv('JWT_REFRESH_DAYS', '30'))),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
}

# CORS: the native app sends no Origin; only browsers (the web build) need this.
CORS_ALLOWED_ORIGINS = env_list('CORS_ALLOWED_ORIGINS')
CORS_ALLOW_ALL_ORIGINS = DEBUG and not CORS_ALLOWED_ORIGINS
CORS_ALLOW_CREDENTIALS = False  # JWT in headers, no cookies


# HTTPS hardening (production sits behind a TLS-terminating proxy).
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', True)
    SECURE_REDIRECT_EXEMPT = [r'^api/health/$']
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', True)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'


# Phone OTP (sign-up, password reset). SMS_BACKEND: see accounts/sms.py.
SMS_BACKEND = os.getenv('SMS_BACKEND', 'accounts.sms.ConsoleBackend')
OTP_TTL_SECONDS = 300
OTP_RESEND_SECONDS = 60
OTP_MAX_PER_HOUR = 5
OTP_MAX_ATTEMPTS = 5


# Rides. Prices are not here: edit FareRule in /admin.
GEOAPIFY_API_KEY = os.getenv('GEOAPIFY_API_KEY', '')
GEOAPIFY_TIMEOUT = float(os.getenv('GEOAPIFY_TIMEOUT', '8'))
GEO_COUNTRY_CODE = os.getenv('GEO_COUNTRY_CODE', 'vn')
# Drivers within this distance of the pickup are offered the ride.
DRIVER_SEARCH_RADIUS_KM = float(os.getenv('DRIVER_SEARCH_RADIUS_KM', '5'))
# Drivers whose last GPS fix is older than this are not matched (app closed / no signal).
DRIVER_LOCATION_MAX_AGE_SECONDS = int(os.getenv('DRIVER_LOCATION_MAX_AGE_SECONDS', '120'))
# How long a driver has to accept an offer, and how many drivers get it at once.
DRIVER_OFFER_SECONDS = int(os.getenv('DRIVER_OFFER_SECONDS', '15'))
DISPATCH_BATCH_SIZE = int(os.getenv('DISPATCH_BATCH_SIZE', '3'))
# A booking nobody accepts within this time is cancelled ("no driver found").
RIDE_SEARCH_SECONDS = int(os.getenv('RIDE_SEARCH_SECONDS', '180'))
# Driver must be this close to the pickup to mark "arrived" (0 = no check).
DRIVER_ARRIVAL_RADIUS_M = int(os.getenv('DRIVER_ARRIVAL_RADIUS_M', '300'))
MIN_TRIP_METERS = int(os.getenv('MIN_TRIP_METERS', '200'))
MAX_TRIP_KM = float(os.getenv('MAX_TRIP_KM', '150'))
# Run the dispatcher inside the web process (single-process setups without Redis).
# With Redis, run `python manage.py ride_worker` as its own process instead.
RIDE_WORKER_EMBEDDED = env_bool('RIDE_WORKER_EMBEDDED', not REDIS_URL)
# New drivers must be approved in /admin before going online, unless this is on.
DRIVER_AUTO_APPROVE = env_bool('DRIVER_AUTO_APPROVE', False)


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'plain': {'format': '%(asctime)s %(levelname)s %(name)s: %(message)s'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'plain'}},
    'root': {'handlers': ['console'], 'level': os.getenv('LOG_LEVEL', 'INFO')},
    'loggers': {'django.db.backends': {'level': 'WARNING'}},
}
