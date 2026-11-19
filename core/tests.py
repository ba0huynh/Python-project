from datetime import timedelta
from decimal import Decimal
from unittest import mock

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Customer
from accounts.tests import request_otp
from config.asgi import application

from . import services
from .models import DriverProfile, FareRule, Ride, RideOffer, Route
from .pricing import quote

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


def make_driver(phone='+84901234567', vehicle_type='bike', lat=10.7735, lng=106.6990, status='ONLINE',
                approved=True, seen_ago=0):
    user = User.objects.create_user(username=f'driver:{phone}', password='x')
    return DriverProfile.objects.create(
        user=user, phone=phone, full_name='Tài xế ' + phone[-2:], license_number='L' + phone,
        vehicle_plate='59X-' + phone[-4:], vehicle_type=vehicle_type, is_approved=approved, status=status,
        current_latitude=lat, current_longitude=lng,
        location_updated_at=timezone.now() - timedelta(seconds=seen_ago),
    )


def client_for(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION='Bearer ' + str(RefreshToken.for_user(user).access_token))
    return c


class PricingTests(TestCase):
    def rule(self, **kw):
        defaults = dict(vehicle_type='bike', display_name='X', base_fare=12_000, base_km=Decimal('2'),
                        per_km=4_500, minimum_fare=15_000, commission_percent=Decimal('20'))
        return FareRule(**{**defaults, **kw})

    def test_fare_by_km_with_minimum_rounding_and_commission(self):
        q = quote(self.rule(), 4200)  # 12.000 + 2.2 km * 4.500 = 21.900 -> 22.000
        self.assertEqual((q.fare, q.commission, q.driver_earning), (22_000, 4_000, 18_000))
        self.assertEqual(quote(self.rule(), 500).fare, 15_000)  # short trip -> minimum fare
        self.assertEqual(quote(self.rule(commission_percent=Decimal('0')), 4200).driver_earning, 22_000)

    def test_initial_rules_exist(self):
        self.assertEqual(set(FareRule.objects.values_list('vehicle_type', flat=True)), {'bike', 'car4', 'car7'})


@override_settings(GEOAPIFY_API_KEY='test-key')
class EstimateTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.api = client_for(make_customer())

    def estimate(self, pickup=PICKUP, dropoff=DROPOFF):
        return self.api.post('/api/rides/estimate/', {'pickup': pickup, 'dropoff': dropoff}, format='json')

    @mock.patch('core.routing.requests.get', return_value=geoapify_response())
    def test_estimate_uses_fare_rules_and_caches_routes(self, get):
        make_driver()
        make_driver('+84909999999', seen_ago=600)  # stale GPS: not counted
        r = self.estimate()
        self.assertEqual(r.status_code, 200, r.data)
        options = {o['vehicle_type']: o for o in r.data['options']}
        self.assertEqual(set(options), {'bike', 'car4', 'car7'})
        bike = options['bike']
        self.assertEqual(bike['fare'], quote(FareRule.objects.get(vehicle_type='bike'), 4200).fare)
        self.assertEqual((bike['distance_m'], bike['duration_s'], bike['drivers_nearby']), (4200, 780, 1))
        self.assertEqual(options['car4']['drivers_nearby'], 0)
        self.assertEqual(len(bike['route']['geometry']['coordinates']), 4)  # legs merged
        self.assertEqual(get.call_count, 2)  # motorcycle + drive, then cached
        self.estimate()
        self.assertEqual(get.call_count, 2)
        self.assertEqual(Route.objects.count(), 2)

    @mock.patch('core.routing.requests.get', return_value=geoapify_response())
    def test_admin_price_change_and_disabled_type(self, _get):
        FareRule.objects.filter(vehicle_type='bike').update(base_fare=50_000, minimum_fare=0)
        FareRule.objects.filter(vehicle_type='car7').update(is_active=False)
        options = {o['vehicle_type']: o for o in self.estimate().data['options']}
        self.assertNotIn('car7', options)
        self.assertEqual(options['bike']['fare'], 60_000)  # 50.000 + 2.2 km * 4.500 = 59.900
        r = self.api.post('/api/rides/', {'vehicle_type': 'car7', 'pickup': PICKUP, 'dropoff': DROPOFF},
                          format='json')
        self.assertEqual(r.status_code, 400)

    @override_settings(GEOAPIFY_API_KEY='')
    def test_without_key_uses_straight_line_then_upgrades(self):
        self.assertEqual(self.estimate().data['options'][0]['route']['provider'], 'straight_line')
        with override_settings(GEOAPIFY_API_KEY='k'), \
                mock.patch('core.routing.requests.get', return_value=geoapify_response()):
            r = self.estimate()
        self.assertEqual(r.data['options'][0]['route']['provider'], 'geoapify')

    def test_invalid_or_too_short_trip(self):
        self.assertEqual(self.estimate(pickup={'lat': 200, 'lng': 0}).status_code, 400)
        near = {'lat': PICKUP['lat'] + 0.0005, 'lng': PICKUP['lng']}  # ~55 m
        self.assertEqual(self.estimate(dropoff=near).status_code, 400)

    def test_drivers_cannot_estimate(self):
        r = client_for(make_driver().user).post('/api/rides/estimate/', {'pickup': PICKUP, 'dropoff': DROPOFF},
                                                format='json')
        self.assertEqual(r.status_code, 403)


