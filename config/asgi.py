"""
ASGI entrypoint: HTTP (Django) + WebSocket (Channels).

`python manage.py runserver` uses this automatically because `daphne` is in
INSTALLED_APPS. Production-style: `daphne -b 0.0.0.0 -p 8000 config.asgi:application`.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django_asgi_app = get_asgi_application()  # must run before importing consumers

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.urls import path  # noqa: E402

from core.consumers import RideConsumer  # noqa: E402

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    # No origin check: the mobile app is not a browser. Auth is the JWT in ?token=.
    'websocket': URLRouter([path('ws/', RideConsumer.as_asgi())]),
})
