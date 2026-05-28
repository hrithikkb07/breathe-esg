import { useState, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { Upload, FileText, CheckCircle, AlertTriangle, XCircle, Clock, ChevronDown, ChevronRight } from "lucide-react";
import { uploadsApi } from "../lib/api";
import { Button, Card, CardHeader, StatusBadge, Select, Spinner, Modal } from "../components/ui";
import { clsx } from "clsx";

const SOURCE_OPTIONS = [
  { value: "SAP",     label: "SAP Fuel / Procurement" },
  { value: "UTILITY", label: "Utility Electricity" },
  { value: "TRAVEL",  label: "Corporate Travel" },
];

const SOURCE_HINTS = {
  SAP:
    "CSV export from SAP MB60 or custom Z-report. Accepts English or German headers, " +
    "comma or semicolon delimiter, European (1.234,56) or US (1,234.56) number format.",
  UTILITY:
    "Portal CSV export (E.ON, EDF, MSEDCL, etc.). Expects billing period start/end dates " +
    "and a usage/consumption column. kWh and MWh both accepted.",
  TRAVEL:
    "Concur / Navan / TravelPerk trip export. Handles flights, hotels, rail, and ground " +
    "transport. Airport IATA codes used for distance estimation when distance column is absent.",
};

const STATUS_ICON = {
  PENDING:    <Clock className="w-4 h-4 text-slate-400" />,
  PROCESSING: <Clock className="w-4 h-4 text-blue-400 animate-spin" />,
  PARTIAL:    <AlertTriangle className="w-4 h-4 text-amber-400" />,
  COMPLETE:   <CheckCircle className="w-4 h-4 text-emerald-400" />,
  FAILED:     <XCircle className="w-4 h-4 text-red-400" />,
};

// ── Failed Rows Modal ─────────────────────────────────────────────────────────
function FailedRowsModal({ uploadId, onClose }) {
  const { data, isLoading } = useQuery({
    queryKey: ["failed-rows", uploadId],
    queryFn: () => uploadsApi.failedRows(uploadId).then((r) => r.data),
    enabled: !!uploadId,
  });

  return (
    <Modal open onClose={onClose} title="Failed Rows" width="max-w-3xl">
      {isLoading ? (
        <Spinner />
      ) : data?.length === 0 ? (
        <p className="text-sm text-slate-500 py-4">No failed rows for this upload.</p>
      ) : (
        <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
          <p className="text-xs text-slate-500">
            {data.length} row{data.length !== 1 ? "s" : ""} failed to parse. The raw
            data is preserved below — use it to diagnose the source file.
          </p>
          {data.map((row) => (
            <div key={row.id} className="bg-surface-muted rounded-md border border-surface-border p-4">
              <div className="flex items-start justify-between mb-2">
                <span className="text-xs font-mono text-slate-400">Row {row.row_number}</span>
                <span className="text-xs text-red-400 font-medium">{row.parse_error}</span>
              </div>
              <pre className="text-[10px] text-slate-600 overflow-x-auto whitespace-pre-wrap break-all">
                {JSON.stringify(row.raw_data, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

// ── Upload History Row ────────────────────────────────────────────────────────
function UploadHistoryRow({ u }) {
  const [expanded, setExpanded] = useState(false);
  const [showFailed, setShowFailed] = useState(false);

  return (
    <>
      <div className="flex items-center gap-4 px-6 py-4">
        <div className="flex-shrink-0">{STATUS_ICON[u.status]}</div>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-300 truncate font-medium">{u.original_filename}</p>
          <p className="text-xs text-slate-600 mt-0.5">
            {u.source_type} · {u.uploaded_by_name} ·{" "}
            {format(new Date(u.created_at), "d MMM yyyy, HH:mm")}
          </p>
          {u.error_message && (
            <p className="text-xs text-red-400 mt-0.5 truncate">{u.error_message}</p>
          )}
        </div>

        <div className="flex items-center gap-4 flex-shrink-0">
          {u.row_count_total != null && (
            <div className="text-xs font-mono text-right space-y-0.5">
              <p className="text-slate-400">{u.row_count_success} ok</p>
              {u.row_count_failed > 0 && (
                <button
                  onClick={() => setShowFailed(true)}
                  className="text-red-400 hover:text-red-300 underline underline-offset-2"
                >
                  {u.row_count_failed} failed
                </button>
              )}
              {u.row_count_suspicious > 0 && (
                <p className="text-amber-400">{u.row_count_suspicious} flagged</p>
              )}
            </div>
          )}
          <StatusBadge status={u.status} />
        </div>
      </div>

      {showFailed && (
        <FailedRowsModal uploadId={u.id} onClose={() => setShowFailed(false)} />
      )}
    </>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function UploadPage() {
  const qc = useQueryClient();
  const fileRef = useRef();
  const [sourceType, setSourceType] = useState("SAP");
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [result, setResult] = useState(null);

  const { data: uploads, isLoading: historyLoading } = useQuery({
    queryKey: ["uploads"],
    queryFn: () => uploadsApi.list({ page_size: 30 }).then((r) => r.data.results),
  });

  const mutation = useMutation({
    mutationFn: (fd) => uploadsApi.upload(fd),
    onSuccess: (res) => {
      setResult({ ok: true, data: res.data });
      setSelectedFile(null);
      qc.invalidateQueries({ queryKey: ["uploads"] });
      qc.invalidateQueries({ queryKey: ["dashboard-summary"] });
    },
    onError: (err) => {
      setResult({ ok: false, message: err.response?.data?.detail || "Upload failed." });
    },
  });

  const handleFile = (file) => {
    if (!file?.name.endsWith(".csv")) {
      setResult({ ok: false, message: "Only CSV files are supported." });
      return;
    }
    if (file.size > 100 * 1024 * 1024) {
      setResult({ ok: false, message: "File exceeds 100 MB limit." });
      return;
    }
    setSelectedFile(file);
    setResult(null);
  };

  const handleSubmit = () => {
    if (!selectedFile) return;
    const fd = new FormData();
    fd.append("file", selectedFile);
    fd.append("source_type", sourceType);
    mutation.mutate(fd);
  };

  return (
    <div className="px-8 py-8 max-w-4xl space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Upload Data</h1>
        <p className="mt-1 text-sm text-slate-500">
          Ingest a CSV from SAP, a utility portal, or a corporate travel platform.
        </p>
      </div>

      <Card>
        <CardHeader title="New Upload" subtitle="CSV files only · 100 MB limit" />
        <div className="px-6 py-6 space-y-5">
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-2">Data source</label>
            <Select value={sourceType} onChange={setSourceType}
              options={SOURCE_OPTIONS} className="w-64" />
            <p className="mt-2 text-xs text-slate-600 max-w-lg">{SOURCE_HINTS[sourceType]}</p>
          </div>

          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]); }}
            onClick={() => fileRef.current.click()}
            className={clsx(
              "border-2 border-dashed rounded-lg px-8 py-12 flex flex-col items-center gap-3 cursor-pointer transition-colors",
              dragOver ? "border-teal-500 bg-teal-500/5"
                : selectedFile ? "border-teal-700 bg-teal-900/10"
                : "border-surface-border hover:border-slate-500"
            )}
          >
            <input ref={fileRef} type="file" accept=".csv" className="hidden"
              onChange={(e) => handleFile(e.target.files[0])} />
            {selectedFile ? (
              <>
                <FileText className="w-8 h-8 text-teal-400" />
                <p className="text-sm font-medium text-teal-300">{selectedFile.name}</p>
                <p className="text-xs text-slate-500">
                  {(selectedFile.size / 1024).toFixed(1)} KB · Click to change
                </p>
              </>
            ) : (
              <>
                <Upload className="w-8 h-8 text-slate-600" />
                <p className="text-sm text-slate-400">Drop a CSV here, or click to browse</p>
                <p className="text-xs text-slate-600">Max 100 MB</p>
              </>
            )}
          </div>

          {result && (
            <div className={clsx(
              "rounded-md px-4 py-3 text-sm border",
              result.ok
                ? "bg-emerald-900/20 border-emerald-800 text-emerald-300"
                : "bg-red-900/20 border-red-800 text-red-300"
            )}>
              {result.ok ? (
                <div className="space-y-1">
                  <p className="font-medium">Upload complete — {result.data.status}</p>
                  <p className="text-xs opacity-80">
                    {result.data.row_count_success} rows ingested ·{" "}
                    {result.data.row_count_failed} failed ·{" "}
                    {result.data.row_count_suspicious} flagged suspicious
                  </p>
                </div>
              ) : (
                <p>{result.message}</p>
              )}
            </div>
          )}

          <Button onClick={handleSubmit} disabled={!selectedFile} loading={mutation.isPending}>
            <Upload className="w-4 h-4" />
            {mutation.isPending ? "Processing…" : "Upload and ingest"}
          </Button>
        </div>
      </Card>

      <Card>
        <CardHeader title="Ingestion History" subtitle="All uploads for this tenant" />
        {historyLoading ? <Spinner /> : uploads?.length === 0 ? (
          <p className="px-6 py-10 text-sm text-slate-600 text-center">No uploads yet.</p>
        ) : (
          <div className="divide-y divide-surface-border">
            {uploads?.map((u) => <UploadHistoryRow key={u.id} u={u} />)}
          </div>
        )}
      </Card>
    </div>
  );
}
