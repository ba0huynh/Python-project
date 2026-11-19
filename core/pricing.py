"""
Fares, by distance, from the FareRule table (editable in /admin).

    fare = base_fare + per_km * max(0, km - base_km), at least minimum_fare,
           rounded to 1.000đ
    commission = fare * commission_percent / 100 (platform fee), rounded to 1.000đ
    driver_earning = fare - commission

The fare is fixed when the ride is booked (upfront pricing), so what the
customer sees in the estimate is what they pay.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .models import FareRule, VehicleType

# Geoapify routing mode per vehicle type (not a price, so it stays in code).
ROUTING_MODE = {
    VehicleType.BIKE: 'motorcycle',
    VehicleType.CAR4: 'drive',
    VehicleType.CAR7: 'drive',
}


@dataclass(frozen=True)
class Quote:
    fare: int
    commission_percent: Decimal
    commission: int
    driver_earning: int


def round_vnd(amount: Decimal) -> int:
    return int((amount / 1000).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * 1000)


def routing_mode(vehicle_type) -> str:
    return ROUTING_MODE[VehicleType(vehicle_type)]


def active_rules():
    return list(FareRule.objects.filter(is_active=True))


def get_rule(vehicle_type) -> FareRule | None:
    return FareRule.objects.filter(vehicle_type=vehicle_type, is_active=True).first()


def quote(rule: FareRule, distance_m: int) -> Quote:
    km = Decimal(distance_m) / 1000
    raw = rule.base_fare + max(Decimal(0), km - rule.base_km) * rule.per_km
    fare = max(round_vnd(raw), rule.minimum_fare)
    commission = min(round_vnd(Decimal(fare) * rule.commission_percent / 100), fare)
    return Quote(fare, rule.commission_percent, commission, fare - commission)
