# SOURCES.md

For each of the three sources: what real-world format I researched, what I learned,
what the sample data looks like and why, and what would break in a real deployment.

---

## 1. SAP Fuel / Procurement Data

### What I Researched

SAP has multiple export mechanisms for inventory and procurement data:
- **Transaction MB60**: Goods Issues list — shows material movements (movement type 261 = Goods Issue to Cost Center). This is the most common way to track fuel consumption: fuel is issued from a storage location to a cost center (plant, production line, vehicle fleet).
- **Transaction ME2M / ME2N**: Purchase order reports — shows what was ordered and received.
- **SAP Analytics Cloud / BI**: Many companies extract to BW and then export from there.
- **Z-reports**: Custom ABAP programs that produce flat file extracts to specified field layouts.

I focused on movement type 261 (Goods Issue) exports from MB60-style transactions because:
1. They capture actual consumption (issue date, not order date)
2. They're available in any SAP MM installation
3. The flat file format is standardized (client can control column selection)

### What I Learned

Real SAP CSV exports are unfriendly in specific, predictable ways:
1. **German headers**: SAP's German locale uses "Buchungsdatum" (posting date), "Werk" (plant), "Menge" (quantity), "Einheit" (unit), "Kostenstelle" (cost center), "Belegnummer" (document number). Many European deployments export in German even when the business operates in English.
2. **Semicolon delimiters**: German locale uses semicolons as CSV delimiters (comma is the decimal separator in German number formatting: 4.250,50 = 4250.50).
3. **Decimal formatting**: European SAP exports use periods as thousands separators and commas as decimal separators — the reverse of English convention.
4. **Movement type complexity**: A return (movement type 262) creates a negative quantity in the same export. These look like negative consumption — they're legitimate reversals but trigger our `NEGATIVE_QUANTITY` flag.
5. **Plant codes**: Plant codes like "DE01" or "IN_MUM" are client-specific. They mean nothing without the plant master lookup table.

### What My Sample Data Looks Like and Why

`sap_fuel_de_sample.csv` uses:
- Semicolon delimiter (German locale)
- German column headers
- European decimal formatting (4.250,500 = 4250.5 liters)
- Movement type 262 (return) producing a negative quantity — tests our flag
- An unrecognized plant code (DE99) — tests missing plant code lookup
- A duplicate document number (row 15 = row 3 repeated) — tests duplicate detection
- An implausibly large quantity (45,000 liters in one day at DE99) — tests spike detection

`sap_fuel_en_sample.csv` uses English headers with US decimal formatting — to test
that the SourceMapping system correctly handles both variants without code changes.

### What Would Break in Real Deployment

1. **Decimal parsing at scale**: If even one row has an unexpected decimal format, `Decimal("4,102.75")` raises `InvalidOperation`. We handle this but production would need more robust numeric parsing.
2. **Movement type filtering**: Not all movement types in the export represent consumption. MT-261 = Goods Issue, MT-262 = Return, MT-601 = Goods Issue to Delivery. We only want 261 for fuel consumption but the client's export may include all types.
3. **Material master mapping**: "Diesel" in one plant might be recorded as "B7" (EN 590 diesel grade) or "Kraftstoff" in another. Without material master synchronization, our fuel type normalization degrades.
4. **Plant hierarchy**: Some clients have 200+ plant codes. Our lookup table approach works but needs to be populated. In production, this should sync from the client's SAP plant master (table T001W) on a schedule.

---

## 2. Utility Electricity Data

### What I Researched

Large commercial/industrial electricity consumers in India (MSEDCL, TSSPDCL), UK (Octopus Energy Business, EDF), and Germany (E.ON, RWE) offer self-service portal access where the billing history can be exported as CSV. I looked at:
- **MSEDCL (Maharashtra)**: Portal exports include Account Number, Consumer Number, billing period (in calendar months), Units Consumed (kWh), and Invoice Number.
- **EDF UK**: Exports include Meter MPAN (Meter Point Administration Number), half-hourly or monthly usage, tariff code, billing period start/end.
- **E.ON Germany**: Similar to EDF; includes Zählernummer (meter number), Verbrauch (consumption), Abrechnungszeitraum (billing period).

The consistent challenge across all three: **billing periods do not align with calendar months**. Utility billing cycles are triggered by meter reads, which drift. A monthly bill might cover 27–34 days. This matters for GHG reporting because the client's fiscal year (Jan–Dec or Apr–Mar) needs to be reconstructed from overlapping billing periods.

### What I Learned

Key facts that shaped my sample data:
1. **Billing period drift**: A meter read happens on whatever day the meter reader visits. The billing period is from the previous read to the current read. This is rarely the 1st to the last of the month.
2. **Estimated reads**: When the utility can't access the meter, they estimate the reading. Estimated reads are flagged in the export (often a "Y/N" column). These should be flagged for analyst review because they may be corrected in the next bill, creating a billing overlap.
3. **Unit variation**: Most commercial meters use kWh. Large industrial consumers (data centers, factories) may be billed in MWh. Some older industrial tariffs use kVAh (kilovolt-ampere-hours, which accounts for power factor).
4. **Negative consumption**: Smart solar installations can export electricity. A net-metered facility may have negative net consumption in some months. This is legitimate but rare — we flag it.
5. **Multiple meters per site**: Large buildings have multiple sub-meters (HVAC, lighting, elevators). These need to be aggregated per site for reporting, but we store them individually for accuracy.

