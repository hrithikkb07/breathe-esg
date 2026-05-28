"""
Suspicious record detection.

These checks run after normalization, before records enter the review queue.
Suspicious records land in FLAGGED status; analysts must consciously approve them.

Design principle: Flag generously, let analysts decide. A false positive
is better than a missed anomaly going to auditors. The flag reason codes
are structured so downstream tooling (dashboards, exports) can filter by type.

Each check returns a list of {"code": str, "detail": str} dicts or an empty list.
The detector aggregates them. If any flags are raised, the record is marked suspicious.
"""

from decimal import Decimal
from datetime import date
from typing import Optional
import statistics


# ── Flag Codes ────────────────────────────────────────────────────────────────
NEGATIVE_QUANTITY         = "NEGATIVE_QUANTITY"
ZERO_QUANTITY             = "ZERO_QUANTITY"
FUTURE_DATE               = "FUTURE_DATE"
DATE_TOO_OLD              = "DATE_TOO_OLD"
DUPLICATE_INVOICE         = "DUPLICATE_INVOICE"
STATISTICAL_SPIKE         = "STATISTICAL_SPIKE"
MISSING_UNIT              = "MISSING_UNIT"
IMPLAUSIBLE_FLIGHT_DISTANCE = "IMPLAUSIBLE_FLIGHT_DISTANCE"
BILLING_OVERLAP           = "BILLING_OVERLAP"
MISSING_PLANT_CODE        = "MISSING_PLANT_CODE"
DISTANCE_NOT_FOUND        = "DISTANCE_NOT_FOUND"   # airport codes present but no distance calculable
UNKNOWN_AIRPORT           = "UNKNOWN_AIRPORT"       # airport code not in our lookup
SAP_REVERSAL              = "SAP_REVERSAL"           # movement type 262 — legitimate return, but needs review
UNKNOWN_FUEL_TYPE         = "UNKNOWN_FUEL_TYPE"      # fuel type not in emission factor table
BILLING_PERIOD_ANOMALY    = "BILLING_PERIOD_ANOMALY" # billing period <20 or >40 days (utility)


def check_quantity(quantity: Optional[Decimal]) -> list:
    """Check for physically impossible or suspicious quantities."""
    flags = []
    if quantity is None:
        flags.append({
            "code": MISSING_UNIT,
            "detail": "Quantity is null — normalization could not determine a value.",
        })
        return flags
    if quantity < 0:
        flags.append({
            "code": NEGATIVE_QUANTITY,
            "detail": f"Quantity is negative ({quantity}). "
                      "Negative fuel/electricity consumption is physically impossible "
                      "unless this is a SAP reversal (movement type 262) or a net-metered "
                      "solar installation. Verify before approving.",
        })
    if quantity == 0:
        flags.append({
            "code": ZERO_QUANTITY,
            "detail": "Quantity is exactly zero. Likely a missing value or unfilled placeholder "
                      "in the source export.",
        })
    return flags


def check_dates(period_start: date, period_end: date) -> list:
    """Check for impossible or suspicious date ranges."""
    flags = []
    today = date.today()

    if period_start > today or period_end > today:
        flags.append({
            "code": FUTURE_DATE,
            "detail": f"Period {period_start} → {period_end} is in the future. "
                      "Consumption data for future periods cannot exist.",
        })

    if period_end < period_start:
        flags.append({
            "code": FUTURE_DATE,
            "detail": f"Period end ({period_end}) is before period start ({period_start}). "
                      "Dates appear to be swapped in the source file.",
        })

    if period_start.year < 2015:
        flags.append({
            "code": DATE_TOO_OLD,
            "detail": f"Period starts in {period_start.year}. Pre-2015 data is unusual for a "
                      "new client onboarding now. Most GHG reporting uses 2019 as the baseline "
                      "year per Paris Agreement guidance. Verify this is intentional.",
        })

    return flags


def check_billing_period_length(period_start: date, period_end: date) -> list:
    """
    Utility-specific: billing periods should be 20-40 days.
    Shorter = likely a partial bill or date error.
    Longer = likely two billing periods merged, or a date error.
    """
    days = (period_end - period_start).days
    if days < 20:
        return [{
            "code": BILLING_PERIOD_ANOMALY,
            "detail": f"Billing period is only {days} days ({period_start} → {period_end}). "
                      "Standard utility billing cycles are 28-35 days. This may be a partial "
                      "bill, a catch-up adjustment, or a date parsing error.",
        }]
    if days > 40:
        return [{
            "code": BILLING_PERIOD_ANOMALY,
            "detail": f"Billing period is {days} days ({period_start} → {period_end}). "
                      "Standard billing cycles are 28-35 days. This may represent two merged "
                      "bills or a date parsing error.",
        }]
    return []


