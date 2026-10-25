from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import DriverProfile, Ride
from .serializers import DriverProfileSerializer, RideSerializer


class UpdateDriverStatusView(APIView):
    def patch(self, request, driver_id):
        try:
            driver = DriverProfile.objects.get(id=driver_id)
        except DriverProfile.DoesNotExist:
            return Response({"error": "Không tìm thấy tài xế"}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = DriverProfileSerializer(driver, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Cập nhật thành công", "data": serializer.data})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AvailableRidesView(APIView):
    def get(self, request):
        pending_rides = Ride.objects.filter(status='PENDING')
        serializer = RideSerializer(pending_rides, many=True)
        return Response({"total": pending_rides.count(), "rides": serializer.data}, status=status.HTTP_200_OK)


class AcceptRideView(APIView):
    def post(self, request, ride_id):
        driver_id = request.data.get('driver_id')
        try:
            ride = Ride.objects.get(id=ride_id, status='PENDING')
            driver = DriverProfile.objects.get(id=driver_id)
        except (Ride.DoesNotExist, DriverProfile.DoesNotExist):
            return Response({"error": "Cuốc xe không hợp lệ hoặc đã có người nhận"}, status=status.HTTP_400_BAD_REQUEST)
        
        ride.driver = driver
        ride.status = 'ACCEPTED'
        ride.save()

        driver.status = 'BUSY'
        driver.save()

        return Response({
            "message": "Nhận chuyến thành công!",
            "ride": RideSerializer(ride).data
        }, status=status.HTTP_200_OK)


class UpdateRideStatusView(APIView):
    def patch(self, request, ride_id):
        new_status = request.data.get('status')
        try:
            ride = Ride.objects.get(id=ride_id)
        except Ride.DoesNotExist:
            return Response({"error": "Không tìm thấy chuyến đi"}, status=status.HTTP_404_NOT_FOUND)
        
        if new_status in ['IN_PROGRESS', 'COMPLETED', 'CANCELLED']:
            ride.status = new_status
            ride.save()

            if new_status == 'COMPLETED' and ride.driver:
                ride.driver.status = 'ONLINE'
                ride.driver.save()

            return Response({"message": "Cập nhật trạng thái thành công", "ride": RideSerializer(ride).data})
        
        return Response({"error": "Trạng thái mới không hợp lệ"}, status=status.HTTP_400_BAD_REQUEST)
