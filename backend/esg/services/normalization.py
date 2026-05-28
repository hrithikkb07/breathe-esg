"""
Unit normalization for the ESG ingestion pipeline.

Canonical units after normalization:
  Fuel:        liters (volume) + kWh equivalent (energy)
  Electricity: kWh
  Distance:    km
  Hotel stays: nights (dimensionless)

Why kWh for fuel energy equivalent:
  Emission factors are typically expressed per unit of energy (kWh or GJ),
  not per unit of volume. Normalizing to energy makes factor application
  consistent across fuel types regardless of physical state (liquid/gas/solid).

References:
  DEFRA 2023 Greenhouse Gas Reporting Conversion Factors
  IPCC AR5 Global Warming Potentials (100-year)
"""

from decimal import Decimal
from typing import Optional
from math import radians, sin, cos, sqrt, atan2


# ── Fuel Energy Densities (Lower Heating Value) ───────────────────────────────
# MJ per liter. LHV is the standard for combustion emission calculations.
# Source: DEFRA 2023, Table 1c; IPCC 2006 Guidelines Vol.2
FUEL_MJ_PER_LITER = {
    "diesel":         Decimal("35.86"),
    "petrol":         Decimal("32.18"),
    "gasoline":       Decimal("32.18"),   # US alias for petrol
    "unleaded":       Decimal("32.18"),
    "lpg":            Decimal("23.40"),
    "natural_gas":    Decimal("34.39"),   # liquid equivalent
    "cng":            Decimal("22.73"),   # compressed natural gas, per liter at STP
    "kerosene":       Decimal("34.37"),
    "aviation_fuel":  Decimal("33.49"),   # Jet-A1 / Jet-A
    "hfo":            Decimal("39.68"),   # heavy fuel oil
    "biodiesel":      Decimal("32.80"),
    "ethanol":        Decimal("21.20"),
    "heating_oil":    Decimal("36.72"),
    "heizöl":         Decimal("36.72"),   # German alias for heating oil
    "kraftstoff":     Decimal("32.18"),   # generic German "fuel" → assume petrol
}

MJ_TO_KWH = Decimal("0.27778")  # exact: 1 MJ = 1/3.6 kWh

# ── Volume Conversions (to liters) ────────────────────────────────────────────
VOLUME_TO_LITERS = {
    # Metric
    "l": Decimal("1"), "L": Decimal("1"),
    "liter": Decimal("1"), "liters": Decimal("1"),
    "Liter": Decimal("1"), "litre": Decimal("1"), "litres": Decimal("1"),
    "ml": Decimal("0.001"), "mL": Decimal("0.001"),
    "m3": Decimal("1000"), "m³": Decimal("1000"),
    "Kubikmeter": Decimal("1000"),   # German: cubic meter
    "dm3": Decimal("1"),             # deciliter = liter
    # Imperial
    "gal": Decimal("3.78541"),       # US gallon
    "gallon": Decimal("3.78541"),
    "UK_gal": Decimal("4.54609"),    # UK/imperial gallon
    "ft3": Decimal("28.3168"),
    "bbl": Decimal("158.987"),       # oil barrel
    # Gas volumes (at STP, approximate)
    "Nm3": Decimal("1000"),          # normal cubic meter ≈ 1000 L
    "scf": Decimal("28.3168"),       # standard cubic foot
}

# ── Mass-to-volume conversions for gaseous fuels (kg → liters at STP) ─────────
# CNG: density ≈ 0.717 kg/m³ at STP → 1 kg = 1/0.000717 L = 1394.7 L
# LNG: density ≈ 450 kg/m³ liquid   → 1 kg = 1/0.450 L   = 2.222 L
# Used when SAP records CNG/LNG by mass rather than volume (common in India/EU).
FUEL_KG_TO_LITERS = {
    "cng":  Decimal("1394.7"),   # compressed natural gas
    "lng":  Decimal("2.222"),    # liquefied natural gas
}

# ── Energy Conversions (to kWh) ───────────────────────────────────────────────
ENERGY_TO_KWH = {
    "kWh": Decimal("1"), "KWH": Decimal("1"), "kwh": Decimal("1"),
    "MWh": Decimal("1000"), "MWH": Decimal("1000"),
    "GWh": Decimal("1000000"),
    "MJ": MJ_TO_KWH,
    "GJ": Decimal("1000") * MJ_TO_KWH,
    "TJ": Decimal("1000000") * MJ_TO_KWH,
    "BTU": Decimal("0.000293071"),
    "MMBTU": Decimal("293.071"),
    "therm": Decimal("29.3071"),
    "kVAh": Decimal("1"),            # approximate, power factor assumed ~1
}

