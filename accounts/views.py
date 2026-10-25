from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from core.serializers import DriverProfileSerializer

from .models import Customer
from .serializers import (
    CustomerRefreshSerializer, CustomerSerializer, DriverLoginSerializer, DriverRegisterSerializer,
    LoginSerializer, LogoutSerializer, RegisterSerializer,
)


def auth_response(customer):
    refresh = RefreshToken.for_user(customer.user)
    return {
        'customer': CustomerSerializer(customer).data,
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }


class PublicAuthView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_scope = 'auth'


class RegisterView(PublicAuthView):
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = serializer.save()
        return Response(auth_response(customer), status=status.HTTP_201_CREATED)


class LoginView(PublicAuthView):
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        return Response(auth_response(serializer.validated_data['customer']))


class RefreshView(TokenRefreshView):
    serializer_class = CustomerRefreshSerializer
    throttle_scope = 'auth'


class MeView(generics.RetrieveAPIView):
    serializer_class = CustomerSerializer

    def get_object(self):
        try:
            return self.request.user.customer
        except Customer.DoesNotExist:
            raise PermissionDenied('Tài khoản không phải khách hàng.')


def driver_auth_response(driver):
    refresh = RefreshToken.for_user(driver.user)
    return {
        'driver': DriverProfileSerializer(driver).data,
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }


class DriverRegisterView(PublicAuthView):
    def post(self, request):
        serializer = DriverRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        driver = serializer.save()
        return Response(driver_auth_response(driver), status=status.HTTP_201_CREATED)


class DriverLoginView(PublicAuthView):
    def post(self, request):
        serializer = DriverLoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        return Response(driver_auth_response(serializer.validated_data['driver']))


class DriverMeView(generics.RetrieveAPIView):
    serializer_class = DriverProfileSerializer

    def get_object(self):
        driver = getattr(self.request.user, 'driver_profile', None)
        if driver is None:
            raise PermissionDenied('Tài khoản không phải tài xế.')
        return driver


class LogoutView(APIView):
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token = RefreshToken(serializer.validated_data['refresh'])
            if str(token['user_id']) != str(request.user.pk):
                raise PermissionDenied('Token không thuộc tài khoản hiện tại.')
            token.blacklist()
        except TokenError:
            raise ValidationError({'refresh': 'Token không hợp lệ hoặc đã hết hạn.'})
        return Response(status=status.HTTP_204_NO_CONTENT)