def check_statistical_spike(
    quantity: Decimal,
    historical_quantities: list,
    entity_id: str,
) -> list:
    """
    Flag if a new quantity is more than 3 standard deviations from the entity's
    historical mean. Requires at least 6 historical data points to be meaningful.

    3σ threshold is conservative by design — we'd rather flag edge cases for
    review than suppress them. The analyst can approve with a note if legitimate.
    """
    if len(historical_quantities) < 6:
        return []

    floats = [float(q) for q in historical_quantities]
    mean = statistics.mean(floats)
    stdev = statistics.stdev(floats)

    if stdev == 0:
        return []

    z_score = abs((float(quantity) - mean) / stdev)

    if z_score > 3:
        return [{
            "code": STATISTICAL_SPIKE,
            "detail": (
                f"Value {quantity} is {z_score:.1f}σ from the historical mean "
                f"({mean:.2f}) for entity '{entity_id}'. This may indicate a meter "
                "malfunction, a unit mismatch in the source export, or a genuine "
                "consumption anomaly."
            ),
        }]
    return []


def check_duplicate_invoice(
    invoice_ref: Optional[str],
    tenant_id,
    source_type: str,
) -> list:
    """
    Detect if an invoice/reference number has already been ingested for this tenant.
    Catches: re-uploads of the same file, source-side duplicates, or copy-paste errors
    in manually maintained spreadsheets.

    Note: Some SAP numbering schemes re-use document numbers across fiscal years.
    The check is scoped to (tenant, source_type) so cross-year duplicates within
    the same source will still flag — the analyst should verify the year.
    """
    from esg.models import RawRecord

    if not invoice_ref:
        return []

    existing = RawRecord.objects.filter(
        upload__tenant_id=tenant_id,
        upload__source_type=source_type,
        raw_data__invoice_ref=invoice_ref,
    ).exists()

    if existing:
        return [{
            "code": DUPLICATE_INVOICE,
            "detail": f"Invoice/document reference '{invoice_ref}' has already been ingested "
                      f"for this client from a {source_type} source. Likely a re-upload of the "
                      "same file or a source-side duplicate.",
        }]
    return []


def check_flight_distance(
    distance_km: Optional[Decimal],
    origin: str = "",
    destination: str = "",
    distance_is_estimated: bool = False,
) -> list:
    """
    Two distinct flight distance checks:

    1. If distance was computed or provided: sanity-check it's physically possible.
    2. If distance is None but we have airport codes: UNKNOWN_AIRPORT — we have
       codes but can't look them up. This is a silent failure we must surface.
    3. If no distance AND no airport codes: DISTANCE_NOT_FOUND — we cannot
       calculate emissions at all without a distance.
    """
    flags = []

    if distance_km is None:
        if origin and destination:
            flags.append({
                "code": UNKNOWN_AIRPORT,
                "detail": (
                    f"Airport codes '{origin}' → '{destination}' are not in our lookup table. "
                    "Distance cannot be estimated. Emission calculation is incomplete. "
                    "Add these airports to the lookup table or provide distance in the source data."
                ),
            })
        else:
            flags.append({
                "code": DISTANCE_NOT_FOUND,
                "detail": "No distance provided and no airport codes available to estimate one. "
                          "CO₂e for this flight cannot be calculated. Record needs manual distance entry.",
            })
        return flags

    if distance_km > 20100:
        flags.append({
            "code": IMPLAUSIBLE_FLIGHT_DISTANCE,
            "detail": f"Distance {distance_km} km exceeds Earth's maximum great-circle distance (~20,004 km). "
                      "Likely a data entry error or unit mismatch (miles entered as km?).",
        })
    if Decimal("0") <= distance_km < Decimal("50"):
        flags.append({
            "code": IMPLAUSIBLE_FLIGHT_DISTANCE,
            "detail": f"Distance {distance_km} km is below the minimum plausible commercial "
                      "flight distance. The shortest scheduled commercial flights are ~50 km. "
                      "Check if origin and destination are the same city.",
        })

    return flags


