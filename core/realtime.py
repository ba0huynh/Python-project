"""
Push events to connected WebSocket clients (see core/consumers.py).

Every connected user joins the group `user_<user id>`. Services call
`notify_user(...)` after a DB change; the message is sent only after the
transaction commits so clients never see uncommitted state.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

logger = logging.getLogger(__name__)


def user_group(user_id) -> str:
    return f'user_{user_id}'


def notify_user(user_id, event: str, data: dict):
    def send():
        layer = get_channel_layer()
        if layer is None:
            return
        try:
            async_to_sync(layer.group_send)(user_group(user_id), {'type': 'push', 'event': event, 'data': data})
        except Exception:  # a realtime hiccup must never break the request that changed the DB
            logger.exception('Failed to push %s to user %s', event, user_id)

    transaction.on_commit(send)
