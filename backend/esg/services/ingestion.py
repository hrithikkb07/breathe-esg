"""
Ingestion orchestrator.

Coordinates: file read → parser dispatch → RawRecord creation →
normalization → suspicious checks → NormalizedEmissionRecord → audit log.

All DB writes happen in one transaction per upload. Row-level failures
do not abort the batch — they are recorded and counted.

WHY SYNCHRONOUS (not Celery):
Files in scope (<50MB, <50k rows) parse in <10s. Celery adds a broker,
a worker process, retry infrastructure, and status-polling complexity.
The interface is designed so switching is a 2-line change — see TRADEOFFS.md.
"""

from decimal import Decimal
from django.utils import timezone
from django.db import transaction

from esg.models import SourceUpload, RawRecord, NormalizedEmissionRecord, AuditLog
from esg.models.audit import log_event
from esg.services.parsers import parse_sap_csv, parse_utility_csv, parse_travel_csv
from esg.services.normalization import (
    normalize_fuel_volume,
    normalize_energy,
    UnitNormalizationError,
    estimate_flight_distance_km,
    known_fuel_types,
)
from esg.services.suspicious import run_all_checks


# ── Emission Factors ─────────────────────────────────────────────────────────
# kg CO₂e per unit of activity.
# Source: DEFRA 2023 Greenhouse Gas Reporting Conversion Factors.
#
# In production these live in an EmissionFactor table with effective_date
# so factor updates can be tracked and records re-derived. See TRADEOFFS.md.
#
# Structure here mirrors what a DB table would expose, so the switch is a
# one-line change: EF["STATIONARY_COMBUSTION"]["diesel"]  →
#   EmissionFactor.objects.get_active("STATIONARY_COMBUSTION", "diesel", date)
EMISSION_FACTORS = {
    "STATIONARY_COMBUSTION": {
        # kg CO₂e per liter (location-based, LHV combustion)
        "diesel":        Decimal("2.6391"),
        "petrol":        Decimal("2.3115"),
        "gasoline":      Decimal("2.3115"),
        "unleaded":      Decimal("2.3115"),
        "natural_gas":   Decimal("2.0403"),
        "cng":           Decimal("1.6792"),
        "lpg":           Decimal("1.5551"),
        "kerosene":      Decimal("2.5401"),
        "aviation_fuel": Decimal("2.5401"),
        "hfo":           Decimal("3.1535"),
        "heating_oil":   Decimal("2.6997"),
        "heizöl":        Decimal("2.6997"),
        "biodiesel":     Decimal("0.1932"),  # net; DEFRA B100 value
        "default":       Decimal("2.5000"),  # conservative fallback
    },
    "PURCHASED_ELECTRICITY": {
        # kg CO₂e per kWh (location-based grid averages, DEFRA 2023)
        "GB":       Decimal("0.20493"),
        "DE":       Decimal("0.38500"),
        "IN_WEST":  Decimal("0.81600"),  # Maharashtra/Gujarat grid
        "IN_NORTH": Decimal("0.82100"),  # Delhi grid
        "IN_SOUTH": Decimal("0.79800"),
        "IN_EAST":  Decimal("0.83400"),
        "US":       Decimal("0.38600"),
        "default":  Decimal("0.23314"),  # UK average as conservative fallback
    },
    "BUSINESS_TRAVEL_AIR": {
        # kg CO₂e per passenger-km (includes radiative forcing factor)
        "economy":         Decimal("0.25500"),
        "premium_economy": Decimal("0.35100"),
        "business":        Decimal("0.57300"),
        "first":           Decimal("0.85300"),
        "default":         Decimal("0.25500"),
    },
    "BUSINESS_TRAVEL_RAIL": {
        "default": Decimal("0.04100"),  # kg CO₂e per passenger-km, UK average
    },
    "BUSINESS_TRAVEL_HOTEL": {
        "default": Decimal("31.0"),     # kg CO₂e per room-night, global average
    },
    "BUSINESS_TRAVEL_GROUND": {
        "default": Decimal("0.17100"),  # kg CO₂e per km, average car
    },
}

