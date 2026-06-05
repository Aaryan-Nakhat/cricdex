import { useCallback, useEffect, useRef, useState } from "react";
import { Eye, Dices, Play } from "lucide-react";
import {
  simulate,
  randomDelivery,
  rng,
  PITCH,
  type DeliveryParams,
  type Hand,
  type Sim,
  type Verdict,
} from "@/lib/lbw";
import { PageTitle, Card, CardHeader, Badge } from "@/components/ui";
import { cn } from "@/lib/utils";

type Phase = "ready" | "bowling" | "decide" | "revealed";

const TOP_W = 340;
const TOP_H = 300;
const SIDE_W = 620;
const SIDE_H = 240;

const COL = {
  bg: "#0d131c",
  pitch: "#15212f",
  line: "#1e2c3c",
  ball: "#f87171",
  path: "#fbbf24",
  proj: "#38bdf8",
  stump: "#e6edf3",
  hit: "#34d399",
  miss: "#64748b",
  text: "#8a97a8",
};

// ---- canvas drawing --------------------------------------------------------

function drawTop(ctx: CanvasRenderingContext2D, sim: Sim | null, n: number, reveal: boolean) {
  const W = TOP_W;
  const H = TOP_H;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = COL.bg;
  ctx.fillRect(0, 0, W, H);
  const X = (x: number) => W / 2 + (x / 1.0) * (W * 0.46);
  const Z = (z: number) => 18 + ((18 - z) / 18) * (H - 36);

  // pitch strip
  ctx.fillStyle = COL.pitch;
  ctx.fillRect(X(-0.55), Z(18), X(0.55) - X(-0.55), Z(0) - Z(18));
  // stump zone (bottom)
  ctx.strokeStyle = COL.line;
  ctx.lineWidth = 1;
  for (const s of [-PITCH.HALF_STUMP, PITCH.HALF_STUMP]) {
    ctx.beginPath();
    ctx.moveTo(X(s), Z(0) - 18);
    ctx.lineTo(X(s), Z(0) + 6);
    ctx.stroke();
  }
  ctx.fillStyle = COL.stump;
  ctx.fillRect(X(-PITCH.HALF_STUMP), Z(0) + 2, X(PITCH.HALF_STUMP) - X(-PITCH.HALF_STUMP), 4);
  ctx.fillStyle = COL.text;
  ctx.font = "10px ui-monospace, monospace";
  ctx.fillText("line / pitching (top-down)", 8, 14);

  if (!sim) return;
  // flight path projected onto x–z
  ctx.strokeStyle = COL.path;
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i <= n && i < sim.path.length; i++) {
    const p = sim.path[i];
    if (i === 0) ctx.moveTo(X(p.x), Z(p.z));
    else ctx.lineTo(X(p.x), Z(p.z));
  }
  ctx.stroke();
  // ball head
  const head = sim.path[Math.min(n, sim.path.length - 1)];
  // bounce marker — once the ball has reached the bounce point
  if (sim.bounce && head.z <= sim.bounce.z) {
    ctx.fillStyle = COL.path;
    ctx.beginPath();
    ctx.arc(X(sim.bounce.x), Z(sim.bounce.z), 3.5, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.fillStyle = COL.ball;
  ctx.beginPath();
  ctx.arc(X(head.x), Z(head.z), 4, 0, Math.PI * 2);
  ctx.fill();

  if (reveal) {
    ctx.strokeStyle = COL.proj;
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    sim.projected.forEach((p, i) => {
      if (i === 0) ctx.moveTo(X(p.x), Z(p.z));
      else ctx.lineTo(X(p.x), Z(p.z));
    });
    ctx.stroke();
    ctx.setLineDash([]);
    const hit = sim.decision.wickets;
    ctx.fillStyle = hit === "hitting" ? COL.hit : hit === "clipping" ? COL.path : COL.miss;
    ctx.beginPath();
    ctx.arc(X(sim.stump.x), Z(0), 4, 0, Math.PI * 2);
    ctx.fill();
  }
}

function drawSide(ctx: CanvasRenderingContext2D, sim: Sim | null, n: number, reveal: boolean) {
  const W = SIDE_W;
  const H = SIDE_H;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = COL.bg;
  ctx.fillRect(0, 0, W, H);
  const Z = (z: number) => 20 + (z / 18) * (W - 40);
  const Y = (y: number) => H - 22 - (y / 3.0) * (H - 44);

  // ground + stumps (at z = 0, left)
  ctx.strokeStyle = COL.line;
  ctx.beginPath();
  ctx.moveTo(0, Y(0));
  ctx.lineTo(W, Y(0));
  ctx.stroke();
  ctx.strokeStyle = COL.stump;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(Z(0), Y(0));
  ctx.lineTo(Z(0), Y(PITCH.BAIL_TOP));
  ctx.stroke();
  ctx.fillStyle = COL.text;
  ctx.font = "10px ui-monospace, monospace";
  ctx.fillText("length / height (side-on) — batter ◀ ▶ bowler", 8, 14);

  if (!sim) return;
  ctx.strokeStyle = COL.path;
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i <= n && i < sim.path.length; i++) {
    const p = sim.path[i];
    if (i === 0) ctx.moveTo(Z(p.z), Y(p.y));
    else ctx.lineTo(Z(p.z), Y(p.y));
  }
  ctx.stroke();
  if (sim.bounce) {
    ctx.fillStyle = COL.path;
    ctx.beginPath();
    ctx.arc(Z(sim.bounce.z), Y(0), 3.5, 0, Math.PI * 2);
    ctx.fill();
  }
  const head = sim.path[Math.min(n, sim.path.length - 1)];
  ctx.fillStyle = COL.ball;
  ctx.beginPath();
  ctx.arc(Z(head.z), Y(head.y), 4, 0, Math.PI * 2);
  ctx.fill();

  if (reveal) {
    ctx.strokeStyle = COL.proj;
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    sim.projected.forEach((p, i) => {
      if (i === 0) ctx.moveTo(Z(p.z), Y(p.y));
      else ctx.lineTo(Z(p.z), Y(p.y));
    });
    ctx.stroke();
    ctx.setLineDash([]);
    const hit = sim.decision.wickets;
    ctx.fillStyle = hit === "hitting" ? COL.hit : hit === "clipping" ? COL.path : COL.miss;
    ctx.beginPath();
    ctx.arc(Z(0), Y(sim.stump.y), 4, 0, Math.PI * 2);
    ctx.fill();
  }
}