### What My Sample Data Looks Like and Why

`utility_electricity_sample.csv` includes:
- `MTR-INMUM-DC`: Mumbai data center billed in MWh — tests energy unit conversion (MWh → kWh)
- Billing periods that start on the 3rd, 7th, and 5th — deliberately not 1st of month
- `INV-UK-240306`: Negative kWh (-120) from London office — tests `NEGATIVE_QUANTITY` flag
- `INV-MUM-240101`: Duplicate row (same invoice, same meter, same period) — tests `DUPLICATE_INVOICE` and `BILLING_OVERLAP` detection
- `Estimated Read: Yes` flag on one row — an analyst note that this read was estimated

### What Would Break in Real Deployment

1. **Overlapping billing periods after corrections**: When a utility corrects an estimated read, they issue a "catch-up" bill for the difference. This creates overlapping periods that need intelligent merging, not duplication.
2. **Half-hourly data**: UK mandatory half-hourly metering (Profile Class 00) produces 48 readings per day. A year is 17,520 rows per meter. Our current model handles this (each row = one RawRecord) but the volume is 500x higher than monthly billing.
3. **International tariff complexity**: Indian HT consumers have multiple tariff components (demand charges, TOD charges, reactive energy charges) in addition to units consumed. Our model stores one `tariff` field — insufficient for tariff reconstruction.
4. **PDF bills**: Many smaller facilities teams don't have portal access and receive PDF bills. This requires OCR + structure extraction — a completely different ingestion path.

---

## 3. Corporate Travel Data

### What I Researched

The major corporate travel platforms — SAP Concur, Navan (formerly TripActions), TravelPerk, Egencia, and American Express Global Business Travel — all have admin export/reporting functionality.

I reviewed:
- **SAP Concur Travel**: Expense Report export includes `Employee ID`, `Transaction Date`, `Expense Type`, `Merchant/Vendor`, `Amount`, and for travel-specific fields: `Origin City`, `Destination City`, `Airline`, `Cabin Type`, `Miles`. The Concur Intelligence reporting module allows custom exports including trip-level fields.
- **Navan**: Trip data export includes `traveler_id`, `booking_type` (Flight/Hotel/Car), `depart_date`, `arrive_date`, `from_location` (city or airport code), `to_location`, `carbon_kg` (Navan calculates and exports this natively).
- **IATA data**: Flights are identified by airport codes (BOM, LHR) or city pairs. Distances are not always provided — some exports give the airport pair and expect the recipient to look up distance.

Key insight from Navan: **some platforms now export their own carbon estimate**. We ignore this and recalculate — we don't trust third-party carbon calculations for audit purposes unless we know and can cite the methodology.

### What My Sample Data Looks Like and Why

`corporate_travel_sample.csv` includes:
- **Mixed travel types** in one file (flights, hotels, ground transport, rail) — this is realistic; Concur mixes expense types in one report
- **Missing distances for some flights** (BOM→LHR, BOM→JFK) — tests the airport-code-to-distance estimation path
- **Provided distances for others** (DEL→FRA, LAX→ORD) — tests that provided distances are used without overriding
- **First class travel** (BOM→SIN) — tests that cabin class is applied to the emission factor (First class is ~3x Economy)
- **A suspicious short flight** (BOM→BOM, 5km) — tests `IMPLAUSIBLE_FLIGHT_DISTANCE` flag
- **Rail travel** (LHR→BER with no distance) — tests the unknown-distance case for non-air travel
- **Hotel stays** as separate rows with the same trip ID as the flight — tests that trip_id grouping works in the frontend

### What Would Break in Real Deployment

1. **Multi-leg itineraries**: A flight from BOM to JFK might route BOM→FRA→JFK. Concur may export this as two rows or one row. If two rows, we double-count unless we de-duplicate on trip segment, not trip ID.
2. **Airport code ambiguity**: "ORD" is unambiguous. "BLR" could be Bangalore (IATA: BLR) or Belém, Brazil (IATA: BEL). Our lookup table handles this correctly for the airports we've indexed, but an unfamiliar code returns None distance and triggers a flag.
3. **Hotel carbon by property**: The DEFRA flat rate per room-night (31 kg CO2e) is a rough average. Premium hotels in high-carbon grids (e.g., coal-heavy regions) can be 2-3x higher. Navan and some other platforms have property-level carbon data we don't access.
4. **Non-Concur/Navan platforms**: If the client uses a regional travel platform (e.g., MakeMyTrip for Business in India), the export format will differ. We'd need a new `SourceMapping` configuration.
5. **Currency normalization**: Our sample has costs in USD. Real data will mix currencies. We don't use costs for emission calculation, but storing them consistently matters for spend-based verification.