EF_SOURCE = "DEFRA 2023"


class IngestionError(Exception):
    pass


@transaction.atomic
def process_upload(upload_id: str, actor=None) -> SourceUpload:
    """
    Main ingestion pipeline for one SourceUpload.

    Steps:
      1. Lock upload row, mark PROCESSING
      2. Read file bytes
      3. Detect and apply tenant SourceMapping (column/unit overrides)
      4. Parse with source-appropriate parser
      5. Per row: create RawRecord → normalize → run suspicious checks → create NormalizedRecord
      6. Write upload statistics
      7. Emit audit events
    """
    upload = SourceUpload.objects.select_for_update().get(id=upload_id)

    if upload.status != SourceUpload.Status.PENDING:
        raise IngestionError(f"Upload {upload_id} is not in PENDING status (got {upload.status}).")

    upload.status = SourceUpload.Status.PROCESSING
    upload.save(update_fields=["status"])
    log_event(tenant=upload.tenant, action=AuditLog.Action.UPLOAD_PROCESSING,
              resource=upload, actor=actor)

    try:
        file_content = upload.file.read()
    except Exception as e:
        _fail_upload(upload, f"Could not read file: {e}")
        return upload

    column_mapping = {}
    unit_mapping = {}
    if upload.source_mapping:
        column_mapping = upload.source_mapping.column_mappings
        unit_mapping = upload.source_mapping.unit_mappings

    parser_map = {
        SourceUpload.SourceType.SAP:     parse_sap_csv,
        SourceUpload.SourceType.UTILITY: parse_utility_csv,
        SourceUpload.SourceType.TRAVEL:  parse_travel_csv,
    }
    parser = parser_map[upload.source_type]

    counts = {"total": 0, "success": 0, "failed": 0, "suspicious": 0}
    historical_cache = _build_historical_cache(upload)
    known_fuels = known_fuel_types()

    for row_number, row_result in enumerate(
        parser(file_content, column_mapping=column_mapping, unit_mapping=unit_mapping),
        start=1,
    ):
        counts["total"] += 1

        # Always persist the raw row — even failures — for analyst drill-down
        raw_record = RawRecord.objects.create(
            upload=upload,
            row_number=row_number,
            raw_data=row_result.get("raw", {}),
            parse_error=row_result.get("parse_error", ""),
        )

        if row_result.get("parse_error") and not row_result.get("parsed"):
            counts["failed"] += 1
            continue

        try:
            normalized_data, suspicious_context = _normalize_row(
                source_type=upload.source_type,
                parsed=row_result["parsed"],
                upload=upload,
            )
        except Exception as e:
            raw_record.parse_error = f"Normalization error: {e}"
            # Use update to avoid triggering the immutability check on full save
            RawRecord.objects.filter(pk=raw_record.pk).update(parse_error=raw_record.parse_error)
            counts["failed"] += 1
            continue

        # Merge context for suspicious checks
        suspicious_context.update({
            "tenant_id": upload.tenant_id,
            "upload_id": str(upload.id),
            "source_type": upload.source_type,
            "invoice_ref": row_result["parsed"].get("invoice_ref"),
            "historical_quantities": historical_cache.get(
                normalized_data.get("source_entity_id"), []
            ),
            "known_fuels": known_fuels,
        })

        flags = run_all_checks(record_data=normalized_data, context=suspicious_context)
        is_suspicious = bool(flags)
        review_status = (
            NormalizedEmissionRecord.ReviewStatus.PENDING
            if is_suspicious
            else NormalizedEmissionRecord.ReviewStatus.APPROVED
        )

        NormalizedEmissionRecord.objects.create(
            tenant=upload.tenant,
            raw_record=raw_record,
            review_status=review_status,
            is_suspicious=is_suspicious,
            suspicious_reasons=flags,
            **normalized_data,
        )

        counts["success"] += 1
        if is_suspicious:
            counts["suspicious"] += 1

    upload.status = (
        SourceUpload.Status.PARTIAL if counts["failed"] > 0 else SourceUpload.Status.COMPLETE
    )
    upload.row_count_total    = counts["total"]
    upload.row_count_success  = counts["success"]
    upload.row_count_failed   = counts["failed"]
    upload.row_count_suspicious = counts["suspicious"]
    upload.completed_at = timezone.now()
    upload.save()

    log_event(tenant=upload.tenant, action=AuditLog.Action.UPLOAD_COMPLETE,
              resource=upload, actor=actor, payload=counts)

    return upload


