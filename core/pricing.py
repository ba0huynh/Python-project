"""Fare rules. Keep in sync with VEHICLES / estimateFare in mobile/src/lib/mock.ts."""
from dataclasses import dataclass

from .models import VehicleType


@dataclass(frozen=True)
class VehiclePricing:
    name: str
    seats: int
    base_fare: int  # VND, covers the first BASE_KM
    per_km: int  # VND per km after BASE_KM
    routing_mode: str  # Geoapify routing mode


BASE_KM = 2

PRICING = {
    VehicleType.BIKE: VehiclePricing('GoBike', 1, 12_000, 4_500, 'motorcycle'),
    VehicleType.CAR4: VehiclePricing('GoCar 4 chỗ', 4, 25_000, 9_000, 'drive'),
    VehicleType.CAR7: VehiclePricing('GoCar 7 chỗ', 7, 30_000, 11_000, 'drive'),
}


def estimate_fare(vehicle_type: str, distance_m: int) -> int:
    p = PRICING[VehicleType(vehicle_type)]
    km = distance_m / 1000
    fare = p.base_fare + max(0.0, km - BASE_KM) * p.per_km
    return int(round(fare / 1000) * 1000)  # round to 1.000đ
