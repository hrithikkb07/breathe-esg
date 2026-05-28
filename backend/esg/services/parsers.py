"""
Source-specific CSV parsers.

Each parser: reads raw CSV → applies tenant column mapping → extracts
canonical fields → yields one dict per row (never writes to DB).

Parsers do NOT normalize units and do NOT create DB records.
This separation keeps each parser independently testable.

WHY PANDAS over csv.DictReader:
- One-line column rename via mapping dict
- Handles encoding (utf-8-sig BOM common in SAP/Excel exports) cleanly
- Type coercion is declarative, not imperative
- Acceptable for file sizes in scope (<100MB)
For streaming >1GB files, replace with csv.DictReader + generators.
"""

import io
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Iterator, Optional
import pandas as pd


# ── SAP Parser ────────────────────────────────────────────────────────────────

SAP_DEFAULT_COLUMNS = {
    # English (standard SAP English locale / ABAP report output)
    "Posting Date":    "date",
    "Plant":           "plant_code",
    "Material":        "fuel_type",
    "Quantity":        "quantity",
    "Unit":            "unit",
    "Cost Center":     "cost_center",
    "Document Number": "invoice_ref",
    "Doc. Number":     "invoice_ref",
    "Movement Type":   "movement_type",
    "Mvt Type":        "movement_type",
    "Material Group":  "material_group",
    # German (SAP DE locale — common in European deployments)
    "Buchungsdatum":   "date",
    "Werk":            "plant_code",
    "Menge":           "quantity",
    "Einheit":         "unit",
    "Kostenstelle":    "cost_center",
    "Belegnummer":     "invoice_ref",
    "Bewegungsart":    "movement_type",
    "Materialgruppe":  "material_group",
    # SAP S/4HANA OData-style (camelCase)
    "PostingDate":     "date",
    "Plant":           "plant_code",
    "BaseUnit":        "unit",
}

SAP_DATE_FORMATS = [
    "%d.%m.%Y",   # German: 31.12.2023
    "%Y-%m-%d",   # ISO 8601
    "%m/%d/%Y",   # US
    "%d/%m/%Y",   # UK/AU
    "%Y%m%d",     # SAP compact
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%d.%m.%y",   # 2-digit year German
]