def _fail_upload(upload: SourceUpload, message: str) -> None:
    upload.status = SourceUpload.Status.FAILED
    upload.error_message = message
    upload.completed_at = timezone.now()
    upload.save(update_fields=["status", "error_message", "completed_at"])


def _normalize_row(*, source_type, parsed, upload) -> tuple[dict, dict]:
    """
    Returns (normalized_field_dict, suspicious_context_dict).
    Separating them keeps the normalization return clean while still
    surfacing source-specific context (movement_type, fuel_type) to the
    suspicious checker without embedding checker logic here.
    """
    if source_type == SourceUpload.SourceType.SAP:
        return _normalize_sap(parsed, upload)
    if source_type == SourceUpload.SourceType.UTILITY:
        return _normalize_utility(parsed, upload)
    if source_type == SourceUpload.SourceType.TRAVEL:
        return _normalize_travel(parsed, upload)
    raise IngestionError(f"Unknown source type: {source_type}")


def _normalize_sap(parsed: dict, upload) -> tuple[dict, dict]:
    from esg.models.upload import PlantCodeLookup

    date_val   = parsed["date"]
    plant_code = parsed.get("plant_code", "")
    fuel_type  = parsed.get("fuel_type", "diesel")
    quantity   = parsed.get("quantity") or Decimal("0")
    unit       = parsed.get("unit", "L")
    movement_type = str(parsed.get("movement_type", "261")).strip()

    # Resolve plant code → human name and grid region
    plant_name = ""
    grid_region = "default"
    try:
        lookup = PlantCodeLookup.objects.get(tenant=upload.tenant, plant_code=plant_code)
        plant_name  = lookup.plant_name
        grid_region = lookup.grid_region or "default"
    except PlantCodeLookup.DoesNotExist:
        pass  # MISSING_PLANT_CODE could be flagged here; we leave it to the caller

    result = normalize_fuel_volume(quantity, unit, fuel_type)
    quantity_liters = result["quantity_liters"]

    fuel_lower = fuel_type.lower().strip()
    ef_table   = EMISSION_FACTORS["STATIONARY_COMBUSTION"]
    ef         = ef_table.get(fuel_lower, ef_table["default"])
    co2e_tonnes = quantity_liters * ef / Decimal("1000")

    normalized = {
        "scope": 1,
        "emission_category": NormalizedEmissionRecord.EmissionCategory.STATIONARY_COMBUSTION,
        "activity_quantity": quantity_liters,
        "activity_unit":     NormalizedEmissionRecord.ActivityUnit.LITERS,
        "original_quantity": quantity,
        "original_unit":     unit,
        "emission_factor":        ef,
        "emission_factor_source": EF_SOURCE,
        "co2e_tonnes":        co2e_tonnes,
        "period_start": date_val,
        "period_end":   date_val,
        "source_entity_id":   plant_code,
        "source_entity_name": plant_name,
    }

    context = {
        "movement_type": movement_type,
        "fuel_type":     fuel_lower,
    }
    return normalized, context


def _normalize_utility(parsed: dict, upload) -> tuple[dict, dict]:
    quantity = parsed.get("quantity") or Decimal("0")
    unit     = parsed.get("unit", "kWh")

    kwh = normalize_energy(quantity, unit)

    # Use grid_region from plant code lookup if meter is mapped; fall back to default
    # In production, meters would be linked to a site which has a grid_region.
    ef = EMISSION_FACTORS["PURCHASED_ELECTRICITY"]["default"]

    normalized = {
        "scope": 2,
        "emission_category": NormalizedEmissionRecord.EmissionCategory.PURCHASED_ELECTRICITY,
        "activity_quantity": kwh,
        "activity_unit":     NormalizedEmissionRecord.ActivityUnit.KWH,
        "original_quantity": quantity,
        "original_unit":     unit,
        "emission_factor":        ef,
        "emission_factor_source": EF_SOURCE,
        "co2e_tonnes":        kwh * ef / Decimal("1000"),
        "period_start": parsed["period_start"],
        "period_end":   parsed["period_end"],
        "source_entity_id":   parsed.get("meter_id", ""),
        "source_entity_name": parsed.get("facility_name", ""),
    }
    return normalized, {}


