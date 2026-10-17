import { TrendingDown, TrendingUp, MoveHorizontal } from "lucide-react";
import { DIRECTION_LABEL, type Direction, type MetricDef } from "@/lib/metrics";
import { Badge, InfoTip } from "./ui";

/** "Higher is better" / "Lower is better" / "Neither — describes a style", as a small badge. */
export function DirectionBadge({ direction }: { direction: Direction }) {
  const icon =
    direction === "higher" ? (
      <TrendingUp className="h-3 w-3" />
    ) : direction === "lower" ? (
      <TrendingDown className="h-3 w-3" />
    ) : (
      <MoveHorizontal className="h-3 w-3" />
    );
  return (
    <Badge tone={direction === "higher" ? "accent" : direction === "lower" ? "ball" : "muted"}>
      {icon} {DIRECTION_LABEL[direction]}
    </Badge>
  );
}

/** The fan-facing explainer for one metric: what it is, how to read it, which way is good, what good looks like,
 * and (smaller) how it's worked out. */
export function MetricExplainer({ m, showHow = true }: { m: MetricDef; showHow?: boolean }) {
  return (
    <div className="space-y-2">
      <p className="text-fg">{m.one_liner}</p>
      <div>
        <div className="font-semibold text-fg">How to read it</div>
        <p>{m.read}</p>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <DirectionBadge direction={m.direction} />
      </div>
      <div>
        <div className="font-semibold text-fg">What good looks like</div>
        <p>{m.good}</p>
      </div>
      {showHow && (
        <div>
          <div className="font-semibold text-fg">How it's worked out</div>
          <p>{m.how}</p>
        </div>
      )}
    </div>
  );
}

/** An (i) button that opens the metric explainer. */
export function MetricInfo({ m, className }: { m: MetricDef; className?: string }) {
  return (
    <InfoTip title={m.name} label={`What ${m.name} means`} className={className}>
      <MetricExplainer m={m} />
    </InfoTip>
  );
}
