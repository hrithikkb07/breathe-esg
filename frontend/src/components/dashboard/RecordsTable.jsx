import { useState } from "react";
import { format } from "date-fns";
import { CheckCircle, XCircle, Eye } from "lucide-react";
import {
  StatusBadge, ScopeBadge, SuspiciousBadge,
  Button, Select, Modal, Textarea, Spinner, EmptyState,
} from "../ui";
import { recordsApi } from "../../lib/api";
import { useMutation, useQueryClient } from "@tanstack/react-query";

const CATEGORY_LABEL = {
  STATIONARY_COMBUSTION:  "Stationary Combustion",
  PURCHASED_ELECTRICITY:  "Purchased Electricity",
  BUSINESS_TRAVEL_AIR:    "Air Travel",
  BUSINESS_TRAVEL_HOTEL:  "Hotel",
  BUSINESS_TRAVEL_RAIL:   "Rail",
  BUSINESS_TRAVEL_GROUND: "Ground Transport",
};

// ── Record Detail Modal ───────────────────────────────────────────────────────
function RecordDetailModal({ record, onClose, queryKey }) {
  const qc = useQueryClient();
  const [notes, setNotes] = useState("");
  const [pendingAction, setPendingAction] = useState(null); // "APPROVE" | "REJECT"

  const reviewMutation = useMutation({
    mutationFn: ({ action, notes }) => recordsApi.review(record.id, { action, notes }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey });
      qc.invalidateQueries({ queryKey: ["dashboard-summary"] });
      onClose();
    },
  });

  const handleReview = (action) => {
    if (action === "REJECT" && !notes.trim()) return;
    reviewMutation.mutate({ action, notes });
  };

  const raw = record;

  return (
    <Modal open onClose={onClose} title="Record Detail" width="max-w-2xl">
      <div className="space-y-5">
        {/* Identity */}
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-surface-muted rounded-md px-3 py-2.5">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Scope</p>
            <ScopeBadge scope={raw.scope} />
          </div>
          <div className="bg-surface-muted rounded-md px-3 py-2.5">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Category</p>
            <p className="text-xs text-slate-300">{CATEGORY_LABEL[raw.emission_category] || raw.emission_category}</p>
          </div>
          <div className="bg-surface-muted rounded-md px-3 py-2.5">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Status</p>
            <StatusBadge status={raw.review_status} />
          </div>
        </div>

        {/* Activity data */}
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-surface-muted rounded-md px-3 py-2.5">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Activity</p>
            <p className="text-sm font-mono text-slate-200">
              {Number(raw.activity_quantity).toLocaleString()} {raw.activity_unit}
            </p>
            {raw.original_unit && raw.original_unit !== raw.activity_unit && (
              <p className="text-xs text-slate-600 mt-0.5">
                Original: {raw.original_quantity} {raw.original_unit}
              </p>
            )}
          </div>
          <div className="bg-surface-muted rounded-md px-3 py-2.5">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">CO₂e</p>
            <p className="text-sm font-mono text-slate-200">
              {raw.co2e_tonnes ? `${Number(raw.co2e_tonnes).toFixed(4)} t` : "—"}
            </p>
            {raw.emission_factor_source && (
              <p className="text-xs text-slate-600 mt-0.5">{raw.emission_factor_source}</p>
            )}
          </div>
          <div className="bg-surface-muted rounded-md px-3 py-2.5">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Period</p>
            <p className="text-sm text-slate-200">
              {raw.period_start} → {raw.period_end}
            </p>
          </div>
          <div className="bg-surface-muted rounded-md px-3 py-2.5">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Source Entity</p>
            <p className="text-sm text-slate-200">{raw.source_entity_id || "—"}</p>
            {raw.source_entity_name && (
              <p className="text-xs text-slate-600 mt-0.5">{raw.source_entity_name}</p>
            )}
          </div>
          {(raw.origin_code || raw.destination_code) && (
            <div className="bg-surface-muted rounded-md px-3 py-2.5">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Route</p>
              <p className="text-sm font-mono text-slate-200">
                {raw.origin_code} → {raw.destination_code}
              </p>
              {raw.distance_km && (
                <p className="text-xs text-slate-600 mt-0.5">
                  {Number(raw.distance_km).toLocaleString()} km
                  {raw.distance_is_estimated && " (estimated)"}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Suspicious flags */}
        {raw.is_suspicious && raw.suspicious_reasons?.length > 0 && (
          <div className="border border-amber-800 bg-amber-900/20 rounded-md px-4 py-3 space-y-2">
            <p className="text-xs font-semibold text-amber-300 uppercase tracking-wider">Suspicious flags</p>
            {raw.suspicious_reasons.map((f, i) => (
              <div key={i}>
                <p className="text-xs font-mono text-amber-400">{f.code}</p>
                <p className="text-xs text-amber-300/70 mt-0.5">{f.detail}</p>
              </div>
            ))}
          </div>
        )}

        {/* Provenance */}
        <div className="text-xs text-slate-600 border-t border-surface-border pt-3 space-y-1 font-mono">
          <p>Source file: <span className="text-slate-400">{raw.upload_filename}</span></p>
          <p>Upload ID: <span className="text-slate-400">{raw.upload_id}</span></p>
          <p>Record ID: <span className="text-slate-400">{raw.id}</span></p>
        </div>

        {/* Review actions */}
        {!raw.is_locked && raw.review_status !== "APPROVED" && raw.review_status !== "REJECTED" && (
          <div className="border-t border-surface-border pt-4 space-y-3">
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">
                Notes{raw.review_status === "FLAGGED" ? " (explain your decision)" : " (optional)"}
              </label>
              <Textarea
                value={notes}
                onChange={setNotes}
                placeholder="Add context for this decision…"
                rows={2}
              />
            </div>
            <div className="flex gap-3">
              <Button
                variant="primary"
                size="sm"
                loading={reviewMutation.isPending && pendingAction === "APPROVE"}
                onClick={() => { setPendingAction("APPROVE"); handleReview("APPROVE"); }}
              >
                <CheckCircle className="w-3.5 h-3.5" />
                Approve
              </Button>
              <Button
                variant="danger"
                size="sm"
                disabled={!notes.trim()}
                loading={reviewMutation.isPending && pendingAction === "REJECT"}
                onClick={() => { setPendingAction("REJECT"); handleReview("REJECT"); }}
              >
                <XCircle className="w-3.5 h-3.5" />
                Reject
              </Button>
              <p className="text-xs text-slate-600 self-center">
                Rejection requires a reason.
              </p>
            </div>
          </div>
        )}

        {raw.is_locked && (
          <p className="text-xs text-slate-600 border-t border-surface-border pt-3">
            🔒 This record is locked and cannot be modified.
          </p>
        )}

        {raw.review_notes && (
          <div className="text-xs text-slate-500 border-t border-surface-border pt-3">
            <span className="text-slate-400 font-medium">Review note:</span> {raw.review_notes}
          </div>
        )}
      </div>
    </Modal>
  );
}

// ── Main Records Table ────────────────────────────────────────────────────────
export default function RecordsTable({
  records,
  isLoading,
  queryKey,
  showBulkActions = false,
  emptyMessage = "No records found.",
}) {
  const [selected, setSelected] = useState([]);
  const [detailRecord, setDetailRecord] = useState(null);
  const [bulkNotes, setBulkNotes] = useState("");
  const qc = useQueryClient();

  const toggleSelect = (id) =>
    setSelected((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);

  const toggleAll = () =>
    setSelected((s) => s.length === records.length ? [] : records.map((r) => r.id));

  const bulkMutation = useMutation({
    mutationFn: ({ action }) =>
      recordsApi.bulkReview({ record_ids: selected, action, notes: bulkNotes }),
    onSuccess: () => {
      setSelected([]);
      setBulkNotes("");
      qc.invalidateQueries({ queryKey });
      qc.invalidateQueries({ queryKey: ["dashboard-summary"] });
    },
  });

  if (isLoading) return <Spinner />;
  if (!records?.length) return <EmptyState title={emptyMessage} />;

  const unlocked = records.filter((r) => !r.is_locked && !["APPROVED","REJECTED"].includes(r.review_status));

  return (
    <div>
      {/* Bulk action bar */}
      {showBulkActions && selected.length > 0 && (
        <div className="flex items-center gap-3 px-4 py-3 bg-teal-900/20 border border-teal-800 rounded-lg mb-4">
          <span className="text-sm text-teal-300 font-medium">{selected.length} selected</span>
          <input
            type="text"
            value={bulkNotes}
            onChange={(e) => setBulkNotes(e.target.value)}
            placeholder="Optional notes for bulk action…"
            className="flex-1 bg-surface-muted border border-surface-border text-slate-300 text-sm rounded px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-teal-500 placeholder:text-slate-600"
          />
          <Button size="sm" onClick={() => bulkMutation.mutate({ action: "APPROVE" })} loading={bulkMutation.isPending}>
            <CheckCircle className="w-3.5 h-3.5" /> Approve all
          </Button>
          <Button size="sm" variant="danger" disabled={!bulkNotes.trim()} onClick={() => bulkMutation.mutate({ action: "REJECT" })}>
            <XCircle className="w-3.5 h-3.5" /> Reject all
          </Button>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-surface-border">
              {showBulkActions && (
                <th className="pl-4 py-3 w-8">
                  <input
                    type="checkbox"
                    checked={selected.length === unlocked.length && unlocked.length > 0}
                    onChange={toggleAll}
                    className="accent-teal-500"
                  />
                </th>
              )}
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Scope / Category</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Entity</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Period</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">Activity</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">CO₂e (t)</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Status</th>
              <th className="px-4 py-3 w-8" />
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-border">
            {records.map((r) => (
              <tr
                key={r.id}
                className="hover:bg-surface-muted/50 transition-colors cursor-pointer"
                onClick={() => {
                  recordsApi.detail(r.id).then((res) => setDetailRecord(res.data));
                }}
              >
                {showBulkActions && (
                  <td className="pl-4 py-3" onClick={(e) => e.stopPropagation()}>
                    {!r.is_locked && !["APPROVED","REJECTED"].includes(r.review_status) && (
                      <input
                        type="checkbox"
                        checked={selected.includes(r.id)}
                        onChange={() => toggleSelect(r.id)}
                        className="accent-teal-500"
                      />
                    )}
                  </td>
                )}
                <td className="px-4 py-3">
                  <div className="flex flex-col gap-1">
                    <ScopeBadge scope={r.scope} />
                    <span className="text-xs text-slate-500">{CATEGORY_LABEL[r.emission_category] || r.emission_category}</span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <p className="text-slate-300 font-mono text-xs">{r.source_entity_id || "—"}</p>
                  {r.source_entity_name && <p className="text-slate-600 text-xs mt-0.5 truncate max-w-[140px]">{r.source_entity_name}</p>}
                  {(r.origin_code && r.destination_code) && (
                    <p className="text-slate-500 text-xs font-mono">{r.origin_code}→{r.destination_code}</p>
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500 font-mono whitespace-nowrap">
                  {r.period_start}<br />{r.period_end !== r.period_start && `→ ${r.period_end}`}
                </td>
                <td className="px-4 py-3 text-right font-mono text-xs text-slate-300 whitespace-nowrap">
                  {Number(r.activity_quantity).toLocaleString(undefined, { maximumFractionDigits: 2 })} {r.activity_unit}
                </td>
                <td className="px-4 py-3 text-right font-mono text-xs text-slate-300 whitespace-nowrap">
                  {r.co2e_tonnes ? Number(r.co2e_tonnes).toFixed(4) : "—"}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-col gap-1">
                    <StatusBadge status={r.review_status} />
                    {r.is_suspicious && <SuspiciousBadge />}
                    {r.is_locked && <span className="text-[10px] text-slate-600">🔒 locked</span>}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <Eye className="w-3.5 h-3.5 text-slate-600" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {detailRecord && (
        <RecordDetailModal
          record={detailRecord}
          onClose={() => setDetailRecord(null)}
          queryKey={queryKey}
        />
      )}
    </div>
  );
}
