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
  maxHeight = "70vh",
}: {
  rows: T[];
  cols: Col<T>[];
  initialSort?: { key: string; dir: "asc" | "desc" };
  rankCol?: boolean;
  onRowClick?: (row: T) => void;
  maxHeight?: string;
}) {
  const primary = cols.find((c) => c.primary)?.key ?? cols[1]?.key ?? cols[0]?.key;
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" }>(
    initialSort ?? { key: primary, dir: "desc" },
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
    copy.sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      let cmp: number;
      if (numeric) {
        cmp = (Number(av) || 0) - (Number(bv) || 0);
      } else {
        cmp = String(av ?? "").localeCompare(String(bv ?? ""));
      }
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
                return (
                  <th
                    key={c.key}
                    className={cn("th", c.align === "right" && "text-right", sortable && "cursor-pointer select-none")}
                    onClick={sortable ? () => toggle(c.key) : undefined}
                  >
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
              >
                {rankCol && (
                  <td className="td text-right stat-num text-muted">{i + 1}</td>
                )}
                {cols.map((c) => {
                  const raw = row[c.key];
                  const isNum = c.digits !== undefined || c.primary;
                  const frac =
                    c.primary && Number.isFinite(range.max) && range.max !== range.min
                      ? (Number(raw) - range.min) / (range.max - range.min)
                      : null;
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
                          <span>{fmt(Number(raw), c.digits ?? 2)}</span>
                          {frac !== null && (
                            <div className="mt-1 h-1 w-full max-w-[120px] overflow-hidden rounded-full bg-border/50">
                              <div
                                className="h-full rounded-full bg-gradient-to-r from-accent-dim to-accent-glow"
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