@override_settings(GEOAPIFY_API_KEY='test-key', DISPATCH_BATCH_SIZE=3)
@mock.patch('core.routing.requests.get', return_value=geoapify_response())
class RideFlowTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.customer = make_customer()
        self.driver = make_driver()
        self.capi = client_for(self.customer)
        self.dapi = client_for(self.driver.user)

    def book(self, vehicle_type='bike', api=None):
        r = (api or self.capi).post('/api/rides/', {'vehicle_type': vehicle_type, 'pickup': PICKUP,
                                                    'dropoff': DROPOFF}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def accept(self, ride, api=None):
        return (api or self.dapi).post(f"/api/driver/rides/{ride['id']}/accept/")

    def move_driver_to_pickup(self, driver=None):
        DriverProfile.objects.filter(pk=(driver or self.driver).pk).update(
            current_latitude=PICKUP['lat'], current_longitude=PICKUP['lng'], location_updated_at=timezone.now()
        )

    def test_full_ride_lifecycle_with_commission(self, _get):
        ride = self.book()
        self.assertEqual(ride['status'], 'PENDING')
        self.assertIsNotNone(ride['search_expires_at'])
        self.assertNotIn('driver_earning', ride)  # customers don't see the platform split
        db_ride = Ride.objects.get(pk=ride['id'])
        self.assertEqual(db_ride.fare, 22_000)
        self.assertEqual((db_ride.commission, db_ride.driver_earning), (4_000, 18_000))

        offers = self.dapi.get('/api/driver/offers/').data['offers']
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]['ride']['customer']['phone'], '')  # hidden until accepted
        self.assertEqual(offers[0]['ride']['driver_earning'], 18_000)

        r = self.accept(ride)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['status'], 'ACCEPTED')
        self.assertEqual(r.data['customer']['phone'], '+84912345678')
        self.assertEqual(r.data['driver_earning'], 18_000)
        self.assertIsNotNone(r.data['approach_route'])
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.status, 'BUSY')

        url = f"/api/driver/rides/{ride['id']}/update-status/"
        self.assertEqual(self.dapi.patch(url, {'status': 'COMPLETED'}, format='json').status_code, 400)
        self.move_driver_to_pickup()
        for s in ('ARRIVED', 'IN_PROGRESS', 'COMPLETED'):
            r = self.dapi.patch(url, {'status': s}, format='json')
            self.assertEqual(r.status_code, 200, r.data)
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.status, 'ONLINE')

        r = self.capi.post(f"/api/rides/{ride['id']}/rate/", {'rating': 4}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.capi.post(f"/api/rides/{ride['id']}/rate/", {'rating': 5}, format='json').status_code,
                         400)
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.rating, 4)
        self.assertIsNone(self.capi.get('/api/rides/current/').data['ride'])

        history = self.capi.get('/api/rides/?limit=10').data
        self.assertEqual(history['count'], 1)
        self.assertEqual(history['results'][0]['id'], ride['id'])
        earnings = self.dapi.get('/api/driver/earnings/').data
        self.assertEqual(earnings['today'], {'trips': 1, 'gross': 22_000, 'commission': 4_000, 'net': 18_000})
        self.assertEqual(len(earnings['recent']), 1)

    def test_customer_cannot_drive_the_ride(self, _get):
        ride = self.book()
        self.assertEqual(self.capi.post(f"/api/rides/{ride['id']}/auto-accept/").status_code, 404)
        self.assertEqual(self.capi.post(f"/api/rides/{ride['id']}/auto-advance/").status_code, 404)
        self.assertEqual(self.accept(ride, self.capi).status_code, 403)

    def test_arrived_requires_being_near_pickup(self, _get):
        ride = self.book()
        self.accept(ride)
        DriverProfile.objects.filter(pk=self.driver.pk).update(current_latitude=10.80, current_longitude=106.75)
        url = f"/api/driver/rides/{ride['id']}/update-status/"
        r = self.dapi.patch(url, {'status': 'ARRIVED'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.move_driver_to_pickup()
        self.assertEqual(self.dapi.patch(url, {'status': 'ARRIVED'}, format='json').status_code, 200)

    def test_only_offered_driver_can_accept(self, _get):
        far = make_driver('+84909999999', lat=10.85, lng=106.80)  # ~12 km, outside radius
        ride = self.book()
        self.assertEqual(self.accept(ride, client_for(far.user)).status_code, 400)
        self.assertEqual(self.accept(ride).status_code, 200)

    def test_first_accept_wins_and_others_are_withdrawn(self, _get):
        other = make_driver('+84909999999')
        ride = self.book()
        self.assertEqual(RideOffer.objects.filter(ride_id=ride['id'], status='PENDING').count(), 2)
        self.assertEqual(self.accept(ride).status_code, 200)
        self.assertEqual(self.accept(ride, client_for(other.user)).status_code, 400)
        self.assertEqual(RideOffer.objects.get(ride_id=ride['id'], driver=other).status, 'WITHDRAWN')

    def test_offers_go_in_batches_to_nearest_free_drivers(self, _get):
        drivers = [self.driver] + [
            make_driver(f'+8490900000{i}', lat=10.7735 + 0.003 * i, lng=106.6990) for i in range(1, 4)
        ]
        make_driver('+84908888888', vehicle_type='car4')  # wrong type
        make_driver('+84907777777', seen_ago=600)  # GPS too old
        make_driver('+84906666666', approved=False)
        ride = self.book()
        offered = set(RideOffer.objects.filter(ride_id=ride['id']).values_list('driver_id', flat=True))
        self.assertEqual(offered, {d.id for d in drivers[:3]})  # three nearest

        # Everyone in the batch declines -> the next nearest gets it.
        for d in drivers[:3]:
            self.assertEqual(client_for(d.user).post(f"/api/driver/rides/{ride['id']}/decline/").status_code, 204)
        last = RideOffer.objects.filter(ride_id=ride['id'], status='PENDING').get()
        self.assertEqual(last.driver_id, drivers[3].id)

    def test_driver_with_open_offer_gets_no_second_offer(self, _get):
        self.book()
        other_customer = make_customer('+84911111111')
        self.book(api=client_for(other_customer))
        self.assertEqual(RideOffer.objects.filter(driver=self.driver).count(), 1)

    def test_expired_offer_moves_to_next_driver_on_worker_pass(self, _get):
        ride = self.book()
        late = make_driver('+84909999999')  # came online after the first batch
        RideOffer.objects.filter(ride_id=ride['id']).update(expires_at=timezone.now() - timedelta(seconds=5))
        self.assertEqual(self.accept(ride).status_code, 400)  # too late
        services.run_dispatch_cycle()
        self.assertEqual(RideOffer.objects.get(ride_id=ride['id'], driver=self.driver).status, 'EXPIRED')
        self.assertEqual(RideOffer.objects.get(ride_id=ride['id'], driver=late).status, 'PENDING')

    def test_search_times_out_with_system_cancel(self, _get):
        ride = self.book()
        Ride.objects.filter(pk=ride['id']).update(dispatched_at=timezone.now() - timedelta(minutes=10))
        self.assertIsNone(self.capi.get('/api/rides/current/').data['ride'])  # lazy, even without the worker
        r = self.capi.get(f"/api/rides/{ride['id']}/").data
        self.assertEqual((r['status'], r['cancelled_by']), ('CANCELLED', 'system'))
        self.assertEqual(RideOffer.objects.get(ride_id=ride['id']).status, 'WITHDRAWN')

    def test_only_one_active_ride_per_customer(self, _get):
        self.book()
        r = self.capi.post('/api/rides/', {'vehicle_type': 'bike', 'pickup': PICKUP, 'dropoff': DROPOFF},
                           format='json')
        self.assertEqual(r.status_code, 400)

    def test_driver_cancel_reoffers_ride_to_someone_else(self, _get):
        loser = make_driver('+84908888888')  # offered too, but lost the race
        ride = self.book()
        self.accept(ride)
        other = make_driver('+84909999999')
        r = self.dapi.post(f"/api/rides/{ride['id']}/cancel/", {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['status'], 'PENDING')
        self.assertIsNone(r.data['driver'])
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.status, 'ONLINE')
        self.assertTrue(RideOffer.objects.filter(ride_id=ride['id'], driver=other, status='PENDING').exists())
        self.assertTrue(RideOffer.objects.filter(ride_id=ride['id'], driver=loser, status='PENDING').exists())
        self.assertFalse(RideOffer.objects.filter(ride_id=ride['id'], driver=self.driver, status='PENDING').exists())

    def test_customer_cancel_frees_driver(self, _get):
        ride = self.book()
        self.accept(ride)
        r = self.capi.post(f"/api/rides/{ride['id']}/cancel/", {'reason': 'Đổi ý'}, format='json')
        self.assertEqual(r.data['status'], 'CANCELLED')
        self.assertEqual(r.data['cancelled_by'], 'customer')
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.status, 'ONLINE')

    def test_role_permissions(self, _get):
        ride = self.book()
        r = self.dapi.post('/api/rides/', {'vehicle_type': 'bike', 'pickup': PICKUP, 'dropoff': DROPOFF},
                           format='json')
        self.assertEqual(r.status_code, 403)
        stranger = make_customer('+84911111111')
        self.assertEqual(client_for(stranger).get(f"/api/rides/{ride['id']}/").status_code, 404)
        self.assertEqual(client_for(stranger).post(f"/api/rides/{ride['id']}/cancel/").status_code, 403)
        # A driver who was only offered the ride can't read its details (customer phone).
        self.assertEqual(self.dapi.get(f"/api/rides/{ride['id']}/").status_code, 404)

    def test_driver_status_rules(self, _get):
        DriverProfile.objects.filter(pk=self.driver.pk).update(is_approved=False, status='OFFLINE')
        self.driver.refresh_from_db()
        self.assertEqual(self.dapi.patch('/api/driver/status/', {'status': 'ONLINE', 'lat': 10.77, 'lng': 106.7},
                                         format='json').status_code, 403)
        DriverProfile.objects.filter(pk=self.driver.pk).update(is_approved=True)
        self.assertEqual(self.dapi.patch('/api/driver/status/', {'status': 'ONLINE'}, format='json').status_code,
                         400)  # needs GPS
        r = self.dapi.patch('/api/driver/status/', {'status': 'ONLINE', 'lat': 10.7735, 'lng': 106.699},
                            format='json')
        self.assertEqual(r.data['status'], 'ONLINE')

    def test_going_offline_passes_offer_to_next_driver(self, _get):
        other = make_driver('+84909999999', lat=10.80, lng=106.70)  # farther, so second in line
        with override_settings(DISPATCH_BATCH_SIZE=1):
            ride = self.book()
            self.assertEqual(RideOffer.objects.get(ride_id=ride['id'], status='PENDING').driver_id, self.driver.id)
            self.dapi.patch('/api/driver/status/', {'status': 'OFFLINE'}, format='json')
        self.assertEqual(RideOffer.objects.get(ride_id=ride['id'], status='PENDING').driver_id, other.id)

    def test_offer_event_reaches_driver(self, _get):
        layer = get_channel_layer()
        channel = async_to_sync(layer.new_channel)()
        async_to_sync(layer.group_add)(f'user_{self.driver.user_id}', channel)
        with self.captureOnCommitCallbacks(execute=True):
            ride = self.book()
        msg = async_to_sync(layer.receive)(channel)
        self.assertEqual(msg['event'], 'ride.offer')
        self.assertEqual(msg['data']['ride_id'], ride['id'])
        self.assertEqual(msg['data']['ride']['customer']['phone'], '')
        self.assertIn('expires_at', msg['data'])
        self.assertTrue(13 <= msg['data']['expires_in'] <= 15)


class GeoTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.api = client_for(make_customer())

    @override_settings(GEOAPIFY_API_KEY='k')
    @mock.patch('core.geocoding.requests.get')
    def test_search_and_reverse(self, get):
        get.return_value = mock.Mock(raise_for_status=lambda: None, json=lambda: {'results': [
            {'name': 'Chợ Bến Thành', 'address_line2': 'Lê Lợi, Quận 1', 'formatted': 'x', 'lat': 10.77, 'lon': 106.69},
        ]})
        r = self.api.get('/api/geo/search/', {'q': 'ben thanh', 'lat': 10.77, 'lng': 106.7})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['results'][0], {'name': 'Chợ Bến Thành', 'address': 'Lê Lợi, Quận 1',
                                                'lat': 10.77, 'lng': 106.69})
        self.assertNotIn('k', str(r.data))
        self.api.get('/api/geo/search/', {'q': 'ben thanh', 'lat': 10.77, 'lng': 106.7})
        self.assertEqual(get.call_count, 1)  # cached
        r = self.api.get('/api/geo/reverse/', {'lat': 10.7725, 'lng': 106.6981})
        self.assertEqual((r.data['name'], r.data['lat']), ('Chợ Bến Thành', 10.7725))

    @override_settings(GEOAPIFY_API_KEY='')
    def test_without_key(self):
        self.assertEqual(self.api.get('/api/geo/search/', {'q': 'abc'}).data['results'], [])
        self.assertEqual(self.api.get('/api/geo/reverse/', {'lat': 10.77, 'lng': 106.69}).data['name'],
                         '10.77000, 106.69000')
        self.assertEqual(self.api.get('/api/geo/search/', {'q': 'a'}).status_code, 400)

    def test_requires_login_and_health_is_public(self):
        self.assertEqual(APIClient().get('/api/geo/search/', {'q': 'abc'}).status_code, 401)
        self.assertEqual(APIClient().get('/api/health/').data, {'status': 'ok'})


