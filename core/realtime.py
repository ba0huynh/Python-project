"""
Push events to connected WebSocket clients (see core/consumers.py).

Every connected user joins the group `user_<user id>`. Views call
`notify_user(...)` after a DB change; the message is sent only after the
transaction commits so clients never see uncommitted state.
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction


def user_group(user_id) -> str:
    return f'user_{user_id}'


def notify_user(user_id, event: str, data: dict):
    def send():
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            user_group(user_id), {'type': 'push', 'event': event, 'data': data}
        )

    transaction.on_commit(send)


def notify_ride_parties(ride, event: str, data: dict):
    """Send an event to the ride's customer and (if assigned) driver."""
    notify_user(ride.customer_id, event, data)
    if ride.driver_id:
        notify_user(ride.driver.user_id, event, data)
