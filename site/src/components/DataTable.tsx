import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { cn, fmt } from "@/lib/utils";

export interface Col<T> {
  key: string;
  label: string;
  align?: "left" | "right";
  digits?: number; // numeric formatting; omit for raw / string
  primary?: boolean;
  render?: (row: T) => React.ReactNode;
  sortable?: boolean;
}

export function DataTable<T extends Record<string, unknown>>({
  rows,
  cols,
  initialSort,
  rankCol = true,
  onRowClick,
  rowLabel,
  higherIsBetter = true,
  maxHeight = "70vh",
}: {
  rows: T[];
  cols: Col<T>[];
  initialSort?: { key: string; dir: "asc" | "desc" };
  rankCol?: boolean;
  onRowClick?: (row: T) => void;
  /** Accessible name for a clickable row (e.g. "Open V Kohli's profile"). */
  rowLabel?: (row: T) => string;
  /** False for metrics where smaller is better: the best rows rank first and get the longest bars. */
  higherIsBetter?: boolean;
  maxHeight?: string;
}) {
  const primary = cols.find((c) => c.primary)?.key ?? cols[1]?.key ?? cols[0]?.key;
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" }>(
    initialSort ?? { key: primary, dir: higherIsBetter ? "desc" : "asc" },
  );

  // magnitude range for the primary column → drives inline bars
  const range = useMemo(() => {
    const vals = rows
      .map((r) => Number(r[primary]))
      .filter((v) => Number.isFinite(v));
    return { min: Math.min(...vals), max: Math.max(...vals) };
  }, [rows, primary]);

  const sorted = useMemo(() => {
    const c = cols.find((x) => x.key === sort.key);
    const numeric = c?.digits !== undefined || c?.primary;
    const copy = [...rows];
    const missing = (v: unknown) => v === null || v === undefined || v === "" || (numeric && !Number.isFinite(Number(v)));
    copy.sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      // rows without a value always go last, whichever way the column is sorted
      if (missing(av) || missing(bv)) return Number(missing(av)) - Number(missing(bv));
      const cmp = numeric ? Number(av) - Number(bv) : String(av).localeCompare(String(bv));
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [rows, sort, cols]);

  function toggle(key: string) {
    setSort((s) =>
      s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" },
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="overflow-auto" style={{ maxHeight }}>
        <table className="w-full border-collapse">
          <thead>
            <tr>
              {rankCol && <th className="th w-12 text-right">#</th>}
              {cols.map((c) => {
                const sortable = c.sortable !== false;
                const isSort = sort.key === c.key;
                const inner = (
                  <span className={cn("inline-flex items-center gap-1", c.align === "right" && "flex-row-reverse")}>
                    {c.label}
                      {sortable &&
                        (isSort ? (
                          sort.dir === "desc" ? (
                            <ArrowDown className="h-3 w-3 text-accent" />
                          ) : (
                            <ArrowUp className="h-3 w-3 text-accent" />
                          )
                        ) : (
                          <ChevronsUpDown className="h-3 w-3 text-muted/40" />
                        ))}
                  </span>
                );
                return (
                  <th
                    key={c.key}
                    scope="col"
                    aria-sort={isSort ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
                    className={cn("th", c.align === "right" && "text-right")}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        onClick={() => toggle(c.key)}
                        className="select-none rounded uppercase tracking-wider hover:text-fg"
                        title={`Sort by ${c.label}`}
                      >
                        {inner}
                      </button>
                    ) : (
                      inner
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => (
              <tr
                key={i}
                className={cn(
                  "group transition-colors hover:bg-surface/60",
                  onRowClick && "cursor-pointer",
                )}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                aria-label={onRowClick && rowLabel ? rowLabel(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
              >
                {rankCol && (
                  <td className="td text-right stat-num text-muted">{i + 1}</td>
                )}
                {cols.map((c) => {
                  const raw = row[c.key];
                  const isNum = c.digits !== undefined || c.primary;
                  const lin =
                    c.primary && Number.isFinite(range.max) && range.max !== range.min && Number.isFinite(Number(raw))
                      ? (Number(raw) - range.min) / (range.max - range.min)
                      : null;
                  const frac = lin === null ? null : higherIsBetter ? lin : 1 - lin;
                  return (
                    <td
                      key={c.key}
                      className={cn(
                        "td",
                        c.align === "right" && "text-right",
                        isNum && "stat-num",
                        c.primary && "font-semibold text-fg",
                      )}
                    >
                      {c.render ? (
                        c.render(row)
                      ) : isNum ? (
                        <div className={cn(c.align === "right" ? "text-right" : "text-left")}>
                          <span>{fmt(raw as number | string | null, c.digits ?? 2)}</span>
                          {frac !== null && (
                            <div className="mt-1 h-1 w-full max-w-[120px] overflow-hidden rounded-full bg-border/50">
                              <div
                                className="h-full rounded-full bg-grad"
                                style={{ width: `${Math.max(2, frac * 100)}%` }}
                              />
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className={cn(c.key === primary ? "font-medium text-fg" : "text-fg")}>
                          {raw === null || raw === undefined ? "—" : String(raw)}
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
