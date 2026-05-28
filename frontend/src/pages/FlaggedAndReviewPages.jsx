import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { recordsApi } from "../lib/api";
import { Card, CardHeader, EmptyState } from "../components/ui";
import RecordsTable from "../components/dashboard/RecordsTable";
import { usePagination, Pagination } from "../hooks/usePagination";

const FLAG_LEGEND = [
  ["NEGATIVE_QUANTITY",          "Negative consumption — physically impossible for fuel/electricity"],
  ["ZERO_QUANTITY",              "Exactly zero — likely a missing value or unfilled placeholder"],
  ["FUTURE_DATE",                "Period is in the future or start/end dates are swapped"],
  ["DATE_TOO_OLD",               "Pre-2015 data — verify intent with client"],
  ["DUPLICATE_INVOICE",          "Invoice ref already ingested — possible re-upload"],
  ["STATISTICAL_SPIKE",          ">3σ from entity's historical mean — meter error or unit mismatch?"],
  ["BILLING_OVERLAP",            "Meter period overlaps existing record — estimated vs actual correction?"],
  ["BILLING_PERIOD_ANOMALY",     "Billing period <20 or >40 days — partial bill or date error?"],
  ["IMPLAUSIBLE_FLIGHT_DISTANCE","Distance <50 km or >20,000 km — impossible route"],
  ["UNKNOWN_AIRPORT",            "Airport code not in lookup — distance could not be estimated"],
  ["DISTANCE_NOT_FOUND",         "No distance and no airport codes — CO₂e cannot be calculated"],
  ["SAP_REVERSAL",               "Movement type 262 — legitimate return, verify net position is correct"],
  ["UNKNOWN_FUEL_TYPE",          "Fuel type not in emission factor table — default factor used"],
];

export function FlaggedPage() {
  const { params, page, pageSize, setPage } = usePagination(50);
  const queryKey = ["records", "flagged", params];
  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () =>
      recordsApi.list({ review_status: "FLAGGED", is_suspicious: true, ...params })
        .then((r) => r.data),
  });

  return (
    <div className="px-8 py-8 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100 flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-amber-400" />
          Flagged Records
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Records automatically flagged during ingestion. Each requires
          analyst investigation before approval.
        </p>
      </div>

      <div className="bg-amber-900/10 border border-amber-800/50 rounded-lg px-5 py-4">
        <p className="text-xs font-semibold text-amber-300 mb-3 uppercase tracking-wider">
          Flag codes reference
        </p>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-8 gap-y-1.5 text-xs">
          {FLAG_LEGEND.map(([code, desc]) => (
            <div key={code} className="flex gap-2">
              <span className="font-mono text-amber-400 shrink-0 w-44">{code}</span>
              <span className="text-slate-500">{desc}</span>
            </div>
          ))}
        </div>
      </div>

      <Card>
        <CardHeader
          title="Suspicious Records"
          subtitle={data ? `${data.count} flagged` : "Loading…"}
        />
        {!isLoading && data?.count === 0 ? (
          <EmptyState icon="✅" title="No flagged records"
            description="All ingested records passed automated checks." />
        ) : (
          <>
            <RecordsTable records={data?.results} isLoading={isLoading}
              queryKey={queryKey} showBulkActions />
            <Pagination page={page} totalPages={data?.total_pages}
              count={data?.count ?? 0} pageSize={pageSize} onPageChange={setPage} />
          </>
        )}
      </Card>
    </div>
  );
}

export function ReviewQueuePage() {
  const { params, page, pageSize, setPage } = usePagination(50);
  const queryKey = ["records", "pending", params];
  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () =>
      recordsApi.list({ review_status: "PENDING", ...params }).then((r) => r.data),
  });

  return (
    <div className="px-8 py-8 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Review Queue</h1>
        <p className="mt-1 text-sm text-slate-500">
          Records that passed automated checks and await analyst sign-off.
          Use bulk approve for batches you've spot-checked.
        </p>
      </div>

      <Card>
        <CardHeader
          title="Pending Review"
          subtitle={data ? `${data.count} awaiting approval` : "Loading…"}
        />
        {!isLoading && data?.count === 0 ? (
          <EmptyState icon="🎉" title="Review queue is empty"
            description="All records have been reviewed." />
        ) : (
          <>
            <RecordsTable records={data?.results} isLoading={isLoading}
              queryKey={queryKey} showBulkActions />
            <Pagination page={page} totalPages={data?.total_pages}
              count={data?.count ?? 0} pageSize={pageSize} onPageChange={setPage} />
          </>
        )}
      </Card>
    </div>
  );
}
