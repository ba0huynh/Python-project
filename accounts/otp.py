"""
Phone OTP: issue a 6-digit code by SMS and verify it once.

Rules (settings): OTP_TTL_SECONDS valid time, OTP_RESEND_SECONDS between two
codes for the same phone/purpose/role, OTP_MAX_PER_HOUR codes per phone, and
OTP_MAX_ATTEMPTS wrong guesses before the code is burned.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import PhoneOTP
from .sms import send_sms


class OTPCooldown(Exception):
    def __init__(self, retry_after: int):
        super().__init__(retry_after)
        self.retry_after = retry_after


def _hash(phone, purpose, role, code):
    msg = f'{phone}|{purpose}|{role}|{code}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()


def issue(phone, purpose, role, send=True) -> PhoneOTP:
    """Create a new code and SMS it. Raises OTPCooldown when asked too often."""
    now = timezone.now()
    fixed = settings.OTP_FIXED_CODE  # dev only, see settings.py
    recent = PhoneOTP.objects.filter(phone=phone, created_at__gte=now - timedelta(hours=1))
    if not fixed and recent.count() >= settings.OTP_MAX_PER_HOUR:
        oldest = recent.order_by('created_at').first()
        raise OTPCooldown(int((oldest.created_at + timedelta(hours=1) - now).total_seconds()) + 1)
    last = recent.filter(purpose=purpose, role=role).order_by('-created_at').first()
    if not fixed and last and (now - last.created_at).total_seconds() < settings.OTP_RESEND_SECONDS:
        raise OTPCooldown(int(settings.OTP_RESEND_SECONDS - (now - last.created_at).total_seconds()) + 1)

    code = fixed or f'{secrets.randbelow(1_000_000):06d}'
    with transaction.atomic():
        # Only the newest code is valid.
        PhoneOTP.objects.filter(phone=phone, purpose=purpose, role=role, consumed_at__isnull=True).update(
            consumed_at=now
        )
        otp = PhoneOTP.objects.create(
            phone=phone, purpose=purpose, role=role, code_hash=_hash(phone, purpose, role, code),
            expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
        )
    if send:
        minutes = settings.OTP_TTL_SECONDS // 60
        send_sms(phone, f'GoXe: ma xac thuc cua ban la {code}. Hieu luc {minutes} phut. Khong chia se ma nay.')
    return otp


def verify(phone, purpose, role, code) -> bool:
    """Check and consume the latest code. Wrong guesses count toward the limit."""
    code = (code or '').strip()
    with transaction.atomic():
        otp = (
            PhoneOTP.objects.select_for_update()
            .filter(phone=phone, purpose=purpose, role=role, consumed_at__isnull=True,
                    expires_at__gt=timezone.now())
            .order_by('-created_at')
            .first()
        )
        if otp is None or otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            return False
        if not hmac.compare_digest(otp.code_hash, _hash(phone, purpose, role, code)):
            otp.attempts += 1
            otp.save(update_fields=['attempts', 'updated_at'])
            return False
        otp.consumed_at = timezone.now()
        otp.save(update_fields=['consumed_at', 'updated_at'])
        return True
