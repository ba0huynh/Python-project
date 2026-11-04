import os
import sys
from pathlib import Path

# Setup Django environment
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from core.routing import get_route, PRECISION
from core.models import Route

def main():
    from_lat = 10.758240352495491
    from_lng = 106.6846006495482
    to_lat = 10.814834555304614
    to_lng = 106.68664363327571
    mode = 'drive'

    print(f"Fetching route from ({from_lat}, {from_lng}) to ({to_lat}, {to_lng}) mode={mode}...")
    route = get_route(from_lat, from_lng, to_lat, to_lng, mode=mode)

    print("\n--- Route Stored in Table (core_route) ---")
    print(f"ID: {route.id}")
    print(f"Provider: {route.provider}")
    print(f"Mode: {route.mode}")
    print(f"Endpoints: ({route.from_lat}, {route.from_lng}) -> ({route.to_lat}, {route.to_lng})")
    print(f"Distance: {route.distance_m} m ({route.distance_m / 1000:.2f} km)")
    print(f"Duration: {route.duration_s} s ({route.duration_s // 60}m {route.duration_s % 60}s)")
    coords_count = len(route.geometry.get('coordinates', []))
    print(f"Coordinates count: {coords_count} points")
    print(f"First coord: {route.geometry['coordinates'][0] if coords_count else None}")
    print(f"Last coord: {route.geometry['coordinates'][-1] if coords_count else None}")

if __name__ == '__main__':
    main()