def _normalize_travel(parsed: dict, upload) -> tuple[dict, dict]:
    travel_type = parsed.get("travel_type", "UNKNOWN")
    travel_date = parsed["travel_date"]
    return_date = parsed.get("return_date") or travel_date

    CATEGORY_MAP = {
        "AIR":    NormalizedEmissionRecord.EmissionCategory.BUSINESS_TRAVEL_AIR,
        "RAIL":   NormalizedEmissionRecord.EmissionCategory.BUSINESS_TRAVEL_RAIL,
        "HOTEL":  NormalizedEmissionRecord.EmissionCategory.BUSINESS_TRAVEL_HOTEL,
        "GROUND": NormalizedEmissionRecord.EmissionCategory.BUSINESS_TRAVEL_GROUND,
    }
    category = CATEGORY_MAP.get(
        travel_type,
        NormalizedEmissionRecord.EmissionCategory.BUSINESS_TRAVEL_GROUND
    )

    if category == NormalizedEmissionRecord.EmissionCategory.BUSINESS_TRAVEL_HOTEL:
        nights = Decimal(str(parsed.get("nights") or 1))
        ef     = EMISSION_FACTORS["BUSINESS_TRAVEL_HOTEL"]["default"]
        return {
            "scope": 3,
            "emission_category": category,
            "activity_quantity": nights,
            "activity_unit":     NormalizedEmissionRecord.ActivityUnit.NIGHTS,
            "original_quantity": nights,
            "original_unit":     "nights",
            "emission_factor":        ef,
            "emission_factor_source": EF_SOURCE,
            "co2e_tonnes":        nights * ef / Decimal("1000"),
            "period_start":      travel_date,
            "period_end":        return_date,
            "source_entity_id":   parsed.get("employee_id", ""),
            "source_entity_name": parsed.get("hotel_name", ""),
        }, {}

    # Distance-based (air, rail, ground)
    distance_km = parsed.get("distance_km") or Decimal("0")
    distance_is_estimated = parsed.get("distance_is_estimated", False)

    ef_map = EMISSION_FACTORS.get(category.value, {})
    cabin  = (parsed.get("cabin_class") or "economy").lower().strip()
    ef     = ef_map.get(cabin, ef_map.get("default", Decimal("0.2")))

    return {
        "scope": 3,
        "emission_category": category,
        "activity_quantity": distance_km,
        "activity_unit":     NormalizedEmissionRecord.ActivityUnit.KM,
        "original_quantity": distance_km,
        "original_unit":     "km",
        "emission_factor":        ef,
        "emission_factor_source": EF_SOURCE,
        "co2e_tonnes":        distance_km * ef / Decimal("1000"),
        "period_start": travel_date,
        "period_end":   return_date,
        "source_entity_id":   parsed.get("employee_id", ""),
        "origin_code":        parsed.get("origin", ""),
        "destination_code":   parsed.get("destination", ""),
        "distance_km":        distance_km if distance_km else None,
        "distance_is_estimated": distance_is_estimated,
    }, {}


def _build_historical_cache(upload) -> dict:
    """Pre-fetch historical quantities per source entity for spike detection."""
    records = (
        NormalizedEmissionRecord.objects
        .filter(tenant=upload.tenant)
        .exclude(raw_record__upload=upload)
        .values("source_entity_id", "activity_quantity")
    )
    cache: dict = {}
    for r in records:
        cache.setdefault(r["source_entity_id"], []).append(r["activity_quantity"])
    return cache