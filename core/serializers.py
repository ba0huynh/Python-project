from rest_framework import serializers
from django.contrib.auth.models import User
from .models import DriverProfile, Ride


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']


class DriverProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = DriverProfile
        fields = '__all__'


class RideSerializer(serializers.ModelSerializer):
    customer = UserSerializer(read_only=True)
    driver = DriverProfileSerializer(read_only=True)

    class Meta:
        model = Ride
        fields = '__all__'