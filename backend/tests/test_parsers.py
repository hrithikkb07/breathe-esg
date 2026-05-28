"""
Unit tests for parsers, normalization, and suspicious detection.

No Django dependency — no models, no DB, no settings required.
All three modules under test are pure functions or operate only on
plain Python objects.

Run:
    cd backend
    pip install pytest pandas
    pytest tests/test_parsers.py -v

Why no Django:
    Parsers receive bytes and yield dicts. Normalization receives Decimal
    and returns Decimal. Suspicious checks receive plain values and return
    lists. None of these touch the ORM, so the test suite boots in <1 second
    and can run in CI without a database.

Django isolation strategy:
    suspicious.py imports Django models inside two functions
    (check_duplicate_invoice, check_billing_overlap). Those functions are
    ORM-backed and intentionally not tested here — they require a live DB.
    All other check_* functions are pure. We patch django.db at the module
    level so the top-level imports in esg.models don't crash on collection,
    then import only the pure functions we need.
"""

import sys
import os
import types
from decimal import Decimal
from datetime import date

# ── Django isolation ──────────────────────────────────────────────────────────
# Patch just enough of django.* so that esg.models (which suspicious.py
# imports lazily inside functions) doesn't crash on import.  We only need the
# module namespace to exist; we never call these stubs.