class SamePhoneTests(APITestCase):
    def test_same_phone_can_be_customer_and_driver(self):
        cache.clear()
        make_customer('+84901234567')
        _, code = request_otp(self.client, '0901234567', role='driver')
        cache.clear()
        r = self.client.post('/api/auth/driver/register/', {
            'phone': '0901234567', 'full_name': 'Trần Văn Bình', 'password': 'RideSecure!2026',
            'password_confirm': 'RideSecure!2026', 'license_number': 'B1-123', 'vehicle_plate': '59X2-123.45',
            'vehicle_type': 'bike', 'otp': code,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        r = self.client.post('/api/auth/login/', {'phone': '0901234567', 'password': 'RideSecure!2026'},
                             format='json')
        self.assertEqual(r.status_code, 400)  # driver password doesn't log into the customer account


@override_settings(RIDE_WORKER_EMBEDDED=False)
class WebSocketTests(TransactionTestCase):
    def test_rejects_missing_token_with_4401(self):
        async def run():
            comm = WebsocketCommunicator(application, '/ws/')
            await comm.connect()
            output = await comm.receive_output()
            self.assertEqual(output, {'type': 'websocket.close', 'code': 4401})
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
            await d.send_json_to({'type': 'driver.location', 'lat': 10.776, 'lng': 106.70, 'heading': 90})
            msg = await c.receive_json_from(timeout=3)
            self.assertEqual(msg['event'], 'driver.location')
            self.assertEqual(msg['data'], {'ride_id': str(ride.id), 'lat': 10.776, 'lng': 106.70, 'heading': 90.0})
            # Customers can't push locations
            await c.send_json_to({'type': 'driver.location', 'lat': 1, 'lng': 1})
            self.assertEqual((await c.receive_json_from())['event'], 'error')
            await c.disconnect()
            await d.disconnect()

        async_to_sync(run)()
        driver.refresh_from_db()
        self.assertEqual((driver.current_latitude, driver.current_heading), (10.776, 90.0))

    def test_unknown_heading_is_stored_as_null(self):
        driver = make_driver()
        r = client_for(driver.user).post('/api/driver/location/', {'lat': 10.77, 'lng': 106.7, 'heading': -1},
                                         format='json')
        self.assertEqual(r.status_code, 204)
        driver.refresh_from_db()
        self.assertIsNone(driver.current_heading)


class AdminRideSummaryTests(TransactionTestCase):
    def test_summary_changelist_empty(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from core.models import RideSummary
        from core.admin import RideSummaryAdmin

        admin_site = admin.AdminSite()
        model_admin = RideSummaryAdmin(RideSummary, admin_site)

        rf = RequestFactory()
        request = rf.get('/admin/core/ridesummary/')
        request.user = User.objects.create_superuser('admin_kpi_test', 'kpi@test.com', 'pass')

        cl = model_admin.get_changelist_instance(request)
        self.assertEqual(len(cl.result_list), 0)

    def test_summary_changelist_with_data(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from core.models import RideSummary
        from core.admin import RideSummaryAdmin

        admin_site = admin.AdminSite()
        model_admin = RideSummaryAdmin(RideSummary, admin_site)

        d1 = make_driver(phone='+84909990001', vehicle_type='bike')
        d2 = make_driver(phone='+84909990002', vehicle_type='car4')
        customer = make_customer(phone='+84909990003')

        # 1 completed bike ride
        Ride.objects.create(
            customer=customer, driver=d1, vehicle_type='bike', status='COMPLETED', fare=50000,
            pickup_address='A', pickup_lat=10.77, pickup_lng=106.69,
            dropoff_address='B', dropoff_lat=10.79, dropoff_lng=106.72,
        )

        # 1 cancelled bike ride
        Ride.objects.create(
            customer=customer, driver=d1, vehicle_type='bike', status='CANCELLED', fare=20000,
            pickup_address='A', pickup_lat=10.77, pickup_lng=106.69,
            dropoff_address='B', dropoff_lat=10.79, dropoff_lng=106.72,
        )

        # 1 completed car4 ride
        Ride.objects.create(
            customer=customer, driver=d2, vehicle_type='car4', status='COMPLETED', fare=120000,
            pickup_address='A', pickup_lat=10.77, pickup_lng=106.69,
            dropoff_address='B', dropoff_lat=10.79, dropoff_lng=106.72,
        )

        rf = RequestFactory()
        request = rf.get('/admin/core/ridesummary/')
        request.user = User.objects.create_superuser('admin_kpi_test2', 'kpi2@test.com', 'pass')

        cl = model_admin.get_changelist_instance(request)
        self.assertEqual(len(cl.result_list), 2)

        # Find bike row
        bike_row = next(r for r in cl.result_list if r.vehicle_type == 'bike')
        self.assertEqual(bike_row.total_rides, 2)
        self.assertEqual(bike_row.completed_rides, 1)
        self.assertEqual(bike_row.cancelled_rides, 1)
        self.assertEqual(bike_row.total_revenue, 50000)

        # Find car4 row
        car4_row = next(r for r in cl.result_list if r.vehicle_type == 'car4')
        self.assertEqual(car4_row.total_rides, 1)
        self.assertEqual(car4_row.completed_rides, 1)
        self.assertEqual(car4_row.cancelled_rides, 0)
        self.assertEqual(car4_row.total_revenue, 120000)

        # Permissions check
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))


class CustomAdminFilterTests(TransactionTestCase):
    def test_fare_range_and_distance_filters(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from core.models import Ride
        from core.admin import FareRangeFilter, DistanceFilter, RideAdmin

        admin_site = admin.AdminSite()
        model_admin = RideAdmin(Ride, admin_site)
        rf = RequestFactory()

        customer = make_customer(phone='+84909111222')
        driver = make_driver(phone='+84909333444')

        # low fare (<50k), short distance (<5km)
        r1 = Ride.objects.create(
            customer=customer, driver=driver, fare=30000, distance_m=3000, status='COMPLETED',
            pickup_address='A', pickup_lat=10.77, pickup_lng=106.69,
            dropoff_address='B', dropoff_lat=10.79, dropoff_lng=106.72,
        )
        # medium fare (50k-100k), long distance (>=5km)
        r2 = Ride.objects.create(
            customer=customer, driver=driver, fare=75000, distance_m=8000, status='COMPLETED',
            pickup_address='A', pickup_lat=10.77, pickup_lng=106.69,
            dropoff_address='B', dropoff_lat=10.79, dropoff_lng=106.72,
        )
        # high fare (>100k), long distance (>=5km)
        r3 = Ride.objects.create(
            customer=customer, driver=driver, fare=150000, distance_m=12000, status='COMPLETED',
            pickup_address='A', pickup_lat=10.77, pickup_lng=106.69,
            dropoff_address='B', dropoff_lat=10.79, dropoff_lng=106.72,
        )

        base_qs = Ride.objects.filter(id__in=[r1.id, r2.id, r3.id])

        # Test FareRangeFilter: low
        req_low = rf.get('/admin/core/ride/?fare_range=low')
        f_low = FareRangeFilter(req_low, req_low.GET.copy(), Ride, model_admin)
        self.assertEqual(list(f_low.queryset(req_low, base_qs)), [r1])

        # Test FareRangeFilter: medium
        req_med = rf.get('/admin/core/ride/?fare_range=medium')
        f_med = FareRangeFilter(req_med, req_med.GET.copy(), Ride, model_admin)
        self.assertEqual(list(f_med.queryset(req_med, base_qs)), [r2])

        # Test FareRangeFilter: high
        req_high = rf.get('/admin/core/ride/?fare_range=high')
        f_high = FareRangeFilter(req_high, req_high.GET.copy(), Ride, model_admin)
        self.assertEqual(list(f_high.queryset(req_high, base_qs)), [r3])

        # Test DistanceFilter: short
        req_short = rf.get('/admin/core/ride/?distance=short')
        d_short = DistanceFilter(req_short, req_short.GET.copy(), Ride, model_admin)
        self.assertEqual(list(d_short.queryset(req_short, base_qs)), [r1])

        # Test DistanceFilter: long
        req_long = rf.get('/admin/core/ride/?distance=long')
        d_long = DistanceFilter(req_long, req_long.GET.copy(), Ride, model_admin)
        self.assertCountEqual(list(d_long.queryset(req_long, base_qs)), [r2, r3])

    def test_bad_rating_filter(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from core.models import Ride
        from core.admin import BadRatingFilter, RideAdmin

        admin_site = admin.AdminSite()
        model_admin = RideAdmin(Ride, admin_site)
        rf = RequestFactory()

        customer = make_customer(phone='+84909555666')
        driver = make_driver(phone='+84909777888')

        # 1-star bad rating
        r_bad = Ride.objects.create(
            customer=customer, driver=driver, fare=30000, distance_m=3000,
            status='COMPLETED', rating=1, rating_comment='Very bad attitude',
            pickup_address='A', pickup_lat=10.77, pickup_lng=106.69,
            dropoff_address='B', dropoff_lat=10.79, dropoff_lng=106.72,
        )
        # 5-star good rating
        r_good = Ride.objects.create(
            customer=customer, driver=driver, fare=50000, distance_m=5000,
            status='COMPLETED', rating=5, rating_comment='Excellent',
            pickup_address='A', pickup_lat=10.77, pickup_lng=106.69,
            dropoff_address='B', dropoff_lat=10.79, dropoff_lng=106.72,
        )
        # Completed but unrated
        r_unrated = Ride.objects.create(
            customer=customer, driver=driver, fare=40000, distance_m=4000,
            status='COMPLETED', rating=None,
            pickup_address='A', pickup_lat=10.77, pickup_lng=106.69,
            dropoff_address='B', dropoff_lat=10.79, dropoff_lng=106.72,
        )
        # Cancelled (unrated but not completed)
        r_cancelled = Ride.objects.create(
            customer=customer, driver=driver, fare=20000, distance_m=2000,
            status='CANCELLED', rating=None,
            pickup_address='A', pickup_lat=10.77, pickup_lng=106.69,
            dropoff_address='B', dropoff_lat=10.79, dropoff_lng=106.72,
        )

        base_qs = Ride.objects.filter(id__in=[r_bad.id, r_good.id, r_unrated.id, r_cancelled.id])

        from core.admin import RatingFilter
        # Test 1 star
        req_1 = rf.get('/admin/core/ride/?rating=1')
        f_1 = RatingFilter(req_1, req_1.GET.copy(), Ride, model_admin)
        self.assertEqual(list(f_1.queryset(req_1, base_qs)), [r_bad])

        # Test 5 stars
        req_5 = rf.get('/admin/core/ride/?rating=5')
        f_5 = RatingFilter(req_5, req_5.GET.copy(), Ride, model_admin)
        self.assertEqual(list(f_5.queryset(req_5, base_qs)), [r_good])

        # Test unrated
        req_unrated = rf.get('/admin/core/ride/?rating=unrated')
        f_unrated = RatingFilter(req_unrated, req_unrated.GET.copy(), Ride, model_admin)
        self.assertCountEqual(list(f_unrated.queryset(req_unrated, base_qs)), [r_unrated, r_cancelled])

        # Readonly fields check
        self.assertIn('rating', model_admin.readonly_fields)
        self.assertIn('rating_comment', model_admin.readonly_fields)

    def test_ride_admin_export_csv_action(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from core.admin import RideAdmin

        admin_site = admin.AdminSite()
        model_admin = RideAdmin(Ride, admin_site)
        rf = RequestFactory()

        customer = make_customer(phone='+84909111222')
        driver = make_driver(phone='+84909333444')
        ride = Ride.objects.create(
            customer=customer, driver=driver, fare=35000, distance_m=3500,
            status='COMPLETED', rating=5, rating_comment='Rat hai long',
            pickup_address='Ben Thanh', pickup_lat=10.77, pickup_lng=106.69,
            dropoff_address='Pho di bo', dropoff_lat=10.79, dropoff_lng=106.72,
        )

        req = rf.post('/admin/core/ride/')
        req.user = customer
        response = model_admin.export_selected_rides_to_csv(req, Ride.objects.filter(id=ride.id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment; filename="goxe_rides_', response['Content-Disposition'])

        content = response.content.decode('utf-8-sig')
        self.assertIn('Ride ID,Created At', content)
        self.assertIn('Ben Thanh', content)
        self.assertIn('Rat hai long', content)
        self.assertIn(',35000,', content)


class SeedCommandTests(TransactionTestCase):
    def test_seed_is_idempotent_across_redeploys(self):
        from io import StringIO
        from django.core.management import call_command

        call_command('seed', force=True, stdout=StringIO())
        initial_rides = Ride.objects.count()
        initial_drivers = DriverProfile.objects.count()
        self.assertGreater(initial_rides, 0)
        self.assertEqual(initial_drivers, 15)
        self.assertTrue(User.objects.filter(username='admin1', is_superuser=True).exists())

        driver = DriverProfile.objects.first()
        driver.status = 'OFFLINE'
        driver.save(update_fields=['status'])

        call_command('seed', force=True, stdout=StringIO())
        self.assertEqual(Ride.objects.count(), initial_rides)
        self.assertEqual(DriverProfile.objects.count(), initial_drivers)
        driver.refresh_from_db()
        self.assertEqual(driver.status, 'OFFLINE')
