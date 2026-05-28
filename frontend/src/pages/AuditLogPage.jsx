import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import { auditApi } from "../lib/api";
import { Card, CardHeader, Spinner, EmptyState } from "../components/ui";

const ACTION_COLOR = {
  UPLOAD_CREATED:    "text-sky-400",
  UPLOAD_COMPLETE:   "text-emerald-400",
  UPLOAD_FAILED:     "text-red-400",
  RECORD_APPROVED:   "text-emerald-400",
  RECORD_REJECTED:   "text-red-400",
  RECORD_FLAGGED:    "text-amber-400",
  RECORD_LOCKED:     "text-purple-400",
  RECORD_SUPERSEDED: "text-slate-400",
};

export default function AuditLogPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["audit-log"],
    queryFn: () => auditApi.list({ page_size: 200 }).then((r) => r.data.results),
    refetchInterval: 10000,
  });

  return (
    <div className="px-8 py-8 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Audit Log</h1>
        <p className="mt-1 text-sm text-slate-500">
          Append-only record of all state changes. Entries cannot be modified or deleted.
        </p>
      </div>

      <Card>
        <CardHeader
          title="Event Log"
          subtitle={data ? `${data.length} events` : "Loading…"}
        />
        {isLoading ? (
          <Spinner />
        ) : data?.length === 0 ? (
          <EmptyState title="No audit events yet." />
        ) : (
          <div className="divide-y divide-surface-border font-mono text-xs">
            {data.map((entry) => (
              <div key={entry.id} className="flex gap-4 px-6 py-3 hover:bg-surface-muted/30">
                {/* ID */}
                <span className="text-slate-700 w-10 shrink-0 text-right">#{entry.id}</span>
                {/* Timestamp */}
                <span className="text-slate-600 shrink-0 w-36">
                  {format(new Date(entry.created_at), "dd MMM HH:mm:ss")}
                </span>
                {/* Action */}
                <span className={`shrink-0 w-36 ${ACTION_COLOR[entry.action] || "text-slate-400"}`}>
                  {entry.action}
                </span>
                {/* Resource */}
                <span className="text-slate-500 shrink-0 w-44 truncate">
                  {entry.resource_type}:{entry.resource_id.slice(0, 8)}…
                </span>
                {/* Actor */}
                <span className="text-slate-600 shrink-0 w-20">{entry.actor_name || "system"}</span>
                {/* Payload summary */}
                <span className="text-slate-700 truncate">
                  {Object.keys(entry.payload).length > 0
                    ? JSON.stringify(entry.payload).slice(0, 80)
                    : ""}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
