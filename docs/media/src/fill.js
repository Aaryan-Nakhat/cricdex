/* Helpers for the README visuals: the numbers come from data.js (window.MEDIA, written by scripts/media_data.py).
   A page fills its data-bearing parts with fill("id", html) from an inline script, before motion.js runs. */
const M = window.MEDIA;
const fx = (x, d = 1) => Number(x).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const sgn = (x, d = 1) => (x > 0 ? "+" : x < 0 ? "−" : "") + fx(Math.abs(x), d);
const pct = (p) => (p >= 0.995 ? ">99%" : p <= 0.005 ? "<1%" : `${Math.round(100 * p)}%`);
const fill = (id, html) => { document.getElementById(id).innerHTML = html; };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const asOf = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
const teamName = { CSK: "Chennai", MI: "Mumbai", RCB: "Bengaluru", KKR: "Kolkata", DC: "Delhi", PBKS: "Punjab",
  SRH: "Hyderabad", GT: "Gujarat", RR: "Rajasthan", LSG: "Lucknow" };
const numWord = (n) => ["no", "one", "two", "three", "four", "five", "six"][n] ?? String(n);
/* an SVG path for a normal density over [x0, x1] runs (axis px = (x - x0) * sx), peak scaled to `peak` px */
function normalPath(mean, sd, x0, x1, sx, base, peak, close) {
  const pts = [];
  for (let px = 0; px <= (x1 - x0) * sx + 0.01; px += 4) {
    const x = x0 + px / sx, z = (x - mean) / sd;
    pts.push(`L${px.toFixed(1)} ${(base - peak * Math.exp(-0.5 * z * z)).toFixed(1)}`);
  }
  const d = "M" + pts.join(" ").slice(1);
  return close ? `${d} L${((x1 - x0) * sx).toFixed(1)} ${base} L0 ${base} Z` : d;
}
