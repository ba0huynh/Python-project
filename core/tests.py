from unittest import mock

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Customer
from config.asgi import application

from .models import DriverProfile, Ride, Route
from .pricing import estimate_fare

User = get_user_model()

PICKUP = {'lat': 10.7725, 'lng': 106.6981, 'address': 'Chợ Bến Thành'}
DROPOFF = {'lat': 10.7950, 'lng': 106.7219, 'address': 'Landmark 81'}


def geoapify_response(distance=4200, time=780):
    resp = mock.Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        'type': 'FeatureCollection',
        'features': [{
            'type': 'Feature',
            'properties': {'distance': distance, 'time': time},
            'geometry': {
                'type': 'MultiLineString',
                'coordinates': [[[106.6981, 10.7725], [106.70, 10.78], [106.71, 10.79]],
                                [[106.71, 10.79], [106.7219, 10.7950]]],
            },
        }],
    }
    return resp


def make_customer(phone='+84912345678'):
    user = User.objects.create_user(username=phone, password='x')
    Customer.objects.create(user=user, phone=phone, full_name='Khách ' + phone[-2:])
    return user


def make_driver(phone='+84901234567', vehicle_type='bike', lat=10.7752, lng=106.7010, status='ONLINE'):
    user = User.objects.create_user(username=f'driver:{phone}', password='x')
    return DriverProfile.objects.create(
        user=user, phone=phone, full_name='Tài xế ' + phone[-2:], license_number='L' + phone,
        vehicle_plate='59X-' + phone[-4:], vehicle_type=vehicle_type, is_approved=True, status=status,
        current_latitude=lat, current_longitude=lng,
    )


def client_for(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION='Bearer ' + str(RefreshToken.for_user(user).access_token))
    return c


