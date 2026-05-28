# Sample Data Guide

Every anomaly in the sample CSVs is deliberate. This document maps each
unusual row to the detection code it should trigger and explains why that
situation exists in real enterprise data.

---

## sap_fuel_de_sample.csv

German locale (semicolon delimiter, European decimal: 4.250,500 = 4250.5 liters).

| Row | Plant | Anomaly | Expected Flag | Real-world reason |
|-----|-------|---------|---------------|-------------------|
| 13  | DE03  | Quantity = -250 L, movement type 262 | `SAP_REVERSAL` | Goods Return — fuel issued in error and returned to storage. Legitimate but changes the period net. |
| 14  | DE99  | 45,000 L diesel in one day | `STATISTICAL_SPIKE` + `MISSING_PLANT_CODE` | Either a meter malfunction, a unit mismatch (m³ entered as L), or a legitimate large delivery that must be spread across periods. DE99 also has no plant code lookup entry. |
| 15  | DE01  | Document number 5001234569, same as row 3 | `DUPLICATE_INVOICE` | Classic re-upload: the facilities team exported Jan–Mar and then re-exported the full Q1, sending March twice. |

**Why German headers?** SAP in European subsidiaries almost always exports in
the system language. A German SAP instance with German language packs will
produce Buchungsdatum, Werk, Menge, Einheit — not Posting Date, Plant, etc.
We auto-detect from column names and apply the correct mapping.

**Why semicolons?** German locale uses comma as the decimal separator
(4.250,50 = four thousand two hundred fifty point five). CSV uses comma as
the field delimiter. SAP resolves the conflict by using semicolons as delimiters.

---

## sap_fuel_en_sample.csv

English locale (comma delimiter, US decimal format). Row 6 has no quantity
for the CNG entry — tests `MISSING_UNIT` / null quantity handling.

---

## utility_electricity_sample.csv

| Row | Meter | Anomaly | Expected Flag | Real-world reason |
|-----|-------|---------|---------------|-------------------|
| INV-MUM-DC-* | MTR-INMUM-DC | Unit = MWh (not kWh) | None (normalised correctly) | Large data centres are billed in MWh. Parser must convert. |
| INV-UK-240306 | MTR-UK01-MAIN | Quantity = -120 kWh | `NEGATIVE_QUANTITY` | Solar export on a net-metered site. The utility owes the client for this period. Legitimate but rare. |
| Last row | MTR-INMUM-MAIN | Identical to row 7 (same invoice, same meter, same period) | `DUPLICATE_INVOICE` + `BILLING_OVERLAP` | Facilities team included the same month twice in the export. |
| INV-2024-0205 | MTR-DE01-AUX | `Estimated Read: Yes` | Stored as `is_estimated=True` in parsed output | Meter reader couldn't access the basement. Reading will be corrected next month, potentially triggering `BILLING_OVERLAP`. |

**Why billing periods like Jan 3 → Feb 1?**
Utility billing cycles are triggered by meter reads, not calendar months.
The meter reader visits on whatever day their schedule puts them at that site.
This is the norm, not the exception. GHG reporting requires pro-rating these
periods to fiscal months — we preserve both start and end dates for this reason.

---

## corporate_travel_sample.csv

| Row | Employee | Anomaly | Expected Flag | Real-world reason |
|-----|----------|---------|---------------|-------------------|
| TRP-2024-0101 | EMP-001 | BOM→LHR, no distance | Distance estimated via Haversine (~7,195 km) | Concur doesn't always include distance. Airport codes used for estimation. |
| TRP-2024-0201 | EMP-004 | BOM→JFK, no distance | Estimated (~12,556 km) | Same as above. |
| TRP-2024-0301 | EMP-001 | First class BOM→SIN | No flag; EF = 0.853 kg/pkm vs 0.255 for economy | Emission factor is 3.3× economy. Cabin class matters significantly. |
| TRP-2024-0203 | EMP-006 | LHR→BER rail, no distance | `DISTANCE_NOT_FOUND` | Rail records often have no distance. BER is in our airport table but LHR→BER is a train route, not a flight — Haversine estimation is only applied for AIR type. Analyst must add distance manually. |
| TRP-2024-0305 | EMP-010 | BOM→BOM, 5 km | `IMPLAUSIBLE_FLIGHT_DISTANCE` | Test booking that was never cancelled. 5 km is below the minimum commercial flight distance. |

**Why mix hotels and flights in one file?**
This is how Concur exports work. The admin pulls an expense report for a date
range and gets all expense types in one file. Hotels appear as separate rows
with the same trip ID as the associated flight. Our parser handles this by
dispatching on the `travel_type` / `Expense Type` column, not on file type.

**Why First class on BOM→SIN?**
To demonstrate that cabin class is actually applied. A reviewer who doesn't
understand the emission factor table would expect all flights to have similar
CO₂e per km. Seeing First class at 3.3× Economy in the records table shows
the system is correctly using DEFRA's cabin-class-specific factors.
