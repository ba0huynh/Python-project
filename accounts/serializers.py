import re

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from django.conf import settings

from core.models import DriverProfile, VehicleType

from .models import Customer

User = get_user_model()


def normalize_phone(value):
    # Vietnamese mobile numbers: 0xxxxxxxxx and +84xxxxxxxxx are equivalent.
    if value.startswith('0'):
        value = '+84' + value[1:]
    if not re.fullmatch(r'\+84[35789]\d{8}', value):
        raise serializers.ValidationError('Số điện thoại di động Việt Nam không hợp lệ.')
    return value


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

    validate_phone = staticmethod(normalize_phone)

    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Mật khẩu xác nhận không khớp.'})
        user = User(username=data['phone'], email=data['email'], first_name=data['full_name'])
        try:
            validate_password(data['password'], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': exc.messages})
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
        user = authenticate(
            request=self.context.get('request'), username=data['phone'], password=data['password']
        )
        if user is None or not Customer.objects.filter(user=user).exists():
            raise serializers.ValidationError('Số điện thoại hoặc mật khẩu không đúng.')
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

    validate_phone = staticmethod(normalize_phone)

    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Mật khẩu xác nhận không khớp.'})
        user = User(username=driver_username(data['phone']), first_name=data['full_name'])
        try:
            validate_password(data['password'], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': exc.messages})
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
        user = authenticate(
            request=self.context.get('request'),
            username=driver_username(data['phone']), password=data['password'],
        )
        if user is None or not DriverProfile.objects.filter(user=user).exists():
            raise serializers.ValidationError('Số điện thoại hoặc mật khẩu không đúng.')
        return {'driver': user.driver_profile}


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
