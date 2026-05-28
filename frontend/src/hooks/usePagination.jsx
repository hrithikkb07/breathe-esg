import { useState, useCallback } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { clsx } from "clsx";

/**
 * usePagination — manages page/page_size state and builds a params object
 * ready to pass to any list API call.
 *
 * Usage:
 *   const { params, paginationProps } = usePagination();
 *   const { data } = useQuery({ queryFn: () => recordsApi.list({ ...filters, ...params }) });
 *   return <Pagination {...paginationProps} total={data?.count} />;
 */
export function usePagination(defaultPageSize = 50) {
  const [page, setPage] = useState(1);
  const [pageSize] = useState(defaultPageSize);

  const reset = useCallback(() => setPage(1), []);

  return {
    params: { page, page_size: pageSize },
    page,
    pageSize,
    setPage,
    reset,
  };
}

/**
 * Pagination bar rendered below tables.
 * Expects the standard DRF paginated response shape:
 *   { count, total_pages, next, previous, results }
 */
export function Pagination({ page, totalPages, count, pageSize, onPageChange }) {
  if (!totalPages || totalPages <= 1) return null;

  const start = (page - 1) * pageSize + 1;
  const end   = Math.min(page * pageSize, count);

  // Generate visible page numbers: always first, last, current ±1
  const pages = new Set([1, totalPages, page, page - 1, page + 1].filter(
    (p) => p >= 1 && p <= totalPages
  ));
  const sorted = Array.from(pages).sort((a, b) => a - b);
  // Insert ellipsis markers
  const items = [];
  sorted.forEach((p, i) => {
    if (i > 0 && p - sorted[i - 1] > 1) items.push("...");
    items.push(p);
  });

  return (
    <div className="flex items-center justify-between px-4 py-3 border-t border-surface-border">
      <p className="text-xs text-slate-600 font-mono">
        {start}–{end} of {count.toLocaleString()} records
      </p>
      <div className="flex items-center gap-1">
        <button
          disabled={page === 1}
          onClick={() => onPageChange(page - 1)}
          className="p-1.5 rounded text-slate-500 hover:text-slate-300 hover:bg-surface-muted disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>

        {items.map((item, i) =>
          item === "..." ? (
            <span key={`ellipsis-${i}`} className="px-2 text-slate-600 text-sm">…</span>
          ) : (
            <button
              key={item}
              onClick={() => onPageChange(item)}
              className={clsx(
                "w-7 h-7 rounded text-xs font-mono transition-colors",
                item === page
                  ? "bg-teal-500 text-slate-900 font-semibold"
                  : "text-slate-500 hover:text-slate-300 hover:bg-surface-muted"
              )}
            >
              {item}
            </button>
          )
        )}

        <button
          disabled={page === totalPages}
          onClick={() => onPageChange(page + 1)}
          className="p-1.5 rounded text-slate-500 hover:text-slate-300 hover:bg-surface-muted disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