def check_sap_reversal(movement_type: Optional[str]) -> list:
    """
    SAP movement type 262 = Goods Return (reversal of a 261 Goods Issue).
    This legitimately produces a negative quantity — it's not a data error,
    but it does need analyst review because it affects the period's total.
    """
    if movement_type and str(movement_type).strip() in ("262", "202", "542"):
        return [{
            "code": SAP_REVERSAL,
            "detail": f"SAP movement type {movement_type} is a goods return/reversal. "
                      "The negative quantity is expected. Verify the original Goods Issue "
                      "(movement type 261) it reverses is also present in the dataset, "
                      "and that the net position for the period is correct.",
        }]
    return []


def check_unknown_fuel_type(fuel_type: str, known_fuels: set) -> list:
    """Flag if a fuel type doesn't map to any emission factor."""
    if fuel_type and fuel_type.lower() not in known_fuels:
        return [{
            "code": UNKNOWN_FUEL_TYPE,
            "detail": f"Fuel type '{fuel_type}' has no emission factor in our reference table. "
                      "CO₂e calculation used a default factor. Verify the correct factor "
                      "and update the normalization configuration.",
        }]
    return []


def check_billing_overlap(
    meter_id: str,
    period_start: date,
    period_end: date,
    tenant_id,
    exclude_upload_id=None,
) -> list:
    """
    Detect if we already have a utility record for this meter that overlaps
    with this billing period.

    WHY THIS MATTERS: Utilities sometimes issue a corrected bill after an estimated
    read is replaced with an actual read. Both the estimated and actual bills may
    appear in the same export if the facilities team doesn't filter by date.
    The corrected bill supersedes the estimated one, but both look valid individually.
    """
    from esg.models import NormalizedEmissionRecord

    qs = NormalizedEmissionRecord.objects.filter(
        tenant_id=tenant_id,
        emission_category="PURCHASED_ELECTRICITY",
        source_entity_id=meter_id,
        period_start__lt=period_end,
        period_end__gt=period_start,
    )
    if exclude_upload_id:
        qs = qs.exclude(raw_record__upload_id=exclude_upload_id)

    if qs.exists():
        return [{
            "code": BILLING_OVERLAP,
            "detail": (
                f"Meter '{meter_id}' already has a record that overlaps with "
                f"{period_start} → {period_end}. This may be an estimated read "
                "that has since been corrected. Compare both records and reject "
                "the estimated one."
            ),
        }]
    return []


def run_all_checks(*, record_data: dict, context: dict) -> list:
    """
    Run all applicable checks and return aggregated flags.
    Context keys consumed:
      tenant_id, upload_id, source_type, invoice_ref,
      historical_quantities, movement_type, fuel_type, known_fuels
    """
    flags = []

    flags.extend(check_quantity(record_data.get("activity_quantity")))
    flags.extend(check_dates(record_data["period_start"], record_data["period_end"]))

    # SAP-specific
    if context.get("source_type") == "SAP":
        flags.extend(check_sap_reversal(context.get("movement_type")))
        if context.get("fuel_type") and context.get("known_fuels"):
            flags.extend(check_unknown_fuel_type(
                context["fuel_type"], context["known_fuels"]
            ))

    # Utility-specific
    if context.get("source_type") == "UTILITY":
        flags.extend(check_billing_period_length(
            record_data["period_start"], record_data["period_end"]
        ))
        flags.extend(check_billing_overlap(
            meter_id=record_data.get("source_entity_id", ""),
            period_start=record_data["period_start"],
            period_end=record_data["period_end"],
            tenant_id=context["tenant_id"],
            exclude_upload_id=context.get("upload_id"),
        ))

    # Travel-specific
    if record_data.get("emission_category") == "BUSINESS_TRAVEL_AIR":
        flags.extend(check_flight_distance(
            distance_km=record_data.get("distance_km"),
            origin=record_data.get("origin_code", ""),
            destination=record_data.get("destination_code", ""),
            distance_is_estimated=record_data.get("distance_is_estimated", False),
        ))

    # Cross-source
    if context.get("historical_quantities"):
        flags.extend(check_statistical_spike(
            quantity=record_data["activity_quantity"],
            historical_quantities=context["historical_quantities"],
            entity_id=record_data.get("source_entity_id", "unknown"),
        ))

    if context.get("invoice_ref"):
        flags.extend(check_duplicate_invoice(
            invoice_ref=context["invoice_ref"],
            tenant_id=context["tenant_id"],
            source_type=context.get("source_type", ""),
        ))

    return flags
