import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { format } from "date-fns";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from "recharts";
import { dashboardApi } from "../lib/api";
import { StatCard, Card, CardHeader, StatusBadge, Spinner } from "../components/ui";
import { AlertTriangle, Clock, CheckCircle, XCircle } from "lucide-react";

const SCOPE_COLORS = { 1: "#f97316", 2: "#a855f7", 3: "#38bdf8" };

const SOURCE_LABEL = {
  SAP: "SAP Fuel",
  UTILITY: "Utility",
  TRAVEL: "Travel",
};

const STATUS_ICON = {
  PENDING:   <Clock className="w-3.5 h-3.5 text-slate-400" />,
  PROCESSING:<Clock className="w-3.5 h-3.5 text-blue-400 animate-spin" />,
  PARTIAL:   <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />,
  COMPLETE:  <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />,
  FAILED:    <XCircle className="w-3.5 h-3.5 text-red-400" />,
};

export default function OverviewPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => dashboardApi.summary().then((r) => r.data),
    refetchInterval: 15000, // poll while processing
  });

  if (isLoading) return <Spinner />;

  const { scope_breakdown, recent_uploads } = data;

  const scopeData = [
    { name: "Scope 1", value: scope_breakdown.scope_1, fill: SCOPE_COLORS[1] },
    { name: "Scope 2", value: scope_breakdown.scope_2, fill: SCOPE_COLORS[2] },
    { name: "Scope 3", value: scope_breakdown.scope_3, fill: SCOPE_COLORS[3] },
  ].filter((d) => d.value > 0);

  const reviewData = [
    { name: "Pending",  value: data.pending_review,     fill: "#64748b" },
    { name: "Flagged",  value: data.flagged_suspicious,  fill: "#f59e0b" },
    { name: "Approved", value: data.approved,            fill: "#22c55e" },
    { name: "Rejected", value: data.rejected,            fill: "#ef4444" },
  ];

  return (
    <div className="px-8 py-8 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Overview</h1>
        <p className="mt-1 text-sm text-slate-500">
          Acme Corporation · Emissions ingestion pipeline
        </p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Records" value={data.total_records.toLocaleString()} />
        <StatCard
          label="Pending Review"
          value={data.pending_review.toLocaleString()}
          accent="text-slate-300"
          sub="Awaiting analyst sign-off"
        />
        <StatCard
          label="Flagged"
          value={data.flagged_suspicious.toLocaleString()}
          accent="text-amber-400"
          sub="Suspicious — requires investigation"
        />
        <StatCard
          label="Approved"
          value={data.approved.toLocaleString()}
          accent="text-emerald-400"
          sub="Ready to lock for audit"
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Scope breakdown donut */}
        <Card>
          <CardHeader title="Records by Scope" subtitle="GHG Protocol categorisation" />
          <div className="px-6 py-6 flex items-center gap-8">
            {scopeData.length > 0 ? (
              <>
                <ResponsiveContainer width={160} height={160}>
                  <PieChart>
                    <Pie
                      data={scopeData}
                      cx="50%"
                      cy="50%"
                      innerRadius={50}
                      outerRadius={72}
                      paddingAngle={3}
                      dataKey="value"
                      strokeWidth={0}
                    >
                      {scopeData.map((entry, i) => (
                        <Cell key={i} fill={entry.fill} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ background: "#161b27", border: "1px solid #232b3e", borderRadius: 8, fontSize: 12 }}
                      labelStyle={{ color: "#94a3b8" }}
                      itemStyle={{ color: "#e2e8f0" }}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="space-y-3">
                  {scopeData.map((d) => (
                    <div key={d.name} className="flex items-center gap-3">
                      <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: d.fill }} />
                      <span className="text-sm text-slate-400">{d.name}</span>
                      <span className="ml-auto text-sm font-mono text-slate-200 tabular-nums">{d.value.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="text-sm text-slate-600 py-8 w-full text-center">No records yet — upload data to get started.</p>
            )}
          </div>
        </Card>

        {/* Review status bar */}
        <Card>
          <CardHeader title="Review Status" subtitle="Across all sources" />
          <div className="px-6 py-6">
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={reviewData} barSize={28}>
                <CartesianGrid strokeDasharray="3 3" stroke="#232b3e" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} width={30} />
                <Tooltip
                  contentStyle={{ background: "#161b27", border: "1px solid #232b3e", borderRadius: 8, fontSize: 12 }}
                  cursor={{ fill: "#232b3e" }}
                />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {reviewData.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* Recent uploads */}
      <Card>
        <CardHeader
          title="Recent Uploads"
          subtitle="Last 5 ingestion events"
          action={
            <Link to="/upload" className="text-xs text-teal-400 hover:text-teal-300 transition-colors">
              New upload →
            </Link>
          }
        />
        {recent_uploads.length === 0 ? (
          <p className="px-6 py-8 text-sm text-slate-600 text-center">No uploads yet.</p>
        ) : (
          <div className="divide-y divide-surface-border">
            {recent_uploads.map((upload) => (
              <div key={upload.id} className="flex items-center gap-4 px-6 py-4">
                <div className="flex-shrink-0">
                  {STATUS_ICON[upload.status]}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-slate-300 truncate font-medium">{upload.original_filename}</p>
                  <p className="text-xs text-slate-600 mt-0.5">
                    {SOURCE_LABEL[upload.source_type]} · {upload.uploaded_by_name} ·{" "}
                    {format(new Date(upload.created_at), "d MMM yyyy, HH:mm")}
                  </p>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  {upload.row_count_total != null && (
                    <span className="text-xs text-slate-500 font-mono">
                      {upload.row_count_success}/{upload.row_count_total} rows
                    </span>
                  )}
                  <StatusBadge status={upload.status} />
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Quick action links */}
      <div className="flex gap-3">
        {data.flagged_suspicious > 0 && (
          <Link
            to="/flagged"
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-amber-900/30 border border-amber-800 text-amber-300 text-sm hover:bg-amber-900/50 transition-colors"
          >
            <AlertTriangle className="w-4 h-4" />
            Review {data.flagged_suspicious} flagged record{data.flagged_suspicious !== 1 ? "s" : ""}
          </Link>
        )}
        {data.pending_review > 0 && (
          <Link
            to="/review"
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-teal-900/30 border border-teal-800 text-teal-300 text-sm hover:bg-teal-900/50 transition-colors"
          >
            <CheckCircle className="w-4 h-4" />
            {data.pending_review} pending approval
          </Link>
        )}
      </div>
    </div>
  );
}
