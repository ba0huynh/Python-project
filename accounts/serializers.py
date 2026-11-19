import re

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from django.conf import settings

from core.models import DriverProfile, VehicleType

from . import otp as otp_service
from .models import Customer

User = get_user_model()


def normalize_phone(value):
    # Vietnamese mobile numbers: 0xxxxxxxxx and +84xxxxxxxxx are equivalent.
    if value.startswith('0'):
        value = '+84' + value[1:]
    if not re.fullmatch(r'\+84[35789]\d{8}', value):
        raise serializers.ValidationError('Số điện thoại di động Việt Nam không hợp lệ.')
    return value


OTP_ERROR = 'Mã OTP không đúng hoặc đã hết hạn.'


def check_otp(phone, purpose, role, code):
    if not otp_service.verify(phone, purpose, role, code):
        raise serializers.ValidationError({'otp': OTP_ERROR})


def is_registered(phone, role):
    if role == 'driver':
        return DriverProfile.objects.filter(phone=phone).exists()
    return Customer.objects.filter(phone=phone).exists()


class OTPRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    purpose = serializers.ChoiceField(choices=['register', 'reset_password'])
    role = serializers.ChoiceField(choices=['customer', 'driver'], default='customer')

    validate_phone = staticmethod(normalize_phone)

    def validate(self, data):
        if data['purpose'] == 'register' and is_registered(data['phone'], data['role']):
            raise serializers.ValidationError({'phone': 'Số điện thoại đã được đăng ký.'})
        return data


class CustomerSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)

    class Meta:
        model = Customer
        fields = ('id', 'phone', 'full_name', 'email', 'created_at')


class RegisterSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    full_name = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True, default='')
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    otp = serializers.CharField(max_length=10, write_only=True)

    validate_phone = staticmethod(normalize_phone)

    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Mật khẩu xác nhận không khớp.'})
        user = User(username=data['phone'], email=data['email'], first_name=data['full_name'])
        try:
            validate_password(data['password'], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': exc.messages})
        if is_registered(data['phone'], 'customer'):
            raise serializers.ValidationError({'phone': 'Số điện thoại đã được đăng ký.'})
        check_otp(data['phone'], 'register', 'customer', data['otp'])  # last: it consumes the code
        return data

    def create(self, data):
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=data['phone'], password=data['password'], email=data['email']
                )
                return Customer.objects.create(
                    user=user, phone=data['phone'], full_name=data['full_name']
                )
        except IntegrityError:
            raise serializers.ValidationError({'phone': 'Số điện thoại đã được đăng ký.'})


class LoginSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    validate_phone = staticmethod(normalize_phone)

    def validate(self, data):
        if not Customer.objects.filter(user__username=data['phone']).exists():
            raise serializers.ValidationError(
                'Số điện thoại này chưa có tài khoản khách hàng. Vui lòng đăng ký.'
            )
        user = authenticate(
            request=self.context.get('request'), username=data['phone'], password=data['password']
        )
        if user is None:
            raise serializers.ValidationError('Mật khẩu không đúng. Vui lòng thử lại.')
        return {'customer': user.customer}


class CustomerRefreshSerializer(TokenRefreshSerializer):
    """Refresh for customers and drivers (both log in with JWT)."""

    def validate(self, attrs):
        token = RefreshToken(attrs['refresh'])
        user_id = token['user_id']
        active = (
            Customer.objects.filter(user_id=user_id, user__is_active=True).exists()
            or DriverProfile.objects.filter(user_id=user_id, user__is_active=True).exists()
        )
        if not active:
            raise serializers.ValidationError('Tài khoản không còn hoạt động.')
        return super().validate(attrs)


# --- Drivers -----------------------------------------------------------------
# A driver is a separate Django user with username "driver:<phone>", so the same
# phone number can have both a customer account and a driver account.

def driver_username(phone):
    return f'driver:{phone}'


class DriverRegisterSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    full_name = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    license_number = serializers.CharField(max_length=50)
    vehicle_plate = serializers.CharField(max_length=20)
    vehicle_type = serializers.ChoiceField(choices=VehicleType.choices, default=VehicleType.BIKE)
    vehicle_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    otp = serializers.CharField(max_length=10, write_only=True)

    validate_phone = staticmethod(normalize_phone)

    def validate_license_number(self, value):
        value = value.strip().upper()
        if DriverProfile.objects.filter(license_number=value).exists():
            raise serializers.ValidationError('Số bằng lái đã được đăng ký.')
        return value

    def validate_vehicle_plate(self, value):
        return value.strip().upper()

    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Mật khẩu xác nhận không khớp.'})
        user = User(username=driver_username(data['phone']), first_name=data['full_name'])
        try:
            validate_password(data['password'], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': exc.messages})
        if is_registered(data['phone'], 'driver'):
            raise serializers.ValidationError({'phone': 'Số điện thoại đã được đăng ký.'})
        check_otp(data['phone'], 'register', 'driver', data['otp'])  # last: it consumes the code
        return data

    def create(self, data):
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=driver_username(data['phone']), password=data['password'],
                    first_name=data['full_name'],
                )
                return DriverProfile.objects.create(
                    user=user,
                    phone=data['phone'],
                    full_name=data['full_name'],
                    license_number=data['license_number'],
                    vehicle_plate=data['vehicle_plate'],
                    vehicle_type=data['vehicle_type'],
                    vehicle_name=data['vehicle_name'],
                    is_approved=settings.DRIVER_AUTO_APPROVE,
                )
        except IntegrityError:
            raise serializers.ValidationError('Số điện thoại hoặc số bằng lái đã được đăng ký.')


class DriverLoginSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    validate_phone = staticmethod(normalize_phone)

    def validate(self, data):
        username = driver_username(data['phone'])
        if not DriverProfile.objects.filter(user__username=username).exists():
            raise serializers.ValidationError(
                'Số điện thoại này chưa có tài khoản tài xế. Vui lòng đăng ký.'
            )
        user = authenticate(
            request=self.context.get('request'), username=username, password=data['password'],
        )
        if user is None:
            raise serializers.ValidationError('Mật khẩu không đúng. Vui lòng thử lại.')
        return {'driver': user.driver_profile}


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class ResetPasswordSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    role = serializers.ChoiceField(choices=['customer', 'driver'], default='customer')
    otp = serializers.CharField(max_length=10)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    new_password_confirm = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    validate_phone = staticmethod(normalize_phone)

    def validate(self, data):
        if data['new_password'] != data['new_password_confirm']:
            raise serializers.ValidationError({'new_password_confirm': 'Mật khẩu xác nhận không khớp.'})
        username = driver_username(data['phone']) if data['role'] == 'driver' else data['phone']
        user = User.objects.filter(username=username, is_active=True).first()
        try:
            validate_password(data['new_password'], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'new_password': exc.messages})
        # No code is ever sent to an unknown phone, so this also covers "not registered"
        # without telling an attacker which numbers have accounts.
        check_otp(data['phone'], 'reset_password', data['role'], data['otp'])
        if user is None:
            raise serializers.ValidationError({'otp': OTP_ERROR})
        data['user'] = user
        return data

    def save(self):
        user = self.validated_data['user']
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password'])
        # Sign out every device that used the old password.
        for token in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=token)
        return user