# ── Distance Conversions (to km) ──────────────────────────────────────────────
DISTANCE_TO_KM = {
    "km": Decimal("1"), "KM": Decimal("1"),
    "mi": Decimal("1.60934"), "miles": Decimal("1.60934"), "mile": Decimal("1.60934"),
    "nm": Decimal("1.852"), "NM": Decimal("1.852"),  # nautical miles
}

# ── Airport Coordinates (IATA code → (lat, lon)) ──────────────────────────────
# Expanded to cover routes realistically appearing in enterprise travel data.
# Source: OurAirports dataset (ourairports.com, CC0 license)
AIRPORT_COORDS = {
    # India
    "BOM": (19.0896, 72.8656),   "DEL": (28.5665, 77.1031),
    "BLR": (13.1979, 77.7063),   "MAA": (12.9900, 80.1693),
    "HYD": (17.2313, 78.4298),   "CCU": (22.6547, 88.4467),
    "AMD": (23.0769, 72.6347),   "PNQ": (18.5821, 73.9197),
    "GOI": (15.3808, 73.8314),   "COK": (10.1520, 76.4019),
    "IXC": (30.6735, 76.7885),   "GAU": (26.1061, 91.5859),
    # UK & Ireland
    "LHR": (51.4775, -0.4614),   "LGW": (51.1537, -0.1821),
    "MAN": (53.3537, -2.2750),   "EDI": (55.9500, -3.3725),
    "BHX": (52.4539, -1.7480),   "DUB": (53.4213, -6.2701),
    # Western Europe
    "CDG": (49.0097,  2.5479),   "ORY": (48.7233,  2.3794),
    "AMS": (52.3086,  4.7639),   "FRA": (50.0379,  8.5622),
    "MUC": (48.3538, 11.7861),   "BER": (52.3667, 13.5033),
    "HAM": (53.6304,  9.9882),   "DUS": (51.2895,  6.7668),
    "VIE": (48.1103, 16.5697),   "ZRH": (47.4647,  8.5492),
    "BCN": (41.2971,  2.0785),   "MAD": (40.4936, -3.5668),
    "FCO": (41.8003, 12.2389),   "MXP": (45.6306,  8.7281),
    "CPH": (55.6180, 12.6561),   "ARN": (59.6519, 17.9186),
    "OSL": (60.1939, 11.1004),   "HEL": (60.3172, 24.9633),
    "LIS": (38.7756, -9.1354),   "BRU": (50.9010,  4.4844),
    "WAW": (52.1657, 20.9671),   "PRG": (50.1008, 14.2600),
    # Middle East & Africa
    "DXB": (25.2532, 55.3657),   "AUH": (24.4330, 54.6511),
    "DOH": (25.2731, 51.6080),   "KWI": (29.2267, 47.9689),
    "RUH": (24.9576, 46.6988),   "AMM": (31.7226, 35.9932),
    "CAI": (30.1219, 31.4056),   "NBO": (-1.3192, 36.9275),
    "JNB": (-26.1367, 28.2411),  "CPT": (-33.9715, 18.6021),
    "LOS": (6.5774,  3.3212),    "CMN": (33.3675, -7.5900),
    # Asia Pacific
    "SIN": (1.3644, 103.9915),   "KUL": (2.7456, 101.7099),
    "BKK": (13.6811, 100.7472),  "HKG": (22.3080, 113.9185),
    "PVG": (31.1443, 121.8083),  "PEK": (40.0799, 116.6031),
    "NRT": (35.7720, 140.3929),  "KIX": (34.4274, 135.2440),
    "ICN": (37.4602, 126.4407),  "TPE": (25.0777, 121.2327),
    "SYD": (-33.9461, 151.1772), "MEL": (-37.6690, 144.8410),
    "AKL": (-37.0082, 174.7917), "CGK": (-6.1256, 106.6559),
    "MNL": (14.5086, 121.0194),  "SGN": (10.8188, 106.6519),
    # North America
    "JFK": (40.6413, -73.7781),  "EWR": (40.6895, -74.1745),
    "LGA": (40.7773, -73.8726),  "BOS": (42.3643, -71.0052),
    "ORD": (41.9742, -87.9073),  "MDW": (41.7868, -87.7522),
    "LAX": (33.9425, -118.4081), "SFO": (37.6213, -122.3790),
    "SEA": (47.4502, -122.3088), "DEN": (39.8561, -104.6737),
    "DFW": (32.8998, -97.0403),  "IAH": (29.9902, -95.3368),
    "MIA": (25.7959, -80.2870),  "ATL": (33.6407, -84.4277),
    "YYZ": (43.6772, -79.6306),  "YVR": (49.1967, -123.1815),
    "MEX": (19.4363, -99.0721),  "GRU": (-23.4356, -46.4731),
    "EZE": (-34.8222, -58.5358), "BOG": (4.7016, -74.1469),
    "LIM": (-12.0219, -77.1143), "SCL": (-33.3930, -70.7858),
}