def _parse_sap_date(raw) -> Optional[date]:
    if raw is None or str(raw).strip() in ("", "nan", "NaT", "None"):
        return None
    raw_s = str(raw).strip()
    for fmt in SAP_DATE_FORMATS:
        try:
            return datetime.strptime(raw_s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal_european(raw: str) -> Optional[Decimal]:
    """
    Handle both European (1.234,56) and US (1,234.56) decimal formats.
    SAP German exports use periods as thousands separator and comma as decimal.
    """
    s = str(raw).strip()
    if not s or s in ("nan", "None", ""):
        return None
    # European: 4.250,500 → 4250.500
    if re.match(r"^-?\d{1,3}(\.\d{3})*(,\d+)?$", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        # US: 4,250.500 → 4250.500
        s = s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _detect_header_language(columns: list) -> str:
    """Return 'DE' if German headers detected, 'EN' otherwise."""
    german_markers = {"Buchungsdatum", "Werk", "Menge", "Einheit", "Kostenstelle"}
    if any(c in german_markers for c in columns):
        return "DE"
    return "EN"


def parse_sap_csv(
    file_content: bytes,
    column_mapping: dict = None,
    unit_mapping: dict = None,
) -> Iterator[dict]:
    """
    Parse a SAP fuel/procurement CSV export.

    Auto-detects:
    - Delimiter (semicolon for German locale, comma for EN)
    - Header language (German or English)
    - European vs US decimal formatting

    Yields one dict per row. Rows with unrecoverable errors yield
    {'parse_error': '...'} with 'parsed' absent so the orchestrator
    can store the raw row and skip normalization.
    """
    sample = file_content[:4096].decode("utf-8", errors="replace")
    delimiter = ";" if sample.count(";") > sample.count(",") else ","

    try:
        df = pd.read_csv(
            io.BytesIO(file_content),
            delimiter=delimiter,
            dtype=str,
            encoding="utf-8-sig",
            on_bad_lines="warn",
        )
    except Exception as e:
        yield {"parse_error": f"CSV read failed: {e}"}
        return

    df.columns = [c.strip() for c in df.columns]
    lang = _detect_header_language(list(df.columns))

    effective_mapping = {**SAP_DEFAULT_COLUMNS, **(column_mapping or {})}
    df = df.rename(columns=effective_mapping)

    effective_unit_map = unit_mapping or {}
    required = {"date", "plant_code", "quantity"}

    for idx, row in df.iterrows():
        row_dict = row.where(pd.notna(row), other=None).to_dict()
        errors = []

        def _is_blank(v):
            """True if value is absent, None, empty string, or a pandas NaN float."""
            if v is None:
                return True
            s = str(v).strip()
            return s == "" or s.lower() in ("nan", "none", "nat")

        missing = [f for f in required if _is_blank(row_dict.get(f))]
        if missing:
            errors.append(f"Missing required fields: {missing}")

        parsed_date = _parse_sap_date(row_dict.get("date"))
        if not parsed_date and "date" not in missing:
            errors.append(f"Unrecognised date format: '{row_dict.get('date')}'")

        raw_qty = str(row_dict.get("quantity") or "").strip()
        quantity = _parse_decimal_european(raw_qty)
        if quantity is None and "quantity" not in missing:
            errors.append(f"Non-numeric quantity: '{raw_qty}'")

        raw_unit = str(row_dict.get("unit") or "").strip()
        unit = effective_unit_map.get(raw_unit, raw_unit)

        # Normalise fuel type: strip whitespace, lower-case
        raw_fuel = str(row_dict.get("fuel_type") or "").strip()

        movement_type = str(row_dict.get("movement_type") or "261").strip()

        def _s(v):
            """Safe string: converts None/NaN/float to '' before strip."""
            s = str(v or "").strip()
            return "" if s in ("nan", "None", "NaT") else s

        yield {
            "raw": row_dict,
            "parsed": {
                "date":          parsed_date,
                "plant_code":    _s(row_dict.get("plant_code")),
                "fuel_type":     raw_fuel.lower(),
                "quantity":      quantity,
                "unit":          unit,
                "cost_center":   _s(row_dict.get("cost_center")),
                "invoice_ref":   _s(row_dict.get("invoice_ref")),
                "movement_type": movement_type,
            },
            "parse_error": "; ".join(errors) if errors else "",
            "header_language": lang,
        }


# ── Utility Parser ─────────────────────────────────────────────────────────────

UTILITY_DEFAULT_COLUMNS = {
    # Portal export variants (E.ON, EDF, MSEDCL, TSSPDCL)
    "Account Number":      "account_number",
    "Meter ID":            "meter_id",
    "Meter Number":        "meter_id",
    "MPAN":                "meter_id",      # UK Meter Point Administration Number
    "Consumer Number":     "meter_id",      # Indian utility portals
    "Zählernummer":        "meter_id",      # German
    "Service Start Date":  "period_start",
    "Service End Date":    "period_end",
    "Billing Start":       "period_start",
    "Billing End":         "period_end",
    "Abrechnungsbeginn":   "period_start",  # German
    "Abrechnungsende":     "period_end",
    "Usage":               "quantity",
    "kWh Usage":           "quantity",
    "Verbrauch":           "quantity",      # German
    "Units":               "unit",
    "Einheit":             "unit",
    "Tariff":              "tariff",
    "Rate Code":           "tariff",
    "Tarifart":            "tariff",        # German
    "Invoice Number":      "invoice_ref",
    "Invoice #":           "invoice_ref",
    "Rechnungsnummer":     "invoice_ref",
    "Facility":            "facility_name",
    "Site":                "facility_name",
    "Estimated Read":      "estimated_read",
    "Estimated":           "estimated_read",
}

UTILITY_DATE_FORMATS = [
    "%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y",
    "%d-%b-%Y", "%m-%d-%Y", "%d.%m.%Y",
    "%d-%m-%Y", "%Y/%m/%d",
]


def _parse_utility_date(raw) -> Optional[date]:
    if raw is None or str(raw).strip() in ("", "nan", "NaT"):
        return None
    for fmt in UTILITY_DATE_FORMATS:
        try:
            return datetime.strptime(str(raw).strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_utility_csv(
    file_content: bytes,
    column_mapping: dict = None,
    unit_mapping: dict = None,
) -> Iterator[dict]:
    """
    Parse utility electricity export CSV.

    Key complexity: billing periods don't align with calendar months.
    We preserve both period_start and period_end so GHG reporting can
    correctly pro-rate to fiscal/calendar months.

    Estimated reads are flagged for analyst attention — they may be
    superseded by a corrected bill in the same or next export.
    """
    try:
        df = pd.read_csv(io.BytesIO(file_content), dtype=str, encoding="utf-8-sig")
    except Exception as e:
        yield {"parse_error": f"CSV read failed: {e}"}
        return

    effective_mapping = {**UTILITY_DEFAULT_COLUMNS, **(column_mapping or {})}
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns=effective_mapping)

    for idx, row in df.iterrows():
        row_dict = row.where(pd.notna(row), other=None).to_dict()
        errors = []

        period_start = _parse_utility_date(row_dict.get("period_start"))
        period_end   = _parse_utility_date(row_dict.get("period_end"))

        if not period_start:
            errors.append(f"Cannot parse period_start: '{row_dict.get('period_start')}'")
        if not period_end:
            errors.append(f"Cannot parse period_end: '{row_dict.get('period_end')}'")

        raw_qty = str(row_dict.get("quantity") or "").replace(",", "").strip()
        quantity = None
        if raw_qty:
            try:
                quantity = Decimal(raw_qty)
            except InvalidOperation:
                errors.append(f"Non-numeric quantity: '{raw_qty}'")

        raw_unit = str(row_dict.get("unit") or "kWh").strip()
        unit = (unit_mapping or {}).get(raw_unit, raw_unit) or "kWh"

        # Normalise estimated-read flag to bool
        est_raw = str(row_dict.get("estimated_read") or "").strip().lower()
        is_estimated = est_raw in ("yes", "y", "true", "1", "estimated")

        def _s(v):
            s = str(v or "").strip()
            return "" if s in ("nan", "None", "NaT") else s

        yield {
            "raw": row_dict,
            "parsed": {
                "meter_id":       _s(row_dict.get("meter_id") or row_dict.get("account_number")),
                "period_start":   period_start,
                "period_end":     period_end,
                "quantity":       quantity,
                "unit":           unit,
                "tariff":         _s(row_dict.get("tariff")),
                "invoice_ref":    _s(row_dict.get("invoice_ref")),
                "facility_name":  _s(row_dict.get("facility_name")),
                "is_estimated":   is_estimated,
            },
            "parse_error": "; ".join(errors) if errors else "",
        }


# ── Travel Parser ─────────────────────────────────────────────────────────────

TRAVEL_DEFAULT_COLUMNS = {
    # SAP Concur Intelligence export
    "Employee ID":      "employee_id",
    "Trip ID":          "trip_id",
    "Expense Type":     "travel_type",
    "Travel Date":      "travel_date",
    "Return Date":      "return_date",
    "Departure Date":   "travel_date",
    "Origin":           "origin",
    "Destination":      "destination",
    "From":             "origin",
    "To":               "destination",
    "Distance (km)":    "distance_km",
    "Distance (mi)":    "distance_mi",
    "Distance":         "distance_km",
    "Cabin Class":      "cabin_class",
    "Class":            "cabin_class",
    "Number of Nights": "nights",
    "Nights":           "nights",
    "Hotel Name":       "hotel_name",
    "Merchant":         "hotel_name",
    # Navan export aliases
    "traveler_id":      "employee_id",
    "booking_type":     "travel_type",
    "depart_date":      "travel_date",
    "arrive_date":      "return_date",
    "from_location":    "origin",
    "to_location":      "destination",
    "trip_type":        "travel_type",
    # TravelPerk aliases
    "traveller_id":     "employee_id",
    "segment_type":     "travel_type",
    "origin_iata":      "origin",
    "destination_iata": "destination",
}

TRAVEL_TYPE_MAP = {
    # Air
    "air": "AIR", "flight": "AIR", "airline": "AIR",
    "plane": "AIR", "air travel": "AIR",
    # Rail
    "rail": "RAIL", "train": "RAIL", "amtrak": "RAIL",
    "eurostar": "RAIL", "rail travel": "RAIL",
    # Hotel
    "hotel": "HOTEL", "lodging": "HOTEL", "accommodation": "HOTEL",
    "hotel accommodation": "HOTEL",
    # Ground
    "car": "GROUND", "taxi": "GROUND", "uber": "GROUND",
    "lyft": "GROUND", "rental car": "GROUND", "car rental": "GROUND",
    "bus": "GROUND", "ground": "GROUND", "ground transport": "GROUND",
    "car hire": "GROUND",
}

TRAVEL_DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%b-%Y", "%d.%m.%Y",
]


def _parse_travel_date(raw) -> Optional[date]:
    if raw is None or str(raw).strip() in ("", "nan", "NaT"):
        return None
    for fmt in TRAVEL_DATE_FORMATS:
        try:
            return datetime.strptime(str(raw).strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_travel_csv(
    file_content: bytes,
    column_mapping: dict = None,
    unit_mapping: dict = None,
) -> Iterator[dict]:
    """
    Parse corporate travel CSV (Concur/Navan/TravelPerk-inspired).

    Mixed record types (flights, hotels, ground transport, rail) appear
    in one file. Each type uses different emission factors and different
    relevant fields. We normalise travel_type to a canonical code
    (AIR / HOTEL / RAIL / GROUND) and extract type-appropriate fields.

    Distance resolution priority:
      1. Provided distance_km in source data
      2. Convert distance_mi if provided
      3. Estimate from IATA airport codes (Haversine)
      4. None — DISTANCE_NOT_FOUND or UNKNOWN_AIRPORT flag raised later
    """
    from esg.services.normalization import estimate_flight_distance_km

    try:
        df = pd.read_csv(
            io.BytesIO(file_content),
            dtype=str,
            encoding="utf-8-sig",
            quoting=0,          # QUOTE_MINIMAL — respects " around commas in fields
            on_bad_lines="warn",
        )
    except Exception as e:
        yield {"parse_error": f"CSV read failed: {e}"}
        return

    effective_mapping = {**TRAVEL_DEFAULT_COLUMNS, **(column_mapping or {})}
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns=effective_mapping)

    for idx, row in df.iterrows():
        row_dict = row.where(pd.notna(row), other=None).to_dict()
        errors = []

        travel_date = _parse_travel_date(row_dict.get("travel_date"))
        return_date = _parse_travel_date(row_dict.get("return_date"))
        if not travel_date:
            errors.append(f"Cannot parse travel_date: '{row_dict.get('travel_date')}'")

        raw_type = str(row_dict.get("travel_type") or "").strip().lower()
        canonical_type = TRAVEL_TYPE_MAP.get(raw_type, "UNKNOWN")

        # ── Distance resolution ──────────────────────────────────────────────
        distance_km = None
        distance_is_estimated = False

        raw_km = str(row_dict.get("distance_km") or "").strip()
        raw_mi = str(row_dict.get("distance_mi") or "").strip()

        if raw_km and raw_km not in ("", "nan"):
            try:
                distance_km = Decimal(raw_km.replace(",", ""))
            except InvalidOperation:
                pass

        if distance_km is None and raw_mi and raw_mi not in ("", "nan"):
            try:
                distance_km = Decimal(raw_mi.replace(",", "")) * Decimal("1.60934")
            except InvalidOperation:
                pass

        def _s(v):
            s = str(v or "").strip()
            return "" if s in ("nan", "None", "NaT") else s

        origin      = _s(row_dict.get("origin")).upper()[:8]
        destination = _s(row_dict.get("destination")).upper()[:8]

        # Only estimate from IATA codes for flights — rail/ground codes may
        # be city codes, not IATA, and the formula would be less reliable.
        if distance_km is None and canonical_type == "AIR" and origin and destination:
            estimated = estimate_flight_distance_km(origin, destination)
            if estimated is not None:
                distance_km = estimated
                distance_is_estimated = True
            # If estimate returns None, UNKNOWN_AIRPORT flag is raised by suspicious checker

        # ── Hotel nights ─────────────────────────────────────────────────────
        nights = None
        if canonical_type == "HOTEL":
            raw_nights = str(row_dict.get("nights") or "").strip()
            if raw_nights and raw_nights not in ("", "nan"):
                try:
                    nights = int(float(raw_nights))
                except (ValueError, TypeError):
                    errors.append(f"Cannot parse nights: '{raw_nights}'")

            # Derive from travel_date / return_date if nights not given
            if nights is None and travel_date and return_date:
                nights = (return_date - travel_date).days or 1

        cabin_raw = str(row_dict.get("cabin_class") or "economy").strip().lower()

        yield {
            "raw": row_dict,
            "parsed": {
                "employee_id":        _s(row_dict.get("employee_id")),
                "trip_id":            _s(row_dict.get("trip_id")),
                "travel_type":        canonical_type,
                "travel_date":        travel_date,
                "return_date":        return_date or travel_date,
                "origin":             origin,
                "destination":        destination,
                "distance_km":        distance_km,
                "distance_is_estimated": distance_is_estimated,
                "cabin_class":        cabin_raw,
                "nights":             nights,
                "hotel_name":         _s(row_dict.get("hotel_name")),
            },
            "parse_error": "; ".join(errors) if errors else "",
        }