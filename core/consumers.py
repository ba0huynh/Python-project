"""
WebSocket endpoint: ws(s)://<host>/ws/?token=<JWT access token>

One connection per logged-in user (customer or driver). The server pushes
{"event": ..., "data": {...}}; events are listed in core/services.py, plus
"connected" right after the handshake. Clients should re-fetch their state
(GET /api/rides/current/, /api/driver/offers/) after every (re)connect.

Clients may send:
    {"type": "ping"}                                          -> {"event": "pong"}
    {"type": "driver.location", "lat": .., "lng": .., "heading": ..}  (drivers only)

Close codes: 4401 = missing/invalid/expired token (refresh it and reconnect).
"""
import asyncio
import logging
import time
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from . import services
from .realtime import user_group

logger = logging.getLogger(__name__)

# Drivers' phones may send faster than this; extra fixes are dropped.
MIN_LOCATION_INTERVAL_S = 1.0

_dispatcher_task = None


async def _dispatcher_loop():
    while True:
        try:
            await database_sync_to_async(services.run_dispatch_cycle)()
        except Exception:
            logger.exception('Embedded dispatch cycle failed')
        await asyncio.sleep(2)


def ensure_embedded_dispatcher():
    """
    Single-process mode (no Redis): run the dispatcher on the web server's own
    event loop, because a separate `ride_worker` process couldn't reach these
    WebSocket clients through the in-memory channel layer.
    """
    global _dispatcher_task
    if settings.RIDE_WORKER_EMBEDDED and (_dispatcher_task is None or _dispatcher_task.done()):
        _dispatcher_task = asyncio.get_running_loop().create_task(_dispatcher_loop())


@database_sync_to_async
def user_from_token(token):
    try:
        user_id = AccessToken(token)['user_id']
    except (TokenError, KeyError):
        return None
    return get_user_model().objects.filter(pk=user_id, is_active=True).select_related('driver_profile').first()


@database_sync_to_async
def save_driver_location(user, lat, lng, heading):
    driver = services.get_driver(user)
    if driver:
        services.update_driver_location(driver, lat, lng, heading)
    return driver is not None


def parse_location(content):
    try:
        lat, lng = float(content['lat']), float(content['lng'])
        heading = content.get('heading')
        heading = float(heading) if heading is not None else None
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng, heading


class RideConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        params = parse_qs(self.scope.get('query_string', b'').decode())
        self.user = await user_from_token(params.get('token', [''])[0])
        if self.user is None:
            # Accept first so the client actually receives the 4401 close code.
            await self.accept()
            await self.close(code=4401)
            return
        ensure_embedded_dispatcher()
        self.group = user_group(self.user.id)
        self.last_location_at = 0.0
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_json({'event': 'connected', 'data': {'user_id': self.user.id}})

    async def disconnect(self, code):
        if getattr(self, 'group', None):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if not getattr(self, 'group', None):
            return
        kind = content.get('type') if isinstance(content, dict) else None
        if kind == 'ping':
            await self.send_json({'event': 'pong'})
        elif kind == 'driver.location':
            loc = parse_location(content)
            if loc is None:
                await self.send_json({'event': 'error', 'data': {'detail': 'lat/lng không hợp lệ'}})
                return
            now = time.monotonic()
            if now - self.last_location_at < MIN_LOCATION_INTERVAL_S:
                return
            self.last_location_at = now
            if not await save_driver_location(self.user, *loc):
                await self.send_json({'event': 'error', 'data': {'detail': 'Chỉ tài xế mới gửi vị trí.'}})
        else:
            await self.send_json({'event': 'error', 'data': {'detail': f'Không hỗ trợ type={kind!r}'}})

    async def push(self, message):
        """Handler for group_send(..., {'type': 'push', ...}) from core/realtime.py."""
        await self.send_json({'event': message['event'], 'data': message['data']})
