"""
Road routes from the Geoapify Routing API, cached in the `Route` table.

Docs: https://apidocs.geoapify.com/docs/routing/
Request: GET /v1/routing?waypoints=lat,lng|lat,lng&mode=motorcycle&apiKey=...
Response: GeoJSON FeatureCollection; features[0].geometry is a MultiLineString
(one line per leg), properties.distance is meters, properties.time is seconds.

Without GEOAPIFY_API_KEY (or if the API fails) a straight-line estimate is
stored instead (provider='straight_line') and replaced on the next request
once Geoapify works again.
"""
import logging
import math

import requests
from django.conf import settings
from django.db import IntegrityError

from .models import Route

logger = logging.getLogger(__name__)

GEOAPIFY_URL = 'https://api.geoapify.com/v1/routing'
# 4 decimals ~ 11 m: close-enough requests share one cached route.
PRECISION = 4
# Straight-line fallback: roads are ~30% longer than a crow's flight, ~25 km/h in city traffic.
DETOUR_FACTOR = 1.3
FALLBACK_SPEED_MPS = 25 / 3.6


class RoutingError(Exception):
    pass


def haversine_m(lat1, lng1, lat2, lng2):
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def fetch_geoapify(from_lat, from_lng, to_lat, to_lng, mode):
    """Call Geoapify and return (distance_m, duration_s, LineString geometry)."""
    key = settings.GEOAPIFY_API_KEY
    if not key:
        raise RoutingError('GEOAPIFY_API_KEY is not set')
    try:
        resp = requests.get(
            GEOAPIFY_URL,
            params={
                'waypoints': f'{from_lat},{from_lng}|{to_lat},{to_lng}',
                'mode': mode,
                'apiKey': key,
            },
            timeout=settings.GEOAPIFY_TIMEOUT,
        )
        resp.raise_for_status()
        feature = resp.json()['features'][0]
    except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
        raise RoutingError(f'Geoapify request failed: {exc}') from exc

    geom = feature['geometry']
    if geom['type'] == 'MultiLineString':
        # Join legs into one line; drop each leg's first point (it repeats the previous leg's last).
        coords = []
        for i, leg in enumerate(geom['coordinates']):
            coords.extend(leg if i == 0 else leg[1:])
    else:
        coords = geom['coordinates']
    props = feature['properties']
    return int(props['distance']), int(props['time']), {'type': 'LineString', 'coordinates': coords}


def straight_line(from_lat, from_lng, to_lat, to_lng):
    distance = haversine_m(from_lat, from_lng, to_lat, to_lng) * DETOUR_FACTOR
    geometry = {'type': 'LineString', 'coordinates': [[from_lng, from_lat], [to_lng, to_lat]]}
    return int(distance), int(distance / FALLBACK_SPEED_MPS), geometry


def get_route(from_lat, from_lng, to_lat, to_lng, mode='drive') -> Route:
    """Return a cached Route for these endpoints, fetching from Geoapify if needed."""
    key = {
        'mode': mode,
        'from_lat': round(from_lat, PRECISION),
        'from_lng': round(from_lng, PRECISION),
        'to_lat': round(to_lat, PRECISION),
        'to_lng': round(to_lng, PRECISION),
    }
    cached = Route.objects.filter(**key).first()
    if cached and cached.provider == 'geoapify':
        return cached

    try:
        distance, duration, geometry = fetch_geoapify(
            key['from_lat'], key['from_lng'], key['to_lat'], key['to_lng'], mode
        )
        provider = 'geoapify'
    except RoutingError as exc:
        if cached:  # keep the old fallback, nothing better available
            return cached
        logger.warning('%s; using straight-line route', exc)
        distance, duration, geometry = straight_line(
            key['from_lat'], key['from_lng'], key['to_lat'], key['to_lng']
        )
        provider = 'straight_line'

    values = {'distance_m': distance, 'duration_s': duration, 'geometry': geometry, 'provider': provider}
    if cached:
        for field, value in values.items():
            setattr(cached, field, value)
        cached.save()
        return cached
    try:
        return Route.objects.create(**key, **values)
    except IntegrityError:  # another request stored it first
        return Route.objects.get(**key)