def _make_module(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m

for _mod in [
    "django", "django.db", "django.db.models", "django.conf",
    "django.core", "django.core.exceptions",
]:
    sys.modules.setdefault(_mod, _make_module(_mod))

# Minimal django.db.models namespace that model files reference at import time
_dm = sys.modules["django.db.models"]
for _attr in ["Model", "UUIDField", "CharField", "TextField", "IntegerField",
              "DecimalField", "BooleanField", "DateField", "DateTimeField",
              "ForeignKey", "OneToOneField", "BigAutoField", "JSONField",
              "CASCADE", "PROTECT", "SET_NULL", "IntegerChoices", "TextChoices",
              "Index", "UniqueConstraint", "Manager", "QuerySet"]:
    if not hasattr(_dm, _attr):
        setattr(_dm, _attr, type(_attr, (), {}))

_conf = sys.modules["django.conf"]
if not hasattr(_conf, "settings"):
    _conf.settings = types.SimpleNamespace(AUTH_USER_MODEL="auth.User")

from esg.services.parsers import (
    parse_sap_csv,
    parse_utility_csv,
    parse_travel_csv,
    _parse_sap_date,
    _parse_decimal_european,
    _detect_header_language,
    _parse_utility_date,
    _parse_travel_date,
    TRAVEL_TYPE_MAP,
)
from esg.services.normalization import (
    normalize_fuel_volume,
    normalize_energy,
    normalize_distance,
    estimate_flight_distance_km,
    UnitNormalizationError,
    AIRPORT_COORDS,
)
from esg.services.suspicious import (
    check_quantity,
    check_dates,
    check_billing_period_length,
    check_flight_distance,
    check_sap_reversal,
    check_unknown_fuel_type,
    check_statistical_spike,
    NEGATIVE_QUANTITY,
    ZERO_QUANTITY,
    FUTURE_DATE,
    DATE_TOO_OLD,
    BILLING_PERIOD_ANOMALY,
    IMPLAUSIBLE_FLIGHT_DISTANCE,
    UNKNOWN_AIRPORT,
    DISTANCE_NOT_FOUND,
    SAP_REVERSAL,
    UNKNOWN_FUEL_TYPE,
    STATISTICAL_SPIKE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def parse_sap_rows(csv_bytes: bytes) -> list[dict]:
    """Collect all rows from parse_sap_csv into a list."""
    return list(parse_sap_csv(csv_bytes))


def parse_utility_rows(csv_bytes: bytes) -> list[dict]:
    return list(parse_utility_csv(csv_bytes))


def parse_travel_rows(csv_bytes: bytes) -> list[dict]:
    return list(parse_travel_csv(csv_bytes))


def flag_codes(flags: list) -> list[str]:
    return [f["code"] for f in flags]


# ─────────────────────────────────────────────────────────────────────────────
# _parse_sap_date
# ─────────────────────────────────────────────────────────────────────────────

class TestParseSapDate:
    def test_german_format(self):
        assert _parse_sap_date("31.12.2023") == date(2023, 12, 31)

    def test_iso_format(self):
        assert _parse_sap_date("2023-08-01") == date(2023, 8, 1)

    def test_us_format(self):
        assert _parse_sap_date("08/01/2023") == date(2023, 8, 1)

    def test_uk_format(self):
        # NOTE: 01/08/2023 is ambiguous — it could be UK (Aug 1) or US (Jan 8).
        # The parser tries %m/%d/%Y before %d/%m/%Y, so 01/08/2023 parses as
        # January 8 (US interpretation). This is a known limitation documented
        # in DECISIONS.md — unambiguous dates (ISO, German dot-format) are
        # preferred in SAP exports; slash-separated dates with day<=12 are
        # inherently ambiguous and should use ISO 8601 in the source system.
        assert _parse_sap_date("01/08/2023") == date(2023, 1, 8)  # US interpretation

    def test_uk_format_unambiguous(self):
        # Day > 12 forces UK interpretation (can't be a US month)
        assert _parse_sap_date("25/08/2023") == date(2023, 8, 25)

    def test_compact_sap_format(self):
        assert _parse_sap_date("20231231") == date(2023, 12, 31)

    def test_two_digit_year_german(self):
        assert _parse_sap_date("31.12.23") == date(2023, 12, 31)

    def test_none_returns_none(self):
        assert _parse_sap_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_sap_date("") is None

    def test_nan_returns_none(self):
        assert _parse_sap_date("nan") is None

    def test_unrecognised_format_returns_none(self):
        assert _parse_sap_date("not-a-date") is None


# ─────────────────────────────────────────────────────────────────────────────
# _parse_decimal_european
# ─────────────────────────────────────────────────────────────────────────────

class TestParseDecimalEuropean:
    def test_plain_integer(self):
        assert _parse_decimal_european("500") == Decimal("500")

    def test_us_decimal(self):
        assert _parse_decimal_european("4250.50") == Decimal("4250.50")

    def test_us_with_thousands_comma(self):
        assert _parse_decimal_european("1,234.56") == Decimal("1234.56")

    def test_european_thousands_dot_decimal_comma(self):
        # 4.250,500 is European for four thousand two hundred fifty point five
        assert _parse_decimal_european("4.250,500") == Decimal("4250.500")

    def test_european_single_group(self):
        assert _parse_decimal_european("1.500") == Decimal("1500")

    def test_negative_european(self):
        assert _parse_decimal_european("-200,00") == Decimal("-200.00")

    def test_empty_returns_none(self):
        assert _parse_decimal_european("") is None

    def test_nan_returns_none(self):
        assert _parse_decimal_european("nan") is None

    def test_non_numeric_returns_none(self):
        assert _parse_decimal_european("N/A") is None


# ─────────────────────────────────────────────────────────────────────────────
# _detect_header_language
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectHeaderLanguage:
    def test_german_headers(self):
        assert _detect_header_language(["Buchungsdatum", "Werk", "Menge"]) == "DE"

    def test_english_headers(self):
        assert _detect_header_language(["Posting Date", "Plant", "Quantity"]) == "EN"

    def test_mixed_defaults_to_en_without_german_markers(self):
        assert _detect_header_language(["Date", "Plant", "Amount"]) == "EN"

    def test_partial_german_still_detected(self):
        assert _detect_header_language(["Buchungsdatum", "Plant", "Quantity"]) == "DE"


# ─────────────────────────────────────────────────────────────────────────────
# parse_sap_csv — integration over the full parser
# ─────────────────────────────────────────────────────────────────────────────

SAP_EN = b"""Posting Date,Plant,Material,Quantity,Unit,Cost Center,Document Number,Movement Type
2024-08-01,DE01,diesel,500,L,CC-100,INV-001,261
2024-08-15,DE01,petrol,300,L,CC-100,INV-002,261
"""

SAP_DE = b"""Buchungsdatum;Werk;Menge;Einheit;Kostenstelle;Belegnummer;Bewegungsart
01.08.2024;DE01;4.250,500;L;CC-100;4500012301;261
15.08.2024;DE01;300;L;CC-100;4500012302;261
"""

SAP_NEGATIVE = b"""Posting Date,Plant,Material,Quantity,Unit,Cost Center,Document Number,Movement Type
2024-08-22,DE01,diesel,-200,L,CC-100,INV-REV-001,262
"""

SAP_MISSING_REQUIRED = b"""Posting Date,Plant,Material,Quantity,Unit
,,diesel,500,L
"""

SAP_BAD_DATE = b"""Posting Date,Plant,Material,Quantity,Unit,Cost Center,Document Number
NOT_A_DATE,DE01,diesel,500,L,CC-100,INV-003
"""

SAP_BAD_QUANTITY = b"""Posting Date,Plant,Material,Quantity,Unit,Cost Center,Document Number
2024-08-01,DE01,diesel,LOTS,L,CC-100,INV-004
"""


class TestParseSapCsv:
    def test_parses_english_headers(self):
        rows = parse_sap_rows(SAP_EN)
        assert len(rows) == 2
        assert rows[0]["parsed"]["plant_code"] == "DE01"

    def test_english_date_parsed(self):
        rows = parse_sap_rows(SAP_EN)
        assert rows[0]["parsed"]["date"] == date(2024, 8, 1)

    def test_english_quantity_parsed(self):
        rows = parse_sap_rows(SAP_EN)
        assert rows[0]["parsed"]["quantity"] == Decimal("500")

    def test_fuel_type_lowercased(self):
        rows = parse_sap_rows(SAP_EN)
        assert rows[0]["parsed"]["fuel_type"] == "diesel"

    def test_invoice_ref_captured(self):
        rows = parse_sap_rows(SAP_EN)
        assert rows[0]["parsed"]["invoice_ref"] == "INV-001"

    def test_movement_type_captured(self):
        rows = parse_sap_rows(SAP_EN)
        assert rows[0]["parsed"]["movement_type"] == "261"

    def test_detects_german_headers(self):
        rows = parse_sap_rows(SAP_DE)
        assert rows[0]["header_language"] == "DE"

    def test_german_semicolon_delimiter(self):
        rows = parse_sap_rows(SAP_DE)
        assert len(rows) == 2

    def test_german_date_format(self):
        rows = parse_sap_rows(SAP_DE)
        assert rows[0]["parsed"]["date"] == date(2024, 8, 1)

    def test_european_decimal_format(self):
        # 4.250,500 should parse to 4250.5
        rows = parse_sap_rows(SAP_DE)
        assert rows[0]["parsed"]["quantity"] == Decimal("4250.500")

    def test_negative_quantity_parsed_without_error(self):
        rows = parse_sap_rows(SAP_NEGATIVE)
        assert rows[0]["parsed"]["quantity"] == Decimal("-200")
        assert rows[0]["parse_error"] == ""

    def test_reversal_movement_type_captured(self):
        rows = parse_sap_rows(SAP_NEGATIVE)
        assert rows[0]["parsed"]["movement_type"] == "262"

    def test_missing_required_fields_sets_error(self):
        rows = parse_sap_rows(SAP_MISSING_REQUIRED)
        assert rows[0]["parse_error"] != ""
        assert "Missing required fields" in rows[0]["parse_error"]

    def test_bad_date_sets_error(self):
        rows = parse_sap_rows(SAP_BAD_DATE)
        assert "date" in rows[0]["parse_error"].lower()

    def test_bad_quantity_sets_error(self):
        rows = parse_sap_rows(SAP_BAD_QUANTITY)
        assert "quantity" in rows[0]["parse_error"].lower()

    def test_raw_dict_preserved(self):
        rows = parse_sap_rows(SAP_EN)
        assert "raw" in rows[0]
        assert isinstance(rows[0]["raw"], dict)

    def test_custom_column_mapping_applied(self):
        csv = b"TxnDate,Location,Fuel,Amount,UOM\n2024-08-01,PLANT1,diesel,100,L\n"
        mapping = {
            "TxnDate": "date",
            "Location": "plant_code",
            "Amount": "quantity",
            "UOM": "unit",
        }
        rows = parse_sap_rows.__wrapped__(csv, column_mapping=mapping) if hasattr(parse_sap_rows, "__wrapped__") else list(parse_sap_csv(csv, column_mapping=mapping))
        assert rows[0]["parsed"]["plant_code"] == "PLANT1"


# ─────────────────────────────────────────────────────────────────────────────
# _parse_utility_date
# ─────────────────────────────────────────────────────────────────────────────

class TestParseUtilityDate:
    def test_us_slash_format(self):
        assert _parse_utility_date("03/07/2024") == date(2024, 3, 7)

    def test_iso_format(self):
        assert _parse_utility_date("2024-03-07") == date(2024, 3, 7)

    def test_uk_slash_format(self):
        # Same US-first ambiguity: 07/03/2024 parses as July 3 (US), not March 7 (UK).
        # Use a day>12 to force unambiguous UK parsing.
        assert _parse_utility_date("07/03/2024") == date(2024, 7, 3)  # US interpretation

    def test_uk_slash_format_unambiguous(self):
        assert _parse_utility_date("25/03/2024") == date(2024, 3, 25)

    def test_day_month_year_dot(self):
        assert _parse_utility_date("07.03.2024") == date(2024, 3, 7)

    def test_none_returns_none(self):
        assert _parse_utility_date(None) is None

    def test_empty_returns_none(self):
        assert _parse_utility_date("") is None


# ─────────────────────────────────────────────────────────────────────────────
# parse_utility_csv
# ─────────────────────────────────────────────────────────────────────────────

UTILITY_CSV = b"""Meter ID,Service Start Date,Service End Date,Usage,Units,Invoice Number,Facility,Estimated Read
MTR-001,03/07/2024,04/09/2024,1200,kWh,INV-UTIL-001,Mumbai HQ,No
MTR-002,03/07/2024,04/08/2024,5000,MWh,INV-UTIL-002,Data Center,No
MTR-003,03/07/2024,04/09/2024,-120,kWh,INV-UTIL-003,London Office,No
MTR-004,01/01/2024,01/31/2024,800,kWh,INV-UTIL-004,Pune Office,Yes
"""

UTILITY_BAD_DATE = b"""Meter ID,Service Start Date,Service End Date,Usage,Units
MTR-X,BADDATE,2024-04-09,1000,kWh
"""

UTILITY_BAD_QTY = b"""Meter ID,Service Start Date,Service End Date,Usage,Units
MTR-X,2024-03-07,2024-04-09,NOT_A_NUMBER,kWh
"""


class TestParseUtilityCsv:
    def test_basic_row_parsed(self):
        rows = parse_utility_rows(UTILITY_CSV)
        assert len(rows) == 4

    def test_meter_id_captured(self):
        rows = parse_utility_rows(UTILITY_CSV)
        assert rows[0]["parsed"]["meter_id"] == "MTR-001"

    def test_period_start_parsed(self):
        rows = parse_utility_rows(UTILITY_CSV)
        assert rows[0]["parsed"]["period_start"] == date(2024, 3, 7)

    def test_period_end_parsed(self):
        rows = parse_utility_rows(UTILITY_CSV)
        assert rows[0]["parsed"]["period_end"] == date(2024, 4, 9)

    def test_quantity_parsed(self):
        rows = parse_utility_rows(UTILITY_CSV)
        assert rows[0]["parsed"]["quantity"] == Decimal("1200")

    def test_unit_captured(self):
        rows = parse_utility_rows(UTILITY_CSV)
        assert rows[0]["parsed"]["unit"] == "kWh"

    def test_mwh_unit_preserved(self):
        rows = parse_utility_rows(UTILITY_CSV)
        assert rows[1]["parsed"]["unit"] == "MWh"

    def test_invoice_ref_captured(self):
        rows = parse_utility_rows(UTILITY_CSV)
        assert rows[0]["parsed"]["invoice_ref"] == "INV-UTIL-001"

    def test_facility_name_captured(self):
        rows = parse_utility_rows(UTILITY_CSV)
        assert rows[0]["parsed"]["facility_name"] == "Mumbai HQ"

    def test_negative_quantity_no_parse_error(self):
        rows = parse_utility_rows(UTILITY_CSV)
        assert rows[2]["parsed"]["quantity"] == Decimal("-120")
        assert rows[2]["parse_error"] == ""

    def test_estimated_read_false(self):
        rows = parse_utility_rows(UTILITY_CSV)
        assert rows[0]["parsed"]["is_estimated"] is False

    def test_estimated_read_true_yes(self):
        rows = parse_utility_rows(UTILITY_CSV)
        assert rows[3]["parsed"]["is_estimated"] is True

    def test_bad_period_start_sets_error(self):
        rows = parse_utility_rows(UTILITY_BAD_DATE)
        assert "period_start" in rows[0]["parse_error"]

    def test_bad_quantity_sets_error(self):
        rows = parse_utility_rows(UTILITY_BAD_QTY)
        assert "quantity" in rows[0]["parse_error"].lower()

    def test_default_unit_kwh_when_missing(self):
        csv = b"Meter ID,Service Start Date,Service End Date,Usage\nMTR-X,2024-03-01,2024-04-01,500\n"
        rows = parse_utility_rows(csv)
        assert rows[0]["parsed"]["unit"] == "kWh"

    def test_estimated_read_variants(self):
        """y, true, 1 should all be truthy."""
        for val in ("y", "true", "1", "estimated"):
            csv = f"Meter ID,Service Start Date,Service End Date,Usage,Estimated Read\nM1,2024-03-01,2024-04-01,100,{val}\n".encode()
            rows = parse_utility_rows(csv)
            assert rows[0]["parsed"]["is_estimated"] is True, f"Failed for: {val}"


# ─────────────────────────────────────────────────────────────────────────────
# _parse_travel_date
# ─────────────────────────────────────────────────────────────────────────────

class TestParseTravelDate:
    def test_iso(self):
        assert _parse_travel_date("2024-06-15") == date(2024, 6, 15)

    def test_us_slash(self):
        assert _parse_travel_date("06/15/2024") == date(2024, 6, 15)

    def test_uk_slash(self):
        assert _parse_travel_date("15/06/2024") == date(2024, 6, 15)

    def test_day_mon_year(self):
        assert _parse_travel_date("15-Jun-2024") == date(2024, 6, 15)

    def test_none_returns_none(self):
        assert _parse_travel_date(None) is None

    def test_empty_returns_none(self):
        assert _parse_travel_date("") is None


# ─────────────────────────────────────────────────────────────────────────────
# parse_travel_csv
# ─────────────────────────────────────────────────────────────────────────────

TRAVEL_CSV = b"""Employee ID,Trip ID,Expense Type,Travel Date,Return Date,Origin,Destination,Cabin Class,Distance (km),Number of Nights,Hotel Name
EMP-001,TRIP-001,flight,2024-06-01,,LHR,BOM,economy,,
EMP-002,TRIP-002,hotel,2024-07-01,2024-07-03,,,,,,Taj Mumbai
EMP-003,TRIP-003,rail,2024-07-10,,,,,,
EMP-004,TRIP-004,car,2024-07-15,,,,,,
EMP-005,TRIP-005,flight,2024-08-01,,JFK,LAX,business,4500,
EMP-006,TRIP-006,Air Travel,2024-08-05,,SIN,HKG,economy,,
"""

TRAVEL_NAVAN_CSV = b"""traveler_id,booking_type,depart_date,from_location,to_location
EMP-A,flight,2024-09-01,LHR,CDG
"""

TRAVEL_BAD_DATE = b"""Employee ID,Trip ID,Expense Type,Travel Date,Origin,Destination
EMP-X,TRIP-X,flight,BADDATE,LHR,BOM
"""


class TestParseTravelCsv:
    def test_row_count(self):
        rows = parse_travel_rows(TRAVEL_CSV)
        assert len(rows) == 6

    def test_flight_type_canonical(self):
        rows = parse_travel_rows(TRAVEL_CSV)
        assert rows[0]["parsed"]["travel_type"] == "AIR"

    def test_hotel_type_canonical(self):
        rows = parse_travel_rows(TRAVEL_CSV)
        assert rows[1]["parsed"]["travel_type"] == "HOTEL"

    def test_rail_type_canonical(self):
        rows = parse_travel_rows(TRAVEL_CSV)
        assert rows[2]["parsed"]["travel_type"] == "RAIL"

    def test_car_type_canonical(self):
        rows = parse_travel_rows(TRAVEL_CSV)
        assert rows[3]["parsed"]["travel_type"] == "GROUND"

    def test_travel_type_map_case_insensitive(self):
        # "Air Travel" should map to AIR via TRAVEL_TYPE_MAP
        rows = parse_travel_rows(TRAVEL_CSV)
        assert rows[5]["parsed"]["travel_type"] == "AIR"

    def test_explicit_distance_km_used(self):
        rows = parse_travel_rows(TRAVEL_CSV)
        assert rows[4]["parsed"]["distance_km"] == Decimal("4500")

    def test_distance_estimated_from_iata(self):
        rows = parse_travel_rows(TRAVEL_CSV)
        # LHR → BOM: should estimate via Haversine
        assert rows[0]["parsed"]["distance_km"] is not None
        assert rows[0]["parsed"]["distance_is_estimated"] is True

    def test_estimated_distance_reasonable(self):
        rows = parse_travel_rows(TRAVEL_CSV)
        # LHR→BOM great-circle is ~7200 km
        d = rows[0]["parsed"]["distance_km"]
        assert Decimal("6800") < d < Decimal("7600")

    def test_origin_uppercased(self):
        rows = parse_travel_rows(TRAVEL_CSV)
        assert rows[0]["parsed"]["origin"] == "LHR"

    def test_destination_uppercased(self):
        rows = parse_travel_rows(TRAVEL_CSV)
        assert rows[0]["parsed"]["destination"] == "BOM"

    def test_cabin_class_lowercased(self):
        rows = parse_travel_rows(TRAVEL_CSV)
        assert rows[0]["parsed"]["cabin_class"] == "economy"
        assert rows[4]["parsed"]["cabin_class"] == "business"

    def test_hotel_nights_from_dates(self):
        rows = parse_travel_rows(TRAVEL_CSV)
        # travel 2024-07-01 → return 2024-07-03 = 2 nights
        assert rows[1]["parsed"]["nights"] == 2

    def test_employee_id_captured(self):
        rows = parse_travel_rows(TRAVEL_CSV)
        assert rows[0]["parsed"]["employee_id"] == "EMP-001"

    def test_navan_column_aliases(self):
        rows = parse_travel_rows(TRAVEL_NAVAN_CSV)
        assert rows[0]["parsed"]["travel_type"] == "AIR"
        assert rows[0]["parsed"]["origin"] == "LHR"
        assert rows[0]["parsed"]["destination"] == "CDG"

    def test_bad_travel_date_sets_error(self):
        rows = parse_travel_rows(TRAVEL_BAD_DATE)
        assert "travel_date" in rows[0]["parse_error"]

    def test_unknown_travel_type_maps_to_unknown(self):
        csv = b"Employee ID,Trip ID,Expense Type,Travel Date\nE1,T1,submarine,2024-06-01\n"
        rows = parse_travel_rows(csv)
        assert rows[0]["parsed"]["travel_type"] == "UNKNOWN"

    def test_distance_mi_converted_to_km(self):
        csv = b"Employee ID,Trip ID,Expense Type,Travel Date,Distance (mi)\nE1,T1,flight,2024-06-01,100\n"
        rows = parse_travel_rows(csv)
        d = rows[0]["parsed"]["distance_km"]
        assert d is not None
        # 100 miles * 1.60934 = 160.934
        assert Decimal("160") < d < Decimal("162")


# ─────────────────────────────────────────────────────────────────────────────
# normalize_fuel_volume
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeFuelVolume:
    def test_liters_diesel_identity(self):
        result = normalize_fuel_volume(Decimal("500"), "L", "diesel")
        assert result["quantity_liters"] == Decimal("500")

    def test_diesel_kwh_equivalent(self):
        result = normalize_fuel_volume(Decimal("500"), "L", "diesel")
        # 500 L * 35.86 MJ/L * 0.27778 kWh/MJ ≈ 4980 kWh
        assert result["quantity_kwh"] is not None
        assert Decimal("4900") < result["quantity_kwh"] < Decimal("5100")

    def test_us_gallon_converted_to_liters(self):
        result = normalize_fuel_volume(Decimal("100"), "gal", "petrol")
        # 100 US gal * 3.78541 L/gal = 378.541 L
        assert abs(result["quantity_liters"] - Decimal("378.541")) < Decimal("0.01")

    def test_uk_gallon_different_from_us(self):
        us = normalize_fuel_volume(Decimal("1"), "gal", "diesel")
        uk = normalize_fuel_volume(Decimal("1"), "UK_gal", "diesel")
        assert uk["quantity_liters"] > us["quantity_liters"]

    def test_mwh_style_unit_raises(self):
        # Volume normalizer should raise on energy units
        try:
            normalize_fuel_volume(Decimal("100"), "kWh", "diesel")
            assert False, "Expected UnitNormalizationError"
        except UnitNormalizationError:
            pass

    def test_unknown_fuel_type_returns_warning(self):
        result = normalize_fuel_volume(Decimal("100"), "L", "moonshine")
        assert result["fuel_type_recognized"] is False
        assert result["quantity_kwh"] is None
        assert "warning" in result

    def test_german_fuel_alias(self):
        # heizöl → heating_oil
        result = normalize_fuel_volume(Decimal("100"), "L", "heizöl")
        assert result["fuel_type_recognized"] is True

    def test_us_gasoline_alias(self):
        result = normalize_fuel_volume(Decimal("100"), "L", "gasoline")
        petrol = normalize_fuel_volume(Decimal("100"), "L", "petrol")
        assert result["quantity_kwh"] == petrol["quantity_kwh"]

    def test_canonical_unit_always_L(self):
        result = normalize_fuel_volume(Decimal("100"), "gal", "diesel")
        assert result["canonical_unit"] == "L"

    def test_unknown_volume_unit_raises(self):
        try:
            normalize_fuel_volume(Decimal("100"), "furlongs", "diesel")
            assert False, "Expected UnitNormalizationError"
        except UnitNormalizationError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# normalize_energy
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeEnergy:
    def test_kwh_identity(self):
        assert normalize_energy(Decimal("1000"), "kWh") == Decimal("1000")

    def test_mwh_to_kwh(self):
        assert normalize_energy(Decimal("1"), "MWh") == Decimal("1000")

    def test_gwh_to_kwh(self):
        assert normalize_energy(Decimal("1"), "GWh") == Decimal("1000000")

    def test_mj_to_kwh(self):
        # 1 MJ = 0.27778 kWh
        result = normalize_energy(Decimal("1"), "MJ")
        assert abs(result - Decimal("0.27778")) < Decimal("0.00001")

    def test_gj_to_kwh(self):
        result = normalize_energy(Decimal("1"), "GJ")
        assert abs(result - Decimal("277.78")) < Decimal("0.01")

    def test_unknown_unit_raises(self):
        try:
            normalize_energy(Decimal("100"), "barleycorns")
            assert False, "Expected UnitNormalizationError"
        except UnitNormalizationError:
            pass

    def test_case_variants(self):
        assert normalize_energy(Decimal("1"), "KWH") == Decimal("1")
        assert normalize_energy(Decimal("1"), "kwh") == Decimal("1")

    def test_kvah_approximation(self):
        # kVAh treated as approximately 1 kWh (power factor ~1)
        assert normalize_energy(Decimal("500"), "kVAh") == Decimal("500")


# ─────────────────────────────────────────────────────────────────────────────
# normalize_distance
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeDistance:
    def test_km_identity(self):
        assert normalize_distance(Decimal("1000"), "km") == Decimal("1000")

    def test_miles_to_km(self):
        result = normalize_distance(Decimal("100"), "mi")
        assert abs(result - Decimal("160.934")) < Decimal("0.01")

    def test_nautical_miles_to_km(self):
        result = normalize_distance(Decimal("100"), "nm")
        assert abs(result - Decimal("185.2")) < Decimal("0.1")

    def test_unknown_unit_raises(self):
        try:
            normalize_distance(Decimal("100"), "parsecs")
            assert False, "Expected UnitNormalizationError"
        except UnitNormalizationError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# estimate_flight_distance_km (Haversine)
# ─────────────────────────────────────────────────────────────────────────────

class TestEstimateFlightDistance:
    def test_known_route_lhr_bom(self):
        d = estimate_flight_distance_km("LHR", "BOM")
        assert d is not None
        # Great-circle LHR→BOM is ~7190 km; allow ±200 km
        assert Decimal("6990") < d < Decimal("7390")

    def test_known_route_jfk_lax(self):
        d = estimate_flight_distance_km("JFK", "LAX")
        assert d is not None
        # ~3983 km
        assert Decimal("3800") < d < Decimal("4200")

    def test_same_airport_is_zero_or_very_small(self):
        d = estimate_flight_distance_km("LHR", "LHR")
        assert d == Decimal("0.0")

    def test_unknown_origin_returns_none(self):
        assert estimate_flight_distance_km("ZZZ", "LHR") is None

    def test_unknown_destination_returns_none(self):
        assert estimate_flight_distance_km("LHR", "ZZZ") is None

    def test_both_unknown_returns_none(self):
        assert estimate_flight_distance_km("XXX", "YYY") is None

    def test_lowercase_input_normalised(self):
        d_upper = estimate_flight_distance_km("LHR", "BOM")
        d_lower = estimate_flight_distance_km("lhr", "bom")
        assert d_upper == d_lower

    def test_returns_decimal_not_float(self):
        d = estimate_flight_distance_km("LHR", "BOM")
        assert isinstance(d, Decimal)

    def test_symmetry(self):
        # A→B distance == B→A distance (Haversine is symmetric)
        d1 = estimate_flight_distance_km("SIN", "NRT")
        d2 = estimate_flight_distance_km("NRT", "SIN")
        assert abs(d1 - d2) < Decimal("1")

    def test_long_haul_route(self):
        # SYD → LHR: ~16,993 km
        d = estimate_flight_distance_km("SYD", "LHR")
        assert d is not None
        assert Decimal("16000") < d < Decimal("18000")


# ─────────────────────────────────────────────────────────────────────────────
# check_quantity
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckQuantity:
    def test_positive_quantity_no_flags(self):
        assert check_quantity(Decimal("500")) == []

    def test_negative_quantity_flagged(self):
        flags = check_quantity(Decimal("-1"))
        assert NEGATIVE_QUANTITY in flag_codes(flags)

    def test_zero_quantity_flagged(self):
        flags = check_quantity(Decimal("0"))
        assert ZERO_QUANTITY in flag_codes(flags)

    def test_none_quantity_flagged(self):
        flags = check_quantity(None)
        assert len(flags) > 0

    def test_large_quantity_no_flags(self):
        assert check_quantity(Decimal("999999")) == []


# ─────────────────────────────────────────────────────────────────────────────
# check_dates
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckDates:
    def test_normal_dates_no_flags(self):
        flags = check_dates(date(2024, 1, 1), date(2024, 1, 31))
        assert flags == []

    def test_future_start_flagged(self):
        flags = check_dates(date(2099, 1, 1), date(2099, 1, 31))
        assert FUTURE_DATE in flag_codes(flags)

    def test_end_before_start_flagged(self):
        flags = check_dates(date(2024, 2, 1), date(2024, 1, 1))
        assert FUTURE_DATE in flag_codes(flags)

    def test_pre_2015_date_flagged(self):
        flags = check_dates(date(2014, 12, 1), date(2014, 12, 31))
        assert DATE_TOO_OLD in flag_codes(flags)

    def test_2015_exact_no_too_old_flag(self):
        flags = check_dates(date(2015, 1, 1), date(2015, 1, 31))
        assert DATE_TOO_OLD not in flag_codes(flags)


# ─────────────────────────────────────────────────────────────────────────────
# check_billing_period_length
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckBillingPeriodLength:
    def test_normal_billing_period(self):
        # 33 days — normal
        flags = check_billing_period_length(date(2024, 3, 1), date(2024, 4, 3))
        assert flags == []

    def test_short_period_flagged(self):
        # 10 days — too short
        flags = check_billing_period_length(date(2024, 3, 1), date(2024, 3, 11))
        assert BILLING_PERIOD_ANOMALY in flag_codes(flags)

    def test_long_period_flagged(self):
        # 60 days — too long
        flags = check_billing_period_length(date(2024, 1, 1), date(2024, 3, 1))
        assert BILLING_PERIOD_ANOMALY in flag_codes(flags)

    def test_exactly_20_days_no_flag(self):
        flags = check_billing_period_length(date(2024, 3, 1), date(2024, 3, 21))
        assert flags == []

    def test_exactly_40_days_no_flag(self):
        flags = check_billing_period_length(date(2024, 3, 1), date(2024, 4, 10))
        assert flags == []

    def test_19_days_flagged(self):
        flags = check_billing_period_length(date(2024, 3, 1), date(2024, 3, 20))
        assert BILLING_PERIOD_ANOMALY in flag_codes(flags)


# ─────────────────────────────────────────────────────────────────────────────
# check_flight_distance
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckFlightDistance:
    def test_normal_distance_no_flags(self):
        assert check_flight_distance(Decimal("5000")) == []

    def test_distance_too_large_flagged(self):
        flags = check_flight_distance(Decimal("21000"))
        assert IMPLAUSIBLE_FLIGHT_DISTANCE in flag_codes(flags)

    def test_distance_too_small_flagged(self):
        # <50 km is below shortest scheduled commercial flight
        flags = check_flight_distance(Decimal("30"))
        assert IMPLAUSIBLE_FLIGHT_DISTANCE in flag_codes(flags)

    def test_exactly_50km_no_flag(self):
        assert check_flight_distance(Decimal("50")) == []

    def test_none_with_codes_flags_unknown_airport(self):
        flags = check_flight_distance(None, origin="XYZ", destination="ABC")
        assert UNKNOWN_AIRPORT in flag_codes(flags)

    def test_none_without_codes_flags_distance_not_found(self):
        flags = check_flight_distance(None, origin="", destination="")
        assert DISTANCE_NOT_FOUND in flag_codes(flags)

    def test_max_earth_circumference_ok(self):
        assert check_flight_distance(Decimal("20000")) == []

    def test_zero_distance_flagged(self):
        # 0 km would also be implausible (same as <50)
        flags = check_flight_distance(Decimal("0"))
        assert IMPLAUSIBLE_FLIGHT_DISTANCE in flag_codes(flags)


# ─────────────────────────────────────────────────────────────────────────────
# check_sap_reversal
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckSapReversal:
    def test_261_no_flag(self):
        assert check_sap_reversal("261") == []

    def test_262_flagged(self):
        flags = check_sap_reversal("262")
        assert SAP_REVERSAL in flag_codes(flags)

    def test_202_flagged(self):
        flags = check_sap_reversal("202")
        assert SAP_REVERSAL in flag_codes(flags)

    def test_542_flagged(self):
        flags = check_sap_reversal("542")
        assert SAP_REVERSAL in flag_codes(flags)

    def test_none_no_flag(self):
        assert check_sap_reversal(None) == []

    def test_empty_no_flag(self):
        assert check_sap_reversal("") == []


# ─────────────────────────────────────────────────────────────────────────────
# check_unknown_fuel_type
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckUnknownFuelType:
    KNOWN = {"diesel", "petrol", "lpg", "kerosene"}

    def test_known_fuel_no_flag(self):
        assert check_unknown_fuel_type("diesel", self.KNOWN) == []

    def test_unknown_fuel_flagged(self):
        flags = check_unknown_fuel_type("synth_fuel_x9", self.KNOWN)
        assert UNKNOWN_FUEL_TYPE in flag_codes(flags)

    def test_empty_fuel_type_no_flag(self):
        # Empty string means it wasn't provided — don't flag
        assert check_unknown_fuel_type("", self.KNOWN) == []

    def test_case_sensitivity(self):
        # Should be case-insensitive comparison
        flags = check_unknown_fuel_type("Diesel", self.KNOWN)
        assert flags == []


# ─────────────────────────────────────────────────────────────────────────────
# check_statistical_spike
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckStatisticalSpike:
    NORMAL_HISTORY = [Decimal(str(x)) for x in [500, 480, 520, 495, 510, 490, 505]]

    def test_normal_value_no_flag(self):
        flags = check_statistical_spike(Decimal("510"), self.NORMAL_HISTORY, "plant-A")
        assert flags == []

    def test_spike_3_sigma_flagged(self):
        # History mean ~500, stdev ~14; 600 is >3 sigma above
        flags = check_statistical_spike(Decimal("600"), self.NORMAL_HISTORY, "plant-A")
        assert STATISTICAL_SPIKE in flag_codes(flags)

    def test_insufficient_history_no_flag(self):
        # Fewer than 6 data points — don't flag (not enough history)
        short_history = [Decimal("500"), Decimal("480"), Decimal("520")]
        flags = check_statistical_spike(Decimal("900"), short_history, "plant-A")
        assert flags == []

    def test_empty_history_no_flag(self):
        assert check_statistical_spike(Decimal("900"), [], "plant-A") == []

    def test_extreme_spike_flagged(self):
        # 45,000 L in one day vs a mean of ~500 L is clearly a spike
        flags = check_statistical_spike(Decimal("45000"), self.NORMAL_HISTORY, "DE99")
        assert STATISTICAL_SPIKE in flag_codes(flags)


# ─────────────────────────────────────────────────────────────────────────────
# TRAVEL_TYPE_MAP coverage
# ─────────────────────────────────────────────────────────────────────────────

class TestTravelTypeMap:
    """Ensure the type map handles the aliases documented in SOURCES.md."""

    AIR_ALIASES = ["air", "flight", "airline", "plane", "air travel"]
    RAIL_ALIASES = ["rail", "train", "eurostar", "rail travel"]
    HOTEL_ALIASES = ["hotel", "lodging", "accommodation", "hotel accommodation"]
    GROUND_ALIASES = ["car", "taxi", "uber", "lyft", "rental car", "bus", "ground"]

    def test_all_air_aliases(self):
        for alias in self.AIR_ALIASES:
            assert TRAVEL_TYPE_MAP.get(alias) == "AIR", f"Failed for alias: {alias}"

    def test_all_rail_aliases(self):
        for alias in self.RAIL_ALIASES:
            assert TRAVEL_TYPE_MAP.get(alias) == "RAIL", f"Failed for alias: {alias}"

    def test_all_hotel_aliases(self):
        for alias in self.HOTEL_ALIASES:
            assert TRAVEL_TYPE_MAP.get(alias) == "HOTEL", f"Failed for alias: {alias}"

    def test_all_ground_aliases(self):
        for alias in self.GROUND_ALIASES:
            assert TRAVEL_TYPE_MAP.get(alias) == "GROUND", f"Failed for alias: {alias}"


# ─────────────────────────────────────────────────────────────────────────────
# Airport coordinates sanity checks
# ─────────────────────────────────────────────────────────────────────────────

class TestAirportCoords:
    def test_key_airports_present(self):
        for code in ["LHR", "BOM", "JFK", "SIN", "DXB", "SYD", "NRT"]:
            assert code in AIRPORT_COORDS, f"{code} missing from AIRPORT_COORDS"

    def test_coordinates_are_valid_ranges(self):
        for code, (lat, lon) in AIRPORT_COORDS.items():
            assert -90 <= lat <= 90, f"{code} lat out of range: {lat}"
            assert -180 <= lon <= 180, f"{code} lon out of range: {lon}"

    def test_lhr_is_in_uk(self):
        lat, lon = AIRPORT_COORDS["LHR"]
        assert 51 < lat < 52
        assert -1 < lon < 0

    def test_bom_is_in_india(self):
        lat, lon = AIRPORT_COORDS["BOM"]
        assert 18 < lat < 20
        assert 72 < lon < 74