// ---- a labelled slider -----------------------------------------------------
function Slider({
  label,
  value,
  min,
  max,
  step,
  fmt,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  fmt?: (v: number) => string;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      <span className="flex justify-between">
        <span>{label}</span>
        <span className="stat-num text-fg">{fmt ? fmt(value) : value}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full cursor-pointer accent-[#34d399]"
      />
    </label>
  );
}

const DEFAULT: DeliveryParams = {
  paceKmph: 135,
  length: 0.5,
  line: 0,
  swing: 0,
  deviation: 0,
  bounce: 0.55,
  wind: 0,
  impactZ: 1.5,
  shotOffered: false,
  hand: "RH",
  margin: 0.05,
};

export function UmpiresEye() {
  const topRef = useRef<HTMLCanvasElement>(null);
  const sideRef = useRef<HTMLCanvasElement>(null);
  const seedRef = useRef(1);

  const [params, setParams] = useState<DeliveryParams>(DEFAULT);
  const [sim, setSim] = useState<Sim | null>(null);
  const [phase, setPhase] = useState<Phase>("ready");
  const [idx, setIdx] = useState(0);
  const [userCall, setUserCall] = useState<Verdict | null>(null);
  const [score, setScore] = useState({ correct: 0, total: 0 });
  const [streak, setStreak] = useState(0);

  const set = (patch: Partial<DeliveryParams>) => setParams((p) => ({ ...p, ...patch }));

  const bowl = useCallback((p: DeliveryParams) => {
    const s = simulate(p);
    setSim(s);
    setParams(p);
    setUserCall(null);
    setIdx(0);
    setPhase("bowling");
  }, []);

  const bowlRandom = useCallback(() => {
    seedRef.current = (seedRef.current * 1664525 + 1013904223) >>> 0;
    const p = randomDelivery(rng(seedRef.current), params.hand);
    p.margin = params.margin; // keep chosen difficulty
    bowl(p);
  }, [bowl, params.hand, params.margin]);

  // animation loop
  useEffect(() => {
    if (phase !== "bowling" || !sim) return;
    const total = sim.path.length;
    const speed = Math.max(1, Math.floor(total / 80));
    let i = 0;
    let raf = 0;
    const tick = () => {
      i += speed;
      if (i >= total - 1) {
        setIdx(total - 1);
        setPhase("decide");
        return;
      }
      setIdx(i);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [phase, sim]);

  // draw on every state change
  useEffect(() => {
    const t = topRef.current?.getContext("2d");
    const s = sideRef.current?.getContext("2d");
    const reveal = phase === "revealed";
    if (t) drawTop(t, sim, idx, reveal);
    if (s) drawSide(s, sim, idx, reveal);
  }, [sim, idx, phase]);

  const call = (v: Verdict) => {
    if (!sim || phase !== "decide") return;
    setUserCall(v);
    setPhase("revealed");
    setIdx(sim.path.length - 1);
    const ok = v === sim.decision.verdict;
    setScore((c) => ({ correct: c.correct + (ok ? 1 : 0), total: c.total + 1 }));
    setStreak((st) => (ok ? st + 1 : 0));
  };

  const d = sim?.decision;
  const correct = userCall && d ? userCall === d.verdict : null;

  return (
    <>
      <PageTitle
        title="Umpire's Eye — Out or Not Out?"
        icon={<Eye className="h-6 w-6" />}
        desc="A physics-simulated LBW trainer. Watch the delivery, then call it before the ball-tracking reveals the verdict — pitching, impact and where it's going. Every ball is randomised; tune the conditions to drill a scenario."
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_320px]">
        {/* views + verdict */}
        <div className="space-y-4">
          <Card className="p-4">
            <div className="flex flex-wrap items-start justify-center gap-4">
              <canvas
                ref={topRef}
                width={TOP_W}
                height={TOP_H}
                className="rounded-lg border border-border"
              />
              <canvas
                ref={sideRef}
                width={SIDE_W}
                height={SIDE_H}
                className="max-w-full rounded-lg border border-border"
              />
            </div>
          </Card>

          {/* call buttons / verdict */}
          {phase === "decide" && (
            <Card className="flex flex-wrap items-center justify-center gap-3 p-4">
              <span className="text-sm font-semibold text-fg">Your call?</span>
              <button
                onClick={() => call("OUT")}
                className="rounded-lg border border-ball/40 bg-ball/10 px-5 py-2 text-sm font-bold text-ball hover:bg-ball/20"
              >
                OUT
              </button>
              <button
                onClick={() => call("UMPIRE'S CALL")}
                className="rounded-lg border border-accent/40 bg-accent/10 px-5 py-2 text-sm font-bold text-accent-glow hover:bg-accent/20"
              >
                UMPIRE'S CALL
              </button>
              <button
                onClick={() => call("NOT OUT")}
                className="rounded-lg border border-willow/40 bg-willow/10 px-5 py-2 text-sm font-bold text-willow hover:bg-willow/20"
              >
                NOT OUT
              </button>
            </Card>
          )}

          {phase === "revealed" && d && (
            <Card className="p-4">
              <div className="flex flex-wrap items-center gap-3">
                <Badge tone={correct ? "willow" : "ball"}>
                  {correct ? "✓ Correct" : "✗ Wrong"}
                </Badge>
                <span className="text-sm text-muted">
                  You said <b className="text-fg">{userCall}</b> — verdict was{" "}
                  <b
                    className={cn(
                      d.verdict === "OUT"
                        ? "text-ball"
                        : d.verdict === "NOT OUT"
                          ? "text-willow"
                          : "text-accent-glow",
                    )}
                  >
                    {d.verdict}
                  </b>
                </span>
                <button
                  onClick={bowlRandom}
                  className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-accent/40 bg-accent/10 px-4 py-2 text-sm font-semibold text-accent-glow hover:bg-accent/20"
                >
                  <Dices className="h-4 w-4" /> Next ball
                </button>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                <div className="rounded-md border border-border bg-surface px-2 py-1.5">
                  <div className="text-muted">Pitching</div>
                  <div className="font-semibold text-fg">{d.pitching}</div>
                </div>
                <div className="rounded-md border border-border bg-surface px-2 py-1.5">
                  <div className="text-muted">Impact</div>
                  <div className="font-semibold text-fg">{d.impactZone}</div>
                </div>
                <div className="rounded-md border border-border bg-surface px-2 py-1.5">
                  <div className="text-muted">Wickets</div>
                  <div className="font-semibold text-fg">{d.wickets}</div>
                </div>
              </div>
              <p className="mt-2 text-xs italic text-muted">{d.reasons.join(" · ")}</p>
            </Card>
          )}

          {(phase === "ready" || phase === "bowling") && (
            <Card className="flex flex-wrap items-center justify-center gap-3 p-4">
              <button
                onClick={bowlRandom}
                disabled={phase === "bowling"}
                className="inline-flex items-center gap-1.5 rounded-lg border border-accent/40 bg-accent/10 px-5 py-2 text-sm font-bold text-accent-glow hover:bg-accent/20 disabled:opacity-40"
              >
                <Dices className="h-4 w-4" /> Bowl a random ball
              </button>
              <button
                onClick={() => bowl(params)}
                disabled={phase === "bowling"}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-5 py-2 text-sm font-semibold text-fg hover:border-accent/40 disabled:opacity-40"
              >
                <Play className="h-4 w-4" /> Bowl these settings
              </button>
            </Card>
          )}
        </div>

        {/* score + config */}
        <div className="space-y-4">
          <Card className="p-4">
            <CardHeader title="Score" subtitle="Call it like the third umpire" />
            <div className="grid grid-cols-3 gap-2 p-3 text-center">
              <div>
                <div className="stat-num text-2xl font-bold text-fg">{score.correct}</div>
                <div className="text-[11px] text-muted">correct</div>
              </div>
              <div>
                <div className="stat-num text-2xl font-bold text-fg">{score.total}</div>
                <div className="text-[11px] text-muted">balls</div>
              </div>
              <div>
                <div className="stat-num text-2xl font-bold text-accent-glow">{streak}</div>
                <div className="text-[11px] text-muted">streak</div>
              </div>
            </div>
            {score.total > 0 && (
              <div className="px-3 pb-2 text-center text-xs text-muted">
                {Math.round((score.correct / score.total) * 100)}% accuracy
              </div>
            )}
          </Card>

          <Card className="p-4">
            <CardHeader title="Conditions" subtitle="Drill a specific scenario" />
            <div className="space-y-3 p-3">
              <Slider label="Pace (km/h)" value={params.paceKmph} min={110} max={150} step={1} onChange={(v) => set({ paceKmph: v })} />
              <Slider label="Length (full → short)" value={params.length} min={0} max={1} step={0.01} fmt={(v) => v.toFixed(2)} onChange={(v) => set({ length: v })} />
              <Slider label="Line (leg − / off +, m)" value={params.line} min={-0.4} max={0.4} step={0.01} fmt={(v) => v.toFixed(2)} onChange={(v) => set({ line: v })} />
              <Slider label="Swing (m/s²)" value={params.swing} min={-4} max={4} step={0.1} fmt={(v) => v.toFixed(1)} onChange={(v) => set({ swing: v })} />
              <Slider label="Seam/spin off pitch (m/s)" value={params.deviation} min={-0.6} max={0.6} step={0.02} fmt={(v) => v.toFixed(2)} onChange={(v) => set({ deviation: v })} />
              <Slider label="Bounce (dead → springy)" value={params.bounce} min={0.4} max={0.68} step={0.01} fmt={(v) => v.toFixed(2)} onChange={(v) => set({ bounce: v })} />
              <Slider label="Wind (m/s²)" value={params.wind} min={-1.5} max={1.5} step={0.1} fmt={(v) => v.toFixed(1)} onChange={(v) => set({ wind: v })} />
              <Slider label="Impact distance (m)" value={params.impactZ} min={0.5} max={3} step={0.05} fmt={(v) => v.toFixed(2)} onChange={(v) => set({ impactZ: v })} />
              <Slider label="Umpire's-call band (m) — smaller = harder" value={params.margin} min={0.01} max={0.12} step={0.005} fmt={(v) => v.toFixed(3)} onChange={(v) => set({ margin: v })} />
              <div className="flex items-center gap-3 pt-1">
                <label className="flex items-center gap-1.5 text-xs text-muted">
                  <input type="checkbox" checked={params.shotOffered} onChange={(e) => set({ shotOffered: e.target.checked })} className="accent-[#34d399]" />
                  shot offered
                </label>
                <label className="flex items-center gap-1.5 text-xs text-muted">
                  Hand
                  <select
                    value={params.hand}
                    onChange={(e) => set({ hand: e.target.value as Hand })}
                    className="input w-auto cursor-pointer py-1 text-xs"
                  >
                    <option value="RH" className="bg-card">RH</option>
                    <option value="LH" className="bg-card">LH</option>
                  </select>
                </label>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
