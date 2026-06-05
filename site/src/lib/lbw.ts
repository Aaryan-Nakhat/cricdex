// LBW trainer physics + decision engine. Pure, deterministic (seeded RNG), no
// data / no backend — a synthetic delivery generator for the "Out or Not Out"
// practice game. Units are metres / seconds; the UI scales to pixels.
//
// Coordinate frame (right-handed-ish, batter's stumps at the origin):
//   z = distance down the pitch from the batter's stumps (release ≈ 18 m → 0)
//   x = lateral line (0 = middle-stump line; sign of leg side depends on hand)
//   y = height above the ground (0 = ground)

export type Hand = "RH" | "LH";

export interface DeliveryParams {
  paceKmph: number; // release speed
  length: number; // 0 = full/yorker … 1 = short (maps to release-down angle)
  line: number; // lateral release offset (m): − leg-ward / + off-ward (RH)
  swing: number; // in-flight lateral accel (m/s²): sign = in/out swing
  deviation: number; // off-the-pitch seam/spin sideways kick (m/s) at the bounce
  bounce: number; // pitch hardness → restitution (0.4 dead … 0.7 springy)
  wind: number; // steady lateral accel (m/s²)
  impactZ: number; // how far in front of the stumps the pad is struck (m)
  shotOffered: boolean; // did the batter play a shot?
  hand: Hand;
  margin: number; // umpire's-call band half-width (m); smaller = harder
}

export interface Pt {
  x: number;
  y: number;
  z: number;
}

export type Pitching = "leg" | "in-line" | "off";
export type ImpactZone = "outside-leg" | "in-line" | "outside-off";
export type Wickets = "hitting" | "clipping" | "missing";
export type Verdict = "OUT" | "NOT OUT" | "UMPIRE'S CALL";

export interface Decision {
  pitching: Pitching;
  impactZone: ImpactZone;
  wickets: Wickets;
  verdict: Verdict;
  reasons: string[];
}

export interface Sim {
  params: DeliveryParams;
  path: Pt[]; // release → impact (animate this)
  projected: Pt[]; // impact → stumps plane (the Hawk-Eye projection)
  bounce: Pt | null;
  impact: Pt;
  stump: { x: number; y: number }; // projected ball centre at z = 0
  decision: Decision;
}

// ---- pitch constants (real dimensions, metres) -----------------------------
const HALF_STUMP = 0.1143; // half the 0.2286 m (9") stump line
const BAIL_TOP = 0.711; // top of the stumps
const BALL_R = 0.0365;
const RELEASE_Z = 18.0;
const RELEASE_Y = 2.0;
const G = 9.81;
const DT = 0.002;

// ---- seeded RNG (mulberry32) so a delivery is replayable by seed -----------
export function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/** A fully random delivery within sane ranges (rand in [0,1)). */
export function randomDelivery(rand: () => number, hand: Hand = "RH"): DeliveryParams {
  return {
    paceKmph: lerp(115, 148, rand()),
    length: rand(),
    line: lerp(-0.32, 0.32, rand()),
    swing: lerp(-3.2, 3.2, rand()),
    deviation: lerp(-0.5, 0.5, rand()),
    bounce: lerp(0.42, 0.66, rand()),
    wind: lerp(-1.2, 1.2, rand()),
    impactZ: lerp(0.7, 2.6, rand()),
    shotOffered: rand() < 0.5,
    hand,
    margin: 0.05,
  };
}

function step(p: Pt, v: Pt, ax: number, ay: number): [Pt, Pt] {
  const nv = { x: v.x + ax * DT, y: v.y + ay * DT, z: v.z };
  const np = { x: p.x + nv.x * DT, y: p.y + nv.y * DT, z: p.z + nv.z * DT };
  return [np, nv];
}

