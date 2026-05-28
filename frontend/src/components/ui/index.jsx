import { clsx } from "clsx";

// ── Badge ─────────────────────────────────────────────────────────────────────
const STATUS_STYLES = {
  PENDING:  "bg-slate-700/60 text-slate-300 border border-slate-600",
  FLAGGED:  "bg-amber-900/50 text-amber-300 border border-amber-700",
  APPROVED: "bg-emerald-900/50 text-emerald-300 border border-emerald-700",
  REJECTED: "bg-red-900/50 text-red-300 border border-red-700",
};

const SCOPE_STYLES = {
  1: "bg-orange-900/40 text-orange-300 border border-orange-800",
  2: "bg-purple-900/40 text-purple-300 border border-purple-800",
  3: "bg-sky-900/40 text-sky-300 border border-sky-800",
};

export function StatusBadge({ status }) {
  return (
    <span className={clsx(
      "inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium tracking-wide",
      STATUS_STYLES[status] || STATUS_STYLES.PENDING
    )}>
      {status}
    </span>
  );
}

export function ScopeBadge({ scope }) {
  return (
    <span className={clsx(
      "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium",
      SCOPE_STYLES[scope]
    )}>
      Scope {scope}
    </span>
  );
}

export function SuspiciousBadge() {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-amber-900/50 text-amber-300 border border-amber-700">
      <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
      Flagged
    </span>
  );
}

// ── Button ────────────────────────────────────────────────────────────────────
const BTN_VARIANTS = {
  primary:  "bg-teal-500 hover:bg-teal-400 text-slate-900 font-semibold",
  secondary:"bg-surface-muted hover:bg-surface-border text-slate-300 border border-surface-border",
  danger:   "bg-red-600 hover:bg-red-500 text-white font-semibold",
  ghost:    "hover:bg-surface-muted text-slate-400 hover:text-slate-200",
};

export function Button({ variant = "primary", size = "md", className, disabled, loading, children, ...props }) {
  const sizeClass = size === "sm" ? "px-3 py-1.5 text-sm" : size === "lg" ? "px-6 py-3 text-base" : "px-4 py-2 text-sm";
  return (
    <button
      className={clsx(
        "inline-flex items-center gap-2 rounded-md transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed",
        BTN_VARIANTS[variant],
        sizeClass,
        className
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading && (
        <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
      )}
      {children}
    </button>
  );
}

// ── Card ──────────────────────────────────────────────────────────────────────
export function Card({ className, children }) {
  return (
    <div className={clsx("bg-surface-raised border border-surface-border rounded-lg", className)}>
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, action }) {
  return (
    <div className="flex items-start justify-between px-6 py-5 border-b border-surface-border">
      <div>
        <h2 className="text-sm font-semibold text-slate-200 tracking-wide uppercase">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

// ── Table ─────────────────────────────────────────────────────────────────────
export function Table({ columns, data, onRowClick, emptyMessage = "No records found." }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-surface-border">
            {columns.map((col) => (
              <th
                key={col.key}
                className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider whitespace-nowrap"
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-border">
          {data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-12 text-center text-slate-600 text-sm">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            data.map((row, i) => (
              <tr
                key={row.id || i}
                onClick={() => onRowClick?.(row)}
                className={clsx(
                  "transition-colors duration-75",
                  onRowClick && "cursor-pointer hover:bg-surface-muted"
                )}
              >
                {columns.map((col) => (
                  <td key={col.key} className="px-4 py-3 text-slate-300 whitespace-nowrap">
                    {col.render ? col.render(row[col.key], row) : row[col.key] ?? "—"}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── Stat Card ─────────────────────────────────────────────────────────────────
export function StatCard({ label, value, sub, accent }) {
  return (
    <Card className="px-6 py-5">
      <p className="text-xs text-slate-500 uppercase tracking-wider font-medium">{label}</p>
      <p className={clsx("mt-2 text-3xl font-mono font-bold tabular-nums", accent || "text-slate-100")}>
        {value ?? "—"}
      </p>
      {sub && <p className="mt-1 text-xs text-slate-600">{sub}</p>}
    </Card>
  );
}

// ── Loading Spinner ───────────────────────────────────────────────────────────
export function Spinner({ className }) {
  return (
    <div className={clsx("flex items-center justify-center py-16", className)}>
      <div className="w-6 h-6 border-2 border-teal-500 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

// ── Empty State ───────────────────────────────────────────────────────────────
export function EmptyState({ icon, title, description, action }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      {icon && <div className="text-slate-600 mb-4 text-4xl">{icon}</div>}
      <p className="text-slate-400 font-medium">{title}</p>
      {description && <p className="mt-1 text-sm text-slate-600 max-w-xs">{description}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

// ── Select / Filter ───────────────────────────────────────────────────────────
export function Select({ value, onChange, options, placeholder, className }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={clsx(
        "bg-surface-muted border border-surface-border text-slate-300 text-sm rounded-md px-3 py-2",
        "focus:outline-none focus:ring-1 focus:ring-teal-500 focus:border-teal-500",
        className
      )}
    >
      {placeholder && <option value="">{placeholder}</option>}
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
  );
}

// ── Modal ─────────────────────────────────────────────────────────────────────
export function Modal({ open, onClose, title, children, width = "max-w-xl" }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70" onClick={onClose} />
      <div className={clsx("relative bg-surface-raised border border-surface-border rounded-xl shadow-2xl w-full", width)}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-surface-border">
          <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
          <button onClick={onClose} className="text-slate-600 hover:text-slate-300 transition-colors">
            ✕
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

// ── Textarea ──────────────────────────────────────────────────────────────────
export function Textarea({ value, onChange, placeholder, rows = 3, className }) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={rows}
      className={clsx(
        "w-full bg-surface-muted border border-surface-border text-slate-300 text-sm rounded-md px-3 py-2 resize-none",
        "placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-teal-500 focus:border-teal-500",
        className
      )}
    />
  );
}
