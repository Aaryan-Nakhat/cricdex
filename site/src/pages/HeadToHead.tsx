import { useMemo, useState } from "react";
import { Swords } from "lucide-react";
import { useStore } from "@/lib/store";
import { usePlayers } from "@/lib/usePlayers";
import { useAsync } from "@/lib/useAsync";
import { getRatings } from "@/lib/data";
import { headToHead, rolesFor } from "@/lib/headtohead";
import { Combobox } from "@/components/Combobox";
import { PageTitle, Card, Spinner, Empty, Badge, Collapsible } from "@/components/ui";
import { cn } from "@/lib/utils";

function H2HMath() {
  return (
    <Collapsible title="How the probability is computed (plain English)" icon={<Swords className="h-4 w-4" />}>
      <div className="space-y-3 text-sm leading-relaxed text-muted">
        <p>
          The model doesn't give each player one fixed number — it gives a <b>bell curve</b>: a best
          estimate of their skill (the centre) plus how <b>unsure</b> it is (the width). Few matches →
          wide curve; lots of matches → narrow.
        </p>
        <p>
          For a role we add the two relevant skill axes into one{" "}
          <b>complete value</b> (batting = scoring + survival; bowling = economy + strike), with the
          uncertainties combined.
        </p>
        <p>
          <b>P(A better than B)</b> = how much of A's bell curve sits above B's. Big gap between two
          confident estimates → near 100%. Small gap, or fuzzy estimates → near 50% (too close to
          call).
        </p>
        <pre className="overflow-auto rounded-lg border border-border bg-bg/60 px-3 py-2 font-mono text-xs text-fg">{`A: value +0.30, uncertainty 0.05
B: value +0.10, uncertainty 0.05
gap = 0.20, combined spread = √(0.05² + 0.05²) = 0.071
P(A better) = how far 0.20 is above 0 in that spread
            ≈ 100%  (gap is ~2.8× the spread → A clearly ahead)

If both uncertainties were 0.20 instead:
combined spread = 0.28 → gap is only 0.7× spread → P ≈ 76%`}</pre>
        <p className="text-xs">
          Technically: P = Φ(gap ÷ combined&nbsp;spread), the normal CDF — but the idea is just
          "overlap of two bell curves".
        </p>
      </div>
    </Collapsible>
  );
}

export function HeadToHead() {
  const { collection } = useStore();
  const { options } = usePlayers(collection);
  const ratings = useAsync(() => getRatings(collection), [collection]);
  const [a, setA] = useState<string | null>(null);
  const [b, setB] = useState<string | null>(null);
  const [role, setRole] = useState<"batter" | "bowler">("batter");

  const rows = ratings.data ?? [];

  // which roles are valid for both picks
  const sharedRoles = useMemo(() => {
    if (!a || !b) return [] as ("batter" | "bowler")[];
    const ra = rolesFor(rows, a), rb = rolesFor(rows, b);
    return ra.filter((r) => rb.includes(r));
  }, [a, b, rows]);

  const effectiveRole = sharedRoles.includes(role) ? role : sharedRoles[0];
  const result = useMemo(
    () => (a && b && effectiveRole ? headToHead(rows, a, b, effectiveRole) : null),
    [a, b, effectiveRole, rows],
  );

  const pct = result ? Math.round(result.pAbetter * 100) : 50;

  return (
    <>
      <PageTitle
        title="Head-to-head"
        icon={<Swords className="h-6 w-6" />}
        desc="Not just whose average is bigger — the probability that one player's true underlying skill exceeds the other's, straight from the Bayesian model's posterior (mean and uncertainty for both)."
      />

      <H2HMath />

      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto_1fr]">
        <Combobox options={options} value={a} onChange={setA} placeholder="Player A" />
        <div className="flex items-center justify-center text-sm font-bold text-muted">vs</div>
        <Combobox options={options} value={b} onChange={setB} placeholder="Player B" />
      </div>

      {a && b && sharedRoles.length > 1 && (
        <div className="mb-6 flex gap-2">
          {sharedRoles.map((r) => (
            <button
              key={r}
              onClick={() => setRole(r)}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-sm font-medium capitalize transition-all",
                r === effectiveRole
                  ? "border-accent/40 bg-accent/10 text-accent-glow"
                  : "border-border bg-surface text-muted hover:text-fg",
              )}
            >
              compare as {r}
            </button>
          ))}
        </div>
      )}

      {ratings.loading ? (
        <Spinner label="Loading ratings…" />
      ) : !a || !b ? (
        <Empty>Pick two players to compare their underlying skill.</Empty>
      ) : !result ? (
        <Empty>
          These two don't share a comparable role{sharedRoles.length === 0 ? " in this collection" : ""}. Try
          another pairing.
        </Empty>
      ) : (
        <div className="animate-fade-up space-y-5">
          {/* the gauge */}
          <Card className="px-6 py-7">
            <div className="mb-2 flex items-center justify-between text-sm font-semibold">
              <span className="text-accent-glow">{result.a.name}</span>
              <Badge tone={pct >= 55 ? "accent" : pct <= 45 ? "ball" : "muted"}>{result.verdict}</Badge>
              <span className="text-fg">{result.b.name}</span>
            </div>
            <div className="relative h-10 w-full overflow-hidden rounded-xl border border-border bg-surface">
              <div
                className="absolute inset-y-0 left-0 bg-gradient-to-r from-accent-dim to-accent-glow transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
              <div className="absolute inset-0 flex items-center justify-between px-4 text-sm font-bold">
                <span className="text-bg">{pct}%</span>
                <span className="text-fg">{100 - pct}%</span>
              </div>
              <div className="absolute left-1/2 top-0 h-full w-px bg-fg/20" />
            </div>
            <p className="mt-3 text-center text-sm text-muted">
              The model gives{" "}
              <span className="font-semibold text-accent-glow">{result.a.name}</span> a{" "}
              <span className="stat-num font-bold text-fg">{pct}%</span> chance of being the better{" "}
              {result.role} than{" "}
              <span className="font-semibold text-fg">{result.b.name}</span>.
            </p>
          </Card>

          {/* the why */}
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            {[result.a, result.b].map((side, i) => (
              <Card key={i} className="px-5 py-4">
                <div className="text-sm font-semibold" style={{ color: i === 0 ? "#6ee7b7" : "#e6edf3" }}>
                  {side.name}
                </div>
                <div className="mt-3 space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted">Complete {result.role} value (mean)</span>
                    <span className="stat-num font-semibold text-fg">
                      {side.axis.mean >= 0 ? "+" : ""}
                      {side.axis.mean.toFixed(3)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Uncertainty (sd)</span>
                    <span className="stat-num text-muted">±{side.axis.sd.toFixed(3)}</span>
                  </div>
                </div>
              </Card>
            ))}
          </div>

          <p className="text-xs leading-relaxed text-muted">
            The “complete {result.role} value” sums the two relevant latent axes
            {result.role === "batter" ? " (scoring + survival)" : " (economy + strike)"} — variances add
            because the axes are modelled separately. P(A&nbsp;better) is the normal CDF of the mean gap
            divided by the combined uncertainty: a big gap between confident estimates moves the bar to the
            edges; a small gap or fuzzy estimates keeps it near 50%.
          </p>
        </div>
      )}
    </>
  );
}