export function simulate(params: DeliveryParams): Sim {
  const speed = params.paceKmph / 3.6; // m/s
  // Release-down angle from "length": a fuller ball pitches closer to the
  // batter (travels farther before bouncing → shallower angle); a short ball
  // bounces sooner (steeper). Tuned so the bounce lands ~2–10 m out and the
  // ball then rises to around stump height by the time it reaches the pad.
  const downAngle = lerp(0.07, 0.2, params.length); // radians below horizontal
  let p: Pt = { x: params.line, y: RELEASE_Y, z: RELEASE_Z };
  let v: Pt = {
    x: params.line * -0.12, // slight angle back toward the stumps
    y: -speed * Math.sin(downAngle),
    z: -speed * Math.cos(downAngle),
  };

  const path: Pt[] = [{ ...p }];
  let bounce: Pt | null = null;
  let steps = 0;
  // Flight + post-bounce, until the ball reaches the pad plane (impactZ).
  while (p.z > params.impactZ && steps < 20000) {
    const ax = (bounce ? 0 : params.swing) + params.wind; // swing only pre-bounce
    [p, v] = step(p, v, ax, -G);
    if (!bounce && p.y <= 0) {
      // bounce: clamp to ground, reflect vertical, kick laterally (seam/spin)
      p.y = 0;
      v.y = -v.y * params.bounce;
      v.x += params.deviation;
      bounce = { ...p };
    }
    path.push({ ...p });
    steps++;
  }
  const impact: Pt = { ...p };

  // Project from the impact onward to the stumps plane (z = 0) — the would-be
  // path had the pad not intervened. Gravity continues; no new swing.
  const projected: Pt[] = [{ ...p }];
  let steps2 = 0;
  while (p.z > 0 && p.y >= -0.1 && steps2 < 20000) {
    [p, v] = step(p, v, params.wind * 0, -G);
    projected.push({ ...p });
    steps2++;
  }
  const stump = { x: p.x, y: p.y };

  return {
    params,
    path,
    projected,
    bounce,
    impact,
    stump,
    decision: decide(params, bounce, impact, stump),
  };
}

function decide(
  params: DeliveryParams,
  bounce: Pt | null,
  impact: Pt,
  stump: { x: number; y: number },
): Decision {
  // Convention: +x = off side, −x = leg side for a RH batter (flip for LH).
  const legSign = params.hand === "RH" ? -1 : 1; // x-sign of the leg side
  const reasons: string[] = [];

  // 1) Pitching — only "outside leg" saves the batter.
  const bx = bounce ? bounce.x : impact.x; // full-toss → judge at impact
  let pitching: Pitching = "in-line";
  if (legSign * bx > HALF_STUMP) pitching = "leg";
  else if (-legSign * bx > HALF_STUMP) pitching = "off";

  // 2) Impact zone.
  let impactZone: ImpactZone = "in-line";
  if (legSign * impact.x > HALF_STUMP) impactZone = "outside-leg";
  else if (-legSign * impact.x > HALF_STUMP) impactZone = "outside-off";

  // 3) Wickets — project the ball centre onto the stump face.
  const distX = Math.abs(stump.x);
  const band = BALL_R + params.margin; // umpire's-call half-band
  const xHit = distX <= HALF_STUMP - BALL_R;
  const xMiss = distX > HALF_STUMP + band;
  const underBails = stump.y > 0 && stump.y <= BAIL_TOP - BALL_R;
  const overBails = stump.y > BAIL_TOP + band || stump.y <= 0;
  let wickets: Wickets;
  if (xMiss || overBails) wickets = "missing";
  else if (xHit && underBails) wickets = "hitting";
  else wickets = "clipping";

  // verdict
  let verdict: Verdict;
  if (pitching === "leg") {
    verdict = "NOT OUT";
    reasons.push("Pitched outside leg stump");
  } else if (impactZone === "outside-off" && params.shotOffered) {
    verdict = "NOT OUT";
    reasons.push("Impact outside off and a shot was offered");
  } else if (wickets === "missing") {
    verdict = "NOT OUT";
    reasons.push("Ball missing the stumps");
  } else if (wickets === "clipping") {
    verdict = "UMPIRE'S CALL";
    reasons.push("Ball clipping the stumps — umpire's call");
  } else {
    verdict = "OUT";
    reasons.push("Pitched in line / off, impact in line, smashing the stumps");
  }
  return { pitching, impactZone, wickets, verdict, reasons };
}

export const PITCH = { HALF_STUMP, BAIL_TOP, BALL_R, RELEASE_Z } as const;
