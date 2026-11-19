"""System checks that catch dev-only settings in production (shown by `manage.py check`)."""
from django.conf import settings
from django.core.checks import Warning, register


@register()
def production_settings(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    issues = []
    if settings.SMS_BACKEND == 'accounts.sms.ConsoleBackend':
        issues.append(Warning(
            'SMS_BACKEND is the console backend: OTP codes are only written to the log.',
            hint='Implement accounts.sms.BaseSMSBackend for your SMS provider and set SMS_BACKEND.',
            id='goxe.W001',
        ))
    if 'InMemoryChannelLayer' in settings.CHANNEL_LAYERS['default']['BACKEND']:
        issues.append(Warning(
            'WebSocket events only reach clients of the same process (in-memory channel layer).',
            hint='Set REDIS_URL so web and worker processes share events.',
            id='goxe.W002',
        ))
    if not settings.GEOAPIFY_API_KEY:
        issues.append(Warning(
            'GEOAPIFY_API_KEY is empty: routes are straight lines and place search returns nothing.',
            id='goxe.W003',
        ))
    return issues
