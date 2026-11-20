import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import Customer, PhoneOTP


def request_otp(client, phone, purpose='register', role='customer'):
    """Ask for a code and return it (captured from the SMS), or None if no SMS was sent."""
    with mock.patch('accounts.otp.send_sms') as send:
        response = client.post('/api/auth/otp/request/', {'phone': phone, 'purpose': purpose, 'role': role},
                               format='json')
    if not send.called:
        return response, None
    return response, re.search(r'\b(\d{6})\b', send.call_args.args[1]).group(1)


@override_settings(OTP_FIXED_CODE='')
class CustomerAuthTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.payload = {
            'phone': '0912345678', 'full_name': 'Nguyen Van An',
            'email': 'an@example.com', 'password': 'RideSecure!2026',
            'password_confirm': 'RideSecure!2026',
        }

    def register(self, **overrides):
        payload = {**self.payload, **overrides}
        _, code = request_otp(self.client, payload['phone'])
        cache.clear()  # don't let OTP/register requests hit the auth rate limit
        response = self.client.post('/api/auth/register/', {**payload, 'otp': code}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def authorize(self, data):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + data['access'])

    def reset(self, otp, phone='0912345678', password='NewPassword!2026'):
        return self.client.post('/api/auth/reset-password/', {
            'phone': phone, 'role': 'customer', 'otp': otp,
            'new_password': password, 'new_password_confirm': password,
        }, format='json')

    def test_register_hashes_password_and_returns_safe_profile(self):
        data = self.register()
        customer = Customer.objects.get()
        self.assertEqual(customer.phone, '+84912345678')
        self.assertTrue(customer.user.check_password(self.payload['password']))
        self.assertNotIn('password', data['customer'])
        self.assertFalse(customer.user.is_staff)

    def test_register_requires_valid_otp(self):
        response = self.client.post('/api/auth/register/', {**self.payload, 'otp': '000000'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('otp', response.data)
        response = self.client.post('/api/auth/register/', self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Customer.objects.exists())

    def test_otp_is_single_use_and_bound_to_phone(self):
        _, code = request_otp(self.client, '0912345678')
        cache.clear()
        other = self.client.post('/api/auth/register/', {**self.payload, 'phone': '0987654321', 'otp': code},
                                 format='json')
        self.assertEqual(other.status_code, 400)
        self.register_with = self.client.post('/api/auth/register/', {**self.payload, 'otp': code}, format='json')
        self.assertEqual(self.register_with.status_code, 201)
        again = self.client.post('/api/auth/register/', {**self.payload, 'phone': '0912345678', 'otp': code},
                                 format='json')
        self.assertEqual(again.status_code, 400)

    def test_otp_resend_cooldown_and_attempt_limit(self):
        first, code = request_otp(self.client, '0912345678')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data['resend_in'], 60)
        second, _ = request_otp(self.client, '0912345678')
        self.assertEqual(second.status_code, 429)
        self.assertIn('retry_after', second.data)
        for _ in range(5):
            cache.clear()
            self.client.post('/api/auth/register/', {**self.payload, 'otp': '000000'}, format='json')
        cache.clear()
        response = self.client.post('/api/auth/register/', {**self.payload, 'otp': code}, format='json')
        self.assertEqual(response.status_code, 400, 'the code must be burned after 5 wrong tries')

    def test_otp_is_stored_hashed(self):
        _, code = request_otp(self.client, '0912345678')
        self.assertNotIn(code, PhoneOTP.objects.get().code_hash)

    def test_otp_for_already_registered_phone_is_refused(self):
        self.register()
        response, code = request_otp(self.client, '0912345678')
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(code)

    def test_duplicate_normalized_phone_is_rejected_without_extra_user(self):
        self.register()
        response = self.client.post('/api/auth/register/', {**self.payload, 'phone': '+84912345678', 'otp': '1'},
                                    format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_invalid_registration_inputs(self):
        for field, value in [('phone', 'abc'), ('email', 'bad'), ('full_name', ' '),
                             ('password_confirm', 'wrong'), ('password', '12345678')]:
            with self.subTest(field=field):
                cache.clear()
                payload = {**self.payload, field: value, 'otp': '123456'}
                if field == 'password':
                    payload['password_confirm'] = value
                response = self.client.post('/api/auth/register/', payload, format='json')
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Customer.objects.exists())

    def test_login_accepts_both_phone_formats(self):
        self.register()
        for phone in ['0912345678', '+84912345678']:
            response = self.client.post('/api/auth/login/', {
                'phone': phone, 'password': self.payload['password'],
            }, format='json')
            self.assertEqual(response.status_code, 200, response.data)
            self.assertIn('access', response.data)

    def test_wrong_password_unknown_phone_and_disabled_user_are_rejected(self):
        self.register()
        for phone, password in [('0912345678', 'incorrect'), ('0987654321', 'incorrect')]:
            response = self.client.post('/api/auth/login/', {
                'phone': phone, 'password': password,
            }, format='json')
            self.assertEqual(response.status_code, 400)
        get_user_model().objects.update(is_active=False)
        response = self.client.post('/api/auth/login/', {
            'phone': self.payload['phone'], 'password': self.payload['password'],
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_me_requires_auth_and_returns_only_current_customer(self):
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 401)
        data = self.register()
        self.authorize(data)
        response = self.client.get('/api/auth/me/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], data['customer']['id'])

    def test_invalid_access_token(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer invalid')
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 401)

    def test_refresh_rotates_and_rejects_reuse(self):
        data = self.register()
        response = self.client.post('/api/auth/refresh/', {'refresh': data['refresh']}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(self.client.post('/api/auth/refresh/', {
            'refresh': data['refresh'],
        }, format='json').status_code, 401)

    def test_disabled_account_cannot_refresh(self):
        data = self.register()
        get_user_model().objects.update(is_active=False)
        response = self.client.post('/api/auth/refresh/', {'refresh': data['refresh']}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_logout_revokes_refresh(self):
        data = self.register()
        self.authorize(data)
        response = self.client.post('/api/auth/logout/', {'refresh': data['refresh']}, format='json')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.post('/api/auth/refresh/', {
            'refresh': data['refresh'],
        }, format='json').status_code, 401)

    def test_cannot_logout_another_customer(self):
        first = self.register()
        second = self.register(phone='0987654321')
        self.authorize(first)
        response = self.client.post('/api/auth/logout/', {'refresh': second['refresh']}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_login_is_rate_limited(self):
        for _ in range(10):
            response = self.client.post('/api/auth/login/', {
                'phone': '0912345678', 'password': 'wrong',
            }, format='json')
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post('/api/auth/login/', {
            'phone': '0912345678', 'password': 'wrong',
        }, format='json').status_code, 429)

    def test_reset_password_with_otp_and_old_sessions_are_revoked(self):
        old = self.register()
        response, code = request_otp(self.client, '0912345678', purpose='reset_password')
        self.assertEqual(response.status_code, 200)
        cache.clear()
        res = self.reset(code)
        self.assertEqual(res.status_code, 200, res.data)
        cache.clear()
        login = self.client.post('/api/auth/login/', {'phone': '0912345678', 'password': 'NewPassword!2026'},
                                 format='json')
        self.assertEqual(login.status_code, 200, login.data)
        refresh = self.client.post('/api/auth/refresh/', {'refresh': old['refresh']}, format='json')
        self.assertEqual(refresh.status_code, 401, 'sessions from before the reset must be signed out')

    def test_reset_password_rejects_wrong_or_default_otp(self):
        self.register()
        request_otp(self.client, '0912345678', purpose='reset_password')
        for otp in ('1234', '999999'):
            cache.clear()
            res = self.reset(otp)
            self.assertEqual(res.status_code, 400)
            self.assertIn('otp', res.data)

    def test_reset_for_unknown_phone_looks_the_same_but_sends_nothing(self):
        response, code = request_otp(self.client, '0988888888', purpose='reset_password')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(code)
        cache.clear()
        res = self.reset('123456', phone='0988888888')
        self.assertEqual(res.status_code, 400)
        self.assertIn('otp', res.data)


@override_settings(DRIVER_AUTO_APPROVE=False, OTP_FIXED_CODE='')
class DriverAuthTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_driver_register_needs_otp_and_waits_for_approval(self):
        _, code = request_otp(self.client, '0901234567', role='driver')
        cache.clear()
        payload = {
            'phone': '0901234567', 'full_name': 'Tran Van Binh', 'password': 'RideSecure!2026',
            'password_confirm': 'RideSecure!2026', 'license_number': 'b1-123', 'vehicle_plate': '59x2-123.45',
            'vehicle_type': 'bike', 'otp': code,
        }
        response = self.client.post('/api/auth/driver/register/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data['driver']['is_approved'])
        self.assertEqual(response.data['driver']['license_number'], 'B1-123')

    def test_customer_code_cannot_register_a_driver(self):
        _, code = request_otp(self.client, '0901234567', role='customer')
        cache.clear()
        response = self.client.post('/api/auth/driver/register/', {
            'phone': '0901234567', 'full_name': 'Tran Van Binh', 'password': 'RideSecure!2026',
            'password_confirm': 'RideSecure!2026', 'license_number': 'B1-123', 'vehicle_plate': '59X2',
            'vehicle_type': 'bike', 'otp': code,
        }, format='json')
        self.assertEqual(response.status_code, 400)


class AdminRegistrationAndApprovalTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='admin', is_staff=True, is_superuser=True)
        self.driver_user = get_user_model().objects.create_user(username='driver:+84901234567')
        from core.models import DriverProfile
        self.driver = DriverProfile.objects.create(
            user=self.driver_user,
            phone='+84901234567',
            full_name='Nguyen Van Driver',
            license_number='LIC-12345',
            vehicle_plate='59A-12345',
            vehicle_type='bike',
            is_approved=False,
            status='OFFLINE',
        )

    def test_admin_classes_registered(self):
        from django.contrib.admin.sites import site
        from core.models import DriverProfile
        self.assertIn(Customer, site._registry)
        self.assertIn(DriverProfile, site._registry)

    def test_approve_selected_drivers_action_success(self):
        from .admin import DriverProfileAdmin
        from core.models import DriverProfile
        from django.contrib.admin.sites import site
        from unittest.mock import MagicMock

        admin_instance = DriverProfileAdmin(DriverProfile, site)
        admin_instance.message_user = MagicMock()
        request = MagicMock()
        queryset = DriverProfile.objects.filter(pk=self.driver.pk)

        admin_instance.approve_selected_drivers(request, queryset)

        self.driver.refresh_from_db()
        self.assertTrue(self.driver.is_approved)
        self.assertEqual(self.driver.status, 'OFFLINE')
        admin_instance.message_user.assert_called_once()
        args, kwargs = admin_instance.message_user.call_args
        self.assertIn("Thành công: Đã phê duyệt 1 tài xế", args[1])

    def test_approve_selected_drivers_action_warning_when_none_pending(self):
        from .admin import DriverProfileAdmin
        from core.models import DriverProfile
        from django.contrib.admin.sites import site
        from unittest.mock import MagicMock

        self.driver.is_approved = True
        self.driver.save()

        admin_instance = DriverProfileAdmin(DriverProfile, site)
        admin_instance.message_user = MagicMock()
        request = MagicMock()
        queryset = DriverProfile.objects.filter(pk=self.driver.pk)

        admin_instance.approve_selected_drivers(request, queryset)

        admin_instance.message_user.assert_called_once()
        args, kwargs = admin_instance.message_user.call_args
        self.assertIn("Không có tài xế nào được duyệt", args[1])


class FixedOtpTests(APITestCase):
    @override_settings(OTP_FIXED_CODE='123456')
    def test_fixed_code_works_and_can_be_resent_immediately(self):
        cache.clear()
        for _ in range(2):
            response, code = request_otp(self.client, '0912345678')
            self.assertEqual((response.status_code, code), (200, '123456'))
