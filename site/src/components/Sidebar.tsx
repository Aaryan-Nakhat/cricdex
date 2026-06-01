import { NavLink } from "react-router-dom";
import { NAV, NAV_GROUPS } from "@/lib/nav";
import { useStore } from "@/lib/store";
import { cn, prettyDate } from "@/lib/utils";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { meta } = useStore();
  return (
    <nav className="flex h-full flex-col gap-5 p-3">
      {NAV_GROUPS.map((group) => (
        <div key={group}>
          <div className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted/70">
            {group}
          </div>
          <div className="flex flex-col gap-0.5">
            {NAV.filter((n) => n.group === group).map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                onClick={onNavigate}
                className={({ isActive }) =>
                  cn("nav-link", isActive && "nav-link-active")
                }
              >
                <item.icon className="h-4 w-4 shrink-0" />
                <span>{item.label}</span>
              </NavLink>
            ))}
          </div>
        </div>
      ))}

      <div className="mt-auto rounded-lg border border-border bg-surface/60 p-3 text-xs text-muted">
        <div className="font-semibold text-fg">Cricsheet ball-by-ball</div>
        <div className="mt-1">
          Data up to{" "}
          <span className="font-medium text-accent-glow">{prettyDate(meta?.data_as_of)}</span>.
          Updated on demand.
        </div>
      </div>
    </nav>
  );
}
