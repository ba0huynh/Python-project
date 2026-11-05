from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APITestCase

from .models import Customer


class CustomerAuthTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.payload = {
            'phone': '0912345678', 'full_name': 'Nguyen Van An',
            'email': 'an@example.com', 'password': 'RideSecure!2026',
            'password_confirm': 'RideSecure!2026',
        }

    def register(self):
        response = self.client.post('/api/auth/register/', self.payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def authorize(self, data):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + data['access'])

    def test_register_hashes_password_and_returns_safe_profile(self):
        data = self.register()
        customer = Customer.objects.get()
        self.assertEqual(customer.phone, '+84912345678')
        self.assertTrue(customer.user.check_password(self.payload['password']))
        self.assertNotEqual(customer.user.password, self.payload['password'])
        self.assertNotIn('password', data['customer'])
        self.assertFalse(customer.user.is_staff)

    def test_duplicate_normalized_phone_is_rejected_without_extra_user(self):
        self.register()
        self.payload['phone'] = '+84912345678'
        response = self.client.post('/api/auth/register/', self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_invalid_registration_inputs(self):
        for field, value in [('phone', 'abc'), ('email', 'bad'), ('full_name', ' '),
                             ('password_confirm', 'wrong'), ('password', '12345678')]:
            with self.subTest(field=field):
                cache.clear()
                payload = {**self.payload, field: value}
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
        self.payload['phone'] = '0987654321'
        second = self.register()
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
