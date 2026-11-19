"""
Place search and reverse geocoding through Geoapify, so the API key stays on the server.

Docs: https://apidocs.geoapify.com/docs/geocoding/
Results are cached (Django cache) because people search the same places often.
Without GEOAPIFY_API_KEY, search returns nothing and reverse returns the coordinates.
"""
import hashlib
import logging

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

AUTOCOMPLETE_URL = 'https://api.geoapify.com/v1/geocode/autocomplete'
REVERSE_URL = 'https://api.geoapify.com/v1/geocode/reverse'
CACHE_SECONDS = 24 * 3600


def _call(url, params):
    key = settings.GEOAPIFY_API_KEY
    if not key:
        return None
    try:
        resp = requests.get(url, params={**params, 'apiKey': key, 'format': 'json', 'lang': 'vi'},
                            timeout=settings.GEOAPIFY_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get('results', [])
    except (requests.RequestException, ValueError) as exc:
        logger.warning('Geoapify geocoding failed: %s', exc)
        return None


def _place(r):
    name = r.get('name') or r.get('address_line1') or r.get('formatted') or ''
    address = r.get('address_line2') or r.get('formatted') or ''
    if address == name:
        address = r.get('formatted', '')
    return {'name': name, 'address': address, 'lat': r['lat'], 'lng': r['lon']}


def search(q, lat=None, lng=None, limit=8):
    q = q.strip()
    near = f'{round(lat, 2)},{round(lng, 2)}' if lat is not None and lng is not None else ''
    cache_key = 'geo:s:' + hashlib.sha1(f'{q.lower()}|{near}'.encode()).hexdigest()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    params = {'text': q, 'limit': limit, 'filter': f'countrycode:{settings.GEO_COUNTRY_CODE}'}
    if near:
        params['bias'] = f'proximity:{lng},{lat}'
    results = _call(AUTOCOMPLETE_URL, params)
    if results is None:
        return []
    places = [_place(r) for r in results if 'lat' in r and 'lon' in r]
    cache.set(cache_key, places, CACHE_SECONDS)
    return places


def reverse(lat, lng):
    cache_key = f'geo:r:{round(lat, 4)},{round(lng, 4)}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    results = _call(REVERSE_URL, {'lat': lat, 'lon': lng})
    if not results:
        return {'name': f'{lat:.5f}, {lng:.5f}', 'address': '', 'lat': lat, 'lng': lng}
    place = {**_place(results[0]), 'lat': lat, 'lng': lng}  # keep the exact point the user picked
    cache.set(cache_key, place, CACHE_SECONDS)
    return place
