"""
WebSocket endpoint: ws://<host>:8000/ws/?token=<JWT access token>

One connection per logged-in user (customer or driver). The server pushes:
    {"event": "ride.requested" | "ride.unavailable" | "ride.updated" | "driver.location", "data": {...}}

Clients may send:
    {"type": "ping"}                                -> {"event": "pong"}
    {"type": "driver.location", "lat": .., "lng": ..}  (drivers only; forwarded to the customer)

Close codes: 4401 = missing/invalid token.
"""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from . import services
from .realtime import user_group


@database_sync_to_async
def user_from_token(token):
    try:
        user_id = AccessToken(token)['user_id']
    except (TokenError, KeyError):
        return None
    return get_user_model().objects.filter(pk=user_id, is_active=True).select_related('driver_profile').first()


@database_sync_to_async
def save_driver_location(user, lat, lng):
    driver = services.get_driver(user)
    if driver:
        services.update_driver_location(driver, lat, lng)
    return driver is not None


class RideConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        params = parse_qs(self.scope.get('query_string', b'').decode())
        self.user = await user_from_token(params.get('token', [''])[0])
        if self.user is None:
            await self.close(code=4401)
            return
        self.group = user_group(self.user.id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_json({'event': 'connected', 'data': {'user_id': self.user.id}})

    async def disconnect(self, code):
        if getattr(self, 'group', None):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        kind = content.get('type')
        if kind == 'ping':
            await self.send_json({'event': 'pong'})
        elif kind == 'driver.location':
            try:
                lat, lng = float(content['lat']), float(content['lng'])
            except (KeyError, TypeError, ValueError):
                await self.send_json({'event': 'error', 'data': {'detail': 'lat/lng không hợp lệ'}})
                return
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                await self.send_json({'event': 'error', 'data': {'detail': 'lat/lng không hợp lệ'}})
                return
            if not await save_driver_location(self.user, lat, lng):
                await self.send_json({'event': 'error', 'data': {'detail': 'Chỉ tài xế mới gửi vị trí.'}})
        else:
            await self.send_json({'event': 'error', 'data': {'detail': f'Không hỗ trợ type={kind!r}'}})

    async def push(self, message):
        """Handler for group_send(..., {'type': 'push', ...}) from core/realtime.py."""
        await self.send_json({'event': message['event'], 'data': message['data']})
