"""
SMS sending, pluggable like Django email backends.

settings.SMS_BACKEND is a dotted path to a class with `send(phone, message)`.
The default ConsoleBackend only logs the message (development). For production
subclass BaseSMSBackend for your provider (eSMS, SpeedSMS, Twilio, ...) and set
SMS_BACKEND to it; `manage.py check --deploy` warns while the console backend is used.
"""
import logging

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class SMSError(Exception):
    pass


class BaseSMSBackend:
    def send(self, phone: str, message: str) -> None:
        raise NotImplementedError


class ConsoleBackend(BaseSMSBackend):
    def send(self, phone, message):
        logger.warning('[SMS to %s] %s', phone, message)


def get_backend() -> BaseSMSBackend:
    return import_string(settings.SMS_BACKEND)()


def send_sms(phone: str, message: str) -> None:
    get_backend().send(phone, message)
