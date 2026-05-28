import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { recordsApi } from "../lib/api";
import { Card, CardHeader, Select } from "../components/ui";
import RecordsTable from "../components/dashboard/RecordsTable";
import { usePagination, Pagination } from "../hooks/usePagination";

const SCOPE_OPTIONS = [
  { value: "1", label: "Scope 1 — Direct" },
  { value: "2", label: "Scope 2 — Purchased Energy" },
  { value: "3", label: "Scope 3 — Value Chain" },
];
const STATUS_OPTIONS = [
  { value: "PENDING",  label: "Pending" },
  { value: "FLAGGED",  label: "Flagged" },
  { value: "APPROVED", label: "Approved" },
  { value: "REJECTED", label: "Rejected" },
];

export default function RecordsPage() {
  const [filters, setFilters] = useState({ scope: "", review_status: "" });
  const { params, page, pageSize, setPage, reset } = usePagination(50);

  const set = (key) => (val) => {
    setFilters((f) => ({ ...f, [key]: val }));
    reset();
  };

  const queryKey = ["records", filters, params];
  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () =>
      recordsApi.list({ ...filters, ...params }).then((r) => r.data),
  });

  return (
    <div className="px-8 py-8 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">All Records</h1>
        <p className="mt-1 text-sm text-slate-500">
          Every normalized emission record across all sources.
        </p>
      </div>

      <Card>
        <CardHeader
          title="Records"
          subtitle={data ? `${data.count.toLocaleString()} records` : "Loading…"}
          action={
            <div className="flex items-center gap-2">
              <Select
                value={filters.scope}
                onChange={set("scope")}
                options={SCOPE_OPTIONS}
                placeholder="All scopes"
                className="w-44"
              />
              <Select
                value={filters.review_status}
                onChange={set("review_status")}
                options={STATUS_OPTIONS}
                placeholder="All statuses"
                className="w-36"
              />
            </div>
          }
        />
        <RecordsTable
          records={data?.results}
          isLoading={isLoading}
          queryKey={queryKey}
          emptyMessage="No records match the selected filters."
        />
        <Pagination
          page={page}
          totalPages={data?.total_pages}
          count={data?.count ?? 0}
          pageSize={pageSize}
          onPageChange={setPage}
        />
      </Card>
    </div>
  );
}