class UnitNormalizationError(Exception):
    pass


def normalize_fuel_volume(quantity: Decimal, unit: str, fuel_type: str) -> dict:
    """
    Normalize a fuel quantity to liters and kWh energy equivalent.

    Returns dict with:
      quantity_liters, quantity_kwh (None if fuel_type unknown),
      canonical_unit, warning (if fuel_type unrecognized)
    """
    unit_clean = unit.strip()
    fuel_lower = fuel_type.lower().strip().replace(" ", "_").replace("-", "_")

    # ── Mass-based units (kg) — only valid for gaseous fuels with known density ──
    if unit_clean == "kg":
        if fuel_lower not in FUEL_KG_TO_LITERS:
            raise UnitNormalizationError(
                f"Unit 'kg' is only supported for gaseous fuels "
                f"({sorted(FUEL_KG_TO_LITERS)}). Got fuel type '{fuel_type}'. "
                f"For liquid fuels, use a volume unit (L, gal, bbl, etc.)."
            )
        liters = quantity * FUEL_KG_TO_LITERS[fuel_lower]
    elif unit_clean not in VOLUME_TO_LITERS:
        raise UnitNormalizationError(
            f"Unknown volume unit '{unit}'. Known: {sorted(VOLUME_TO_LITERS)}"
        )
    else:
        liters = quantity * VOLUME_TO_LITERS[unit_clean]

    if fuel_lower not in FUEL_MJ_PER_LITER:
        return {
            "quantity_liters": liters,
            "quantity_kwh": None,
            "canonical_unit": "L",
            "warning": f"Unknown fuel type '{fuel_type}'; energy equivalent not calculated",
            "fuel_type_recognized": False,
        }

    mj = liters * FUEL_MJ_PER_LITER[fuel_lower]
    return {
        "quantity_liters": liters,
        "quantity_kwh": mj * MJ_TO_KWH,
        "canonical_unit": "L",
        "fuel_type_recognized": True,
    }


def normalize_energy(quantity: Decimal, unit: str) -> Decimal:
    """Normalize any energy unit to kWh."""
    unit_clean = unit.strip()
    if unit_clean not in ENERGY_TO_KWH:
        raise UnitNormalizationError(
            f"Unknown energy unit '{unit}'. Known: {sorted(ENERGY_TO_KWH)}"
        )
    return quantity * ENERGY_TO_KWH[unit_clean]


def normalize_distance(quantity: Decimal, unit: str) -> Decimal:
    """Normalize any distance unit to km."""
    unit_clean = unit.strip()
    if unit_clean not in DISTANCE_TO_KM:
        raise UnitNormalizationError(
            f"Unknown distance unit '{unit}'. Known: {sorted(DISTANCE_TO_KM)}"
        )
    return quantity * DISTANCE_TO_KM[unit_clean]


def estimate_flight_distance_km(origin: str, destination: str) -> Optional[Decimal]:
    """
    Estimate great-circle distance between two IATA airport codes using the
    Haversine formula. Returns None if either code is not in our lookup table.

    Coverage: ~100 airports across India, Europe, Middle East, Asia Pacific,
    and North America. See AIRPORT_COORDS for the full list.

    For unknown airports, the caller should raise UNKNOWN_AIRPORT flag
    rather than silently omitting the distance.
    """
    o = origin.upper().strip()
    d = destination.upper().strip()

    if o not in AIRPORT_COORDS or d not in AIRPORT_COORDS:
        return None  # Caller must flag this — not a silent failure

    R = 6371  # Earth mean radius, km
    lat1, lon1 = (radians(x) for x in AIRPORT_COORDS[o])
    lat2, lon2 = (radians(x) for x in AIRPORT_COORDS[d])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return Decimal(str(round(R * 2 * atan2(sqrt(a), sqrt(1 - a)), 2)))


def known_fuel_types() -> set:
    """Return the set of recognized fuel type keys for flag checks."""
    return set(FUEL_MJ_PER_LITER.keys())