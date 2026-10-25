from rest_framework import serializers

from .models import DriverProfile, Ride, Route, VehicleType


class PointSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lng = serializers.FloatField(min_value=-180, max_value=180)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class RouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Route
        fields = ['id', 'mode', 'distance_m', 'duration_s', 'geometry', 'provider']


class DriverPublicSerializer(serializers.ModelSerializer):
    """What a customer sees about their driver."""
    lat = serializers.FloatField(source='current_latitude')
    lng = serializers.FloatField(source='current_longitude')

    class Meta:
        model = DriverProfile
        fields = ['id', 'full_name', 'phone', 'vehicle_type', 'vehicle_name', 'vehicle_plate', 'rating', 'lat', 'lng']


class DriverProfileSerializer(serializers.ModelSerializer):
    """A driver's own profile."""
    lat = serializers.FloatField(source='current_latitude', read_only=True)
    lng = serializers.FloatField(source='current_longitude', read_only=True)

    class Meta:
        model = DriverProfile
        fields = [
            'id', 'phone', 'full_name', 'license_number', 'vehicle_type', 'vehicle_name', 'vehicle_plate',
            'is_approved', 'status', 'rating', 'lat', 'lng', 'location_updated_at', 'created_at',
        ]
        read_only_fields = fields


class RideSerializer(serializers.ModelSerializer):
    pickup = serializers.SerializerMethodField()
    dropoff = serializers.SerializerMethodField()
    customer = serializers.SerializerMethodField()
    driver = DriverPublicSerializer(read_only=True)
    route = RouteSerializer(read_only=True)
    approach_route = RouteSerializer(read_only=True)

    class Meta:
        model = Ride
        fields = [
            'id', 'status', 'vehicle_type', 'pickup', 'dropoff', 'distance_m', 'duration_s', 'fare',
            'payment_method', 'customer', 'driver', 'route', 'approach_route',
            'created_at', 'accepted_at', 'arrived_at', 'started_at', 'completed_at', 'cancelled_at',
            'cancelled_by', 'cancel_reason', 'rating', 'rating_comment',
        ]

    def get_pickup(self, ride):
        return {'address': ride.pickup_address, 'lat': ride.pickup_lat, 'lng': ride.pickup_lng}

    def get_dropoff(self, ride):
        return {'address': ride.dropoff_address, 'lat': ride.dropoff_lat, 'lng': ride.dropoff_lng}

    def get_customer(self, ride):
        profile = getattr(ride.customer, 'customer', None)
        return {
            'id': str(profile.id) if profile else None,
            'full_name': profile.full_name if profile else ride.customer.get_full_name(),
            'phone': profile.phone if profile else '',
        }


# --- Request bodies --------------------------------------------------------------

class EstimateRequestSerializer(serializers.Serializer):
    pickup = PointSerializer()
    dropoff = PointSerializer()


class EstimateOptionSerializer(serializers.Serializer):
    vehicle_type = serializers.CharField()
    name = serializers.CharField()
    seats = serializers.IntegerField()
    fare = serializers.IntegerField()
    route = RouteSerializer()


class CreateRideSerializer(EstimateRequestSerializer):
    vehicle_type = serializers.ChoiceField(choices=VehicleType.choices)


class DriverStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['ONLINE', 'OFFLINE'])
    lat = serializers.FloatField(min_value=-90, max_value=90, required=False)
    lng = serializers.FloatField(min_value=-180, max_value=180, required=False)


class LocationSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lng = serializers.FloatField(min_value=-180, max_value=180)


class RideStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['ARRIVED', 'IN_PROGRESS', 'COMPLETED'])


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class RateSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