@override_settings(GEOAPIFY_API_KEY='test-key')
class RoutingTests(APITestCase):
    def setUp(self):
        self.customer = make_customer()
        self.api = client_for(self.customer)

    @mock.patch('core.routing.requests.get', return_value=geoapify_response())
    def test_estimate_returns_route_per_vehicle_and_caches(self, get):
        r = self.api.post('/api/rides/estimate/', {'pickup': PICKUP, 'dropoff': DROPOFF}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        options = {o['vehicle_type']: o for o in r.data['options']}
        self.assertEqual(set(options), {'bike', 'car4', 'car7'})
        self.assertEqual(options['bike']['fare'], estimate_fare('bike', 4200))
        route = options['bike']['route']
        self.assertEqual(route['provider'], 'geoapify')
        self.assertEqual(route['geometry']['type'], 'LineString')
        # Legs merged, shared point not duplicated
        self.assertEqual(len(route['geometry']['coordinates']), 4)
        # One call per mode (motorcycle, drive), then served from the Route table
        self.assertEqual(get.call_count, 2)
        self.api.post('/api/rides/estimate/', {'pickup': PICKUP, 'dropoff': DROPOFF}, format='json')
        self.assertEqual(get.call_count, 2)
        self.assertEqual(Route.objects.count(), 2)
        params = get.call_args.kwargs['params']
        self.assertEqual(params['waypoints'], '10.7725,106.6981|10.795,106.7219')

    @override_settings(GEOAPIFY_API_KEY='')
    def test_without_key_uses_straight_line_then_upgrades(self):
        r = self.api.post('/api/rides/estimate/', {'pickup': PICKUP, 'dropoff': DROPOFF}, format='json')
        self.assertEqual(r.data['options'][0]['route']['provider'], 'straight_line')
        with override_settings(GEOAPIFY_API_KEY='k'), \
                mock.patch('core.routing.requests.get', return_value=geoapify_response()):
            r = self.api.post('/api/rides/estimate/', {'pickup': PICKUP, 'dropoff': DROPOFF}, format='json')
        self.assertEqual(r.data['options'][0]['route']['provider'], 'geoapify')
        self.assertEqual(Route.objects.count(), 2)

    def test_estimate_validates_coordinates(self):
        r = self.api.post('/api/rides/estimate/', {'pickup': {'lat': 200, 'lng': 0}, 'dropoff': DROPOFF}, format='json')
        self.assertEqual(r.status_code, 400)


@override_settings(GEOAPIFY_API_KEY='test-key')
@mock.patch('core.routing.requests.get', return_value=geoapify_response())
class RideFlowTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.customer = make_customer()
        self.driver = make_driver()
        self.capi = client_for(self.customer)
        self.dapi = client_for(self.driver.user)

    def book(self, vehicle_type='bike'):
        r = self.capi.post('/api/rides/', {'vehicle_type': vehicle_type, 'pickup': PICKUP, 'dropoff': DROPOFF}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def test_full_ride_lifecycle(self, _get):
        ride = self.book()
        self.assertEqual(ride['status'], 'PENDING')
        self.assertEqual(ride['fare'], estimate_fare('bike', 4200))
        self.assertEqual(ride['route']['distance_m'], 4200)

        available = self.dapi.get('/api/driver/rides/available/').data
        self.assertEqual(available['total'], 1)

        r = self.dapi.post(f"/api/driver/rides/{ride['id']}/accept/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['status'], 'ACCEPTED')
        self.assertIsNotNone(r.data['approach_route'])
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.status, 'BUSY')

        url = f"/api/driver/rides/{ride['id']}/update-status/"
        self.assertEqual(self.dapi.patch(url, {'status': 'COMPLETED'}, format='json').status_code, 400)  # skip not allowed
        for s in ('ARRIVED', 'IN_PROGRESS', 'COMPLETED'):
            r = self.dapi.patch(url, {'status': s}, format='json')
            self.assertEqual(r.status_code, 200, r.data)
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.status, 'ONLINE')

        r = self.capi.post(f"/api/rides/{ride['id']}/rate/", {'rating': 4}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.rating, 4)
        self.assertEqual(self.capi.get('/api/rides/current/').data['ride'], None)
        self.assertEqual(len(self.capi.get('/api/rides/').data), 1)

    def test_second_driver_cannot_take_accepted_ride(self, _get):
        other = make_driver('+84909999999')
        ride = self.book()
        self.assertEqual(self.dapi.post(f"/api/driver/rides/{ride['id']}/accept/").status_code, 200)
        r = client_for(other.user).post(f"/api/driver/rides/{ride['id']}/accept/")
        self.assertEqual(r.status_code, 400)

    def test_only_one_active_ride_per_customer(self, _get):
        self.book()
        r = self.capi.post('/api/rides/', {'vehicle_type': 'bike', 'pickup': PICKUP, 'dropoff': DROPOFF}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_wrong_vehicle_type_and_far_drivers_dont_see_ride(self, _get):
        car = make_driver('+84908888888', vehicle_type='car4')
        far = make_driver('+84907777777', lat=21.0278, lng=105.8342)  # Hà Nội
        self.book()
        self.assertEqual(client_for(car.user).get('/api/driver/rides/available/').data['total'], 0)
        self.assertEqual(client_for(far.user).get('/api/driver/rides/available/').data['total'], 0)

    def test_driver_cancel_puts_ride_back_to_pending(self, _get):
        ride = self.book()
        self.dapi.post(f"/api/driver/rides/{ride['id']}/accept/")
        r = self.dapi.post(f"/api/rides/{ride['id']}/cancel/", {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['status'], 'PENDING')
        self.assertIsNone(r.data['driver'])
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.status, 'ONLINE')

    def test_customer_cancel_frees_driver(self, _get):
        ride = self.book()
        self.dapi.post(f"/api/driver/rides/{ride['id']}/accept/")
        r = self.capi.post(f"/api/rides/{ride['id']}/cancel/", {'reason': 'Đổi ý'}, format='json')
        self.assertEqual(r.data['status'], 'CANCELLED')
        self.assertEqual(r.data['cancelled_by'], 'customer')
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.status, 'ONLINE')

    def test_role_permissions(self, _get):
        ride = self.book()
        self.assertEqual(self.capi.post(f"/api/driver/rides/{ride['id']}/accept/").status_code, 403)
        r = self.dapi.post('/api/rides/', {'vehicle_type': 'bike', 'pickup': PICKUP, 'dropoff': DROPOFF}, format='json')
        self.assertEqual(r.status_code, 403)
        stranger = make_customer('+84911111111')
        self.assertEqual(client_for(stranger).get(f"/api/rides/{ride['id']}/").status_code, 404)
        self.assertEqual(client_for(stranger).post(f"/api/rides/{ride['id']}/cancel/").status_code, 403)

    def test_unapproved_driver_cannot_go_online(self, _get):
        self.driver.is_approved = False
        self.driver.status = 'OFFLINE'
        self.driver.save()
        r = self.dapi.patch('/api/driver/status/', {'status': 'ONLINE'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_ride_requested_event_reaches_nearby_driver(self, _get):
        layer = get_channel_layer()
        channel = async_to_sync(layer.new_channel)()
        async_to_sync(layer.group_add)(f'user_{self.driver.user_id}', channel)
        with self.captureOnCommitCallbacks(execute=True):
            ride = self.book()
        msg = async_to_sync(layer.receive)(channel)
        self.assertEqual(msg['event'], 'ride.requested')
        self.assertEqual(msg['data']['id'], ride['id'])
        self.assertIn('distance_to_pickup_m', msg['data'])


class DriverAuthTests(APITestCase):
    payload = {
        'phone': '0901234567', 'full_name': 'Trần Văn Bình', 'password': 'RideSecure!2026',
        'password_confirm': 'RideSecure!2026', 'license_number': 'B1-123', 'vehicle_plate': '59X2-123.45',
        'vehicle_type': 'bike',
    }

    def setUp(self):
        cache.clear()

    def test_register_login_me_refresh(self):
        r = self.client.post('/api/auth/driver/register/', self.payload, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['driver']['phone'], '+84901234567')
        self.assertTrue(r.data['driver']['is_approved'])
        r = self.client.post('/api/auth/driver/login/', {'phone': '+84901234567', 'password': 'RideSecure!2026'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + r.data['access'])
        self.assertEqual(self.client.get('/api/auth/driver/me/').status_code, 200)
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 403)  # not a customer
        self.client.credentials()
        self.assertEqual(self.client.post('/api/auth/refresh/', {'refresh': r.data['refresh']}, format='json').status_code, 200)

    def test_same_phone_can_be_customer_and_driver(self):
        make_customer('+84901234567')
        r = self.client.post('/api/auth/driver/register/', self.payload, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        r = self.client.post('/api/auth/login/', {'phone': '0901234567', 'password': 'RideSecure!2026'}, format='json')
        self.assertEqual(r.status_code, 400)  # driver password doesn't log into the customer account


class WebSocketTests(TransactionTestCase):
    def test_rejects_missing_token(self):
        async def run():
            comm = WebsocketCommunicator(application, '/ws/')
            connected, code = await comm.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4401)
        async_to_sync(run)()

    @override_settings(GEOAPIFY_API_KEY='')
    def test_driver_location_is_forwarded_to_customer(self):
        customer = make_customer()
        driver = make_driver(status='BUSY')
        ride = Ride.objects.create(
            customer=customer, driver=driver, status='ACCEPTED', fare=20000,
            pickup_address='A', pickup_lat=10.77, pickup_lng=106.69,
            dropoff_address='B', dropoff_lat=10.79, dropoff_lng=106.72,
        )
        ctoken = str(RefreshToken.for_user(customer).access_token)
        dtoken = str(RefreshToken.for_user(driver.user).access_token)

        async def run():
            c = WebsocketCommunicator(application, f'/ws/?token={ctoken}')
            d = WebsocketCommunicator(application, f'/ws/?token={dtoken}')
            self.assertTrue((await c.connect())[0])
            self.assertTrue((await d.connect())[0])
            self.assertEqual((await c.receive_json_from())['event'], 'connected')
            self.assertEqual((await d.receive_json_from())['event'], 'connected')
            await d.send_json_to({'type': 'ping'})
            self.assertEqual((await d.receive_json_from())['event'], 'pong')
            await d.send_json_to({'type': 'driver.location', 'lat': 10.776, 'lng': 106.70})
            msg = await c.receive_json_from(timeout=3)
            self.assertEqual(msg['event'], 'driver.location')
            self.assertEqual(msg['data'], {'ride_id': str(ride.id), 'lat': 10.776, 'lng': 106.70})
            # Customers can't push locations
            await c.send_json_to({'type': 'driver.location', 'lat': 1, 'lng': 1})
            self.assertEqual((await c.receive_json_from())['event'], 'error')
            await c.disconnect()
            await d.disconnect()

        async_to_sync(run)()
        driver.refresh_from_db()
        self.assertEqual(driver.current_latitude, 10.776)
