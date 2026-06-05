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
type V3 = [number, number, number];

const W = 860;
const H = 480;
const FOCAL = 760;

const COL = {
  sky: "#0b1018",
  grass: "#16321f",
  grass2: "#1b3a25",
  pitch: "#b9a37a",
  pitchEdge: "#8c764f",
  crease: "#e8e4d8",
  ball: "#e2362f",
  ballGlow: "#ff6b5e",
  trail: "#fbbf24",
  proj: "#38bdf8",
  stump: "#e8d8b0",
  bail: "#f4ead0",
  hit: "#34d399",
  clip: "#fbbf24",
  miss: "#64748b",
  skin: "#caa07a",
  shirt: "#dfe7ee",
  pad: "#eef2f6",
  bat: "#b9874d",
  text: "#8a97a8",
};

// pitch length to the bowler stumps (m)
const PITCH_LEN = 20.12;

// ---- tiny vec3 + pinhole camera -------------------------------------------
const sub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a: V3, b: V3): V3 => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const norm = (a: V3): V3 => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};

interface Cam {
  eye: V3;
  r: V3;
  u: V3;
  f: V3;
}
function makeCam(eye: V3, target: V3): Cam {
  const f = norm(sub(target, eye));
  const r = norm(cross(f, [0, 1, 0]));
  const u = cross(r, f);
  return { eye, r, u, f };
}
interface P2 {
  x: number;
  y: number;
  s: number;
  z: number;
}
function project(cam: Cam, P: V3): P2 | null {
  const d = sub(P, cam.eye);
  const cz = dot(d, cam.f);
  if (cz <= 0.06) return null;
  return { x: W / 2 + (FOCAL * dot(d, cam.r)) / cz, y: H / 2 - (FOCAL * dot(d, cam.u)) / cz, s: FOCAL / cz, z: cz };
}

const CAMERAS: Record<string, { eye: V3; target: V3 }> = {
  "Behind stumps": { eye: [0, 2.1, -5.2], target: [0, 0.5, 9] },
  "Bowler's eye": { eye: [0, 2.4, 24], target: [0, 0.45, 0] },
  "Side-on": { eye: [-8.5, 1.7, 4.5], target: [0.1, 0.6, 4.5] },
  "High angle": { eye: [-4.5, 4.6, -3.5], target: [0, 0.3, 8] },
};

// ---- scene rendering -------------------------------------------------------
function line3(ctx: CanvasRenderingContext2D, cam: Cam, a: V3, b: V3, color: string, width: number) {
  const pa = project(cam, a);
  const pb = project(cam, b);
  if (!pa || !pb) return;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(pa.x, pa.y);
  ctx.lineTo(pb.x, pb.y);
  ctx.stroke();
}
function quad(ctx: CanvasRenderingContext2D, cam: Cam, pts: V3[], fill: string, stroke?: string) {
  const ps = pts.map((p) => project(cam, p));
  if (ps.some((p) => !p)) return;
  ctx.beginPath();
  ps.forEach((p, i) => (i ? ctx.lineTo(p!.x, p!.y) : ctx.moveTo(p!.x, p!.y)));
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
  if (stroke) {
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
}
function dot3(ctx: CanvasRenderingContext2D, cam: Cam, p: V3, r: number, color: string) {
  const q = project(cam, p);
  if (!q) return;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(q.x, q.y, Math.max(1.5, r * q.s), 0, Math.PI * 2);
  ctx.fill();
}

function drawStumps(ctx: CanvasRenderingContext2D, cam: Cam, z: number, color: string, glow: boolean) {
  const xs = [-PITCH.HALF_STUMP, 0, PITCH.HALF_STUMP];
  if (glow) {
    ctx.shadowColor = color;
    ctx.shadowBlur = 16;
  }
  for (const x of xs) line3(ctx, cam, [x, 0, z], [x, PITCH.BAIL_TOP, z], color, Math.max(2, 7 * (project(cam, [x, 0, z])?.s ?? 0)));
  // bails
  line3(ctx, cam, [-PITCH.HALF_STUMP, PITCH.BAIL_TOP, z], [PITCH.HALF_STUMP, PITCH.BAIL_TOP, z], COL.bail, Math.max(1.5, 4 * (project(cam, [0, PITCH.BAIL_TOP, z])?.s ?? 0)));
  ctx.shadowBlur = 0;
}

function drawBatsman(ctx: CanvasRenderingContext2D, cam: Cam, hand: Hand) {
  // stylized RH/LH batsman at the crease, a touch to the leg side
  const side = hand === "RH" ? -1 : 1; // leg side x-sign
  const bx = side * 0.18; // stance centre
  const z = 1.35;
  const head: V3 = [bx, 1.62, z];
  const shoulder: V3 = [bx, 1.32, z];
  const hip: V3 = [bx, 0.92, z];
  const footF: V3 = [bx - side * 0.18, 0, z - 0.15];
  const footB: V3 = [bx + side * 0.05, 0, z + 0.2];
  const hands: V3 = [bx - side * 0.16, 1.0, z - 0.12];
  // legs (pads — thicker, light)
  line3(ctx, cam, hip, footF, COL.pad, Math.max(3, 9 * (project(cam, footF)?.s ?? 0)));
  line3(ctx, cam, hip, footB, COL.pad, Math.max(3, 8 * (project(cam, footB)?.s ?? 0)));
  // torso
  line3(ctx, cam, shoulder, hip, COL.shirt, Math.max(3, 11 * (project(cam, hip)?.s ?? 0)));
  // arms to hands
  line3(ctx, cam, shoulder, hands, COL.shirt, Math.max(2, 6 * (project(cam, hands)?.s ?? 0)));
  // bat (hands down toward ground in front)
  const batToe: V3 = [bx - side * 0.05, 0.02, z - 0.45];
  line3(ctx, cam, hands, batToe, COL.bat, Math.max(2, 7 * (project(cam, batToe)?.s ?? 0)));
  // head
  dot3(ctx, cam, head, 0.11, COL.skin);
}

function drawScene(ctx: CanvasRenderingContext2D, cam: Cam, sim: Sim | null, n: number, reveal: boolean) {
  ctx.clearRect(0, 0, W, H);
  // sky
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, COL.sky);
  g.addColorStop(1, "#0f1922");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);

  // grass (big ground plane)
  quad(ctx, cam, [
    [-10, 0, -7],
    [10, 0, -7],
    [10, 0, 26],
    [-10, 0, 26],
  ], COL.grass);
  // pitch strip
  quad(
    ctx,
    cam,
    [
      [-1.5, 0, -0.5],
      [1.5, 0, -0.5],
      [1.5, 0, PITCH_LEN + 0.5],
      [-1.5, 0, PITCH_LEN + 0.5],
    ],
    COL.pitch,
    COL.pitchEdge,
  );
  // creases (popping crease both ends + the stump line)
  for (const z of [0, 1.22, PITCH_LEN, PITCH_LEN - 1.22]) {
    line3(ctx, cam, [-1.32, 0.01, z], [1.32, 0.01, z], COL.crease, 1.5);
  }

  if (!sim) {
    drawStumps(ctx, cam, 0, COL.stump, false);
    drawStumps(ctx, cam, PITCH_LEN, COL.stump, false);
    drawBatsman(ctx, cam, "RH");
    return;
  }

  // bowler-end stumps (far)
  drawStumps(ctx, cam, PITCH_LEN, COL.stump, false);

  // bounce mark on the pitch
  if (sim.bounce && sim.path[Math.min(n, sim.path.length - 1)].z <= sim.bounce.z) {
    const q = project(cam, [sim.bounce.x, 0.01, sim.bounce.z]);
    if (q) {
      ctx.fillStyle = "rgba(251,191,36,0.5)";
      ctx.beginPath();
      ctx.ellipse(q.x, q.y, Math.max(3, 6 * q.s), Math.max(1.5, 3 * q.s), 0, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // ball trail
  ctx.strokeStyle = COL.trail;
  ctx.lineWidth = 2;
  ctx.beginPath();
  let started = false;
  for (let i = Math.max(0, n - 16); i <= n && i < sim.path.length; i++) {
    const p = sim.path[i];
    const q = project(cam, [p.x, p.y, p.z]);
    if (!q) continue;
    if (!started) {
      ctx.moveTo(q.x, q.y);
      started = true;
    } else ctx.lineTo(q.x, q.y);
  }
  ctx.stroke();

  // projected path + impact (reveal only)
  if (reveal) {
    ctx.strokeStyle = COL.proj;
    ctx.setLineDash([6, 5]);
    ctx.lineWidth = 2;
    ctx.beginPath();
    let st = false;
    for (const p of sim.projected) {
      const q = project(cam, [p.x, p.y, p.z]);
      if (!q) continue;
      if (!st) {
        ctx.moveTo(q.x, q.y);
        st = true;
      } else ctx.lineTo(q.x, q.y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    dot3(ctx, cam, [sim.impact.x, sim.impact.y, sim.impact.z], 0.06, COL.proj);
  }

  // the ball
  const head = sim.path[Math.min(n, sim.path.length - 1)];
  const hq = project(cam, [head.x, head.y, head.z]);
  if (hq) {
    ctx.shadowColor = COL.ballGlow;
    ctx.shadowBlur = 12;
    ctx.fillStyle = COL.ball;
    ctx.beginPath();
    ctx.arc(hq.x, hq.y, Math.max(2.5, PITCH.BALL_R * hq.s * 1.6), 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  }

  // batsman + near stumps (foreground)
  drawBatsman(ctx, cam, sim.params.hand);
  const wk = reveal ? sim.decision.wickets : "missing";
  const stumpCol = !reveal
    ? COL.stump
    : wk === "hitting"
      ? COL.hit
      : wk === "clipping"
        ? COL.clip
        : COL.stump;
  drawStumps(ctx, cam, 0, stumpCol, reveal && wk !== "missing");
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
  const cvs = useRef<HTMLCanvasElement>(null);
  const seedRef = useRef(1);

  const [params, setParams] = useState<DeliveryParams>(DEFAULT);
  const [sim, setSim] = useState<Sim | null>(null);
  const [phase, setPhase] = useState<Phase>("ready");
  const [idx, setIdx] = useState(0);
  const [userCall, setUserCall] = useState<Verdict | null>(null);
  const [score, setScore] = useState({ correct: 0, total: 0 });
  const [streak, setStreak] = useState(0);
  const [camKey, setCamKey] = useState("Behind stumps");

  const set = (patch: Partial<DeliveryParams>) => setParams((p) => ({ ...p, ...patch }));

  const bowl = useCallback((p: DeliveryParams) => {
    setSim(simulate(p));
    setParams(p);
    setUserCall(null);
    setIdx(0);
    setPhase("bowling");
  }, []);

  const bowlRandom = useCallback(() => {
    seedRef.current = (seedRef.current * 1664525 + 1013904223) >>> 0;
    const p = randomDelivery(rng(seedRef.current), params.hand);
    p.margin = params.margin;
    bowl(p);
  }, [bowl, params.hand, params.margin]);

  // animation loop (ball flies; freeze at impact)
  useEffect(() => {
    if (phase !== "bowling" || !sim) return;
    const total = sim.path.length;
    const speed = Math.max(1, Math.floor(total / 95));
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

  // draw
  useEffect(() => {
    const ctx = cvs.current?.getContext("2d");
    if (!ctx) return;
    const c = CAMERAS[camKey];
    drawScene(ctx, makeCam(c.eye, c.target), sim, idx, phase === "revealed");
  }, [sim, idx, phase, camKey]);

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
        desc="A 3D physics-simulated LBW trainer. Watch the delivery come down, then call it before the ball-tracking reveals pitching, impact and the projected stump path. Every ball is randomised; tune the conditions to drill a scenario."
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          <Card className="p-3">
            <div className="mb-2 flex flex-wrap gap-2">
              {Object.keys(CAMERAS).map((k) => (
                <button
                  key={k}
                  onClick={() => setCamKey(k)}
                  className={cn(
                    "rounded-md border px-2.5 py-1 text-xs transition-colors",
                    k === camKey
                      ? "border-accent/50 bg-accent/10 text-accent-glow"
                      : "border-border bg-surface text-muted hover:text-fg",
                  )}
                >
                  {k}
                </button>
              ))}
            </div>
            <canvas
              ref={cvs}
              width={W}
              height={H}
              className="w-full rounded-lg border border-border"
            />
          </Card>

          {phase === "decide" && (
            <Card className="flex flex-wrap items-center justify-center gap-3 p-4">
              <span className="text-sm font-semibold text-fg">Your call?</span>
              <button onClick={() => call("OUT")} className="rounded-lg border border-ball/40 bg-ball/10 px-5 py-2 text-sm font-bold text-ball hover:bg-ball/20">
                OUT
              </button>
              <button onClick={() => call("UMPIRE'S CALL")} className="rounded-lg border border-accent/40 bg-accent/10 px-5 py-2 text-sm font-bold text-accent-glow hover:bg-accent/20">
                UMPIRE'S CALL
              </button>
              <button onClick={() => call("NOT OUT")} className="rounded-lg border border-willow/40 bg-willow/10 px-5 py-2 text-sm font-bold text-willow hover:bg-willow/20">
                NOT OUT
              </button>
            </Card>
          )}

          {phase === "revealed" && d && (
            <Card className="p-4">
              <div className="flex flex-wrap items-center gap-3">
                <Badge tone={correct ? "willow" : "ball"}>{correct ? "✓ Correct" : "✗ Wrong"}</Badge>
                <span className="text-sm text-muted">
                  You said <b className="text-fg">{userCall}</b> — verdict was{" "}
                  <b className={cn(d.verdict === "OUT" ? "text-ball" : d.verdict === "NOT OUT" ? "text-willow" : "text-accent-glow")}>{d.verdict}</b>
                </span>
                <button onClick={bowlRandom} className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-accent/40 bg-accent/10 px-4 py-2 text-sm font-semibold text-accent-glow hover:bg-accent/20">
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
              <button onClick={bowlRandom} disabled={phase === "bowling"} className="inline-flex items-center gap-1.5 rounded-lg border border-accent/40 bg-accent/10 px-5 py-2 text-sm font-bold text-accent-glow hover:bg-accent/20 disabled:opacity-40">
                <Dices className="h-4 w-4" /> Bowl a random ball
              </button>
              <button onClick={() => bowl(params)} disabled={phase === "bowling"} className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-5 py-2 text-sm font-semibold text-fg hover:border-accent/40 disabled:opacity-40">
                <Play className="h-4 w-4" /> Bowl these settings
              </button>
            </Card>
          )}
        </div>

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
                  <select value={params.hand} onChange={(e) => set({ hand: e.target.value as Hand })} className="input w-auto cursor-pointer py-1 text-xs">
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
