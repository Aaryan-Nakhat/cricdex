// Page selections that live in the URL query (`#/page?key=value`), so a
// copied link reproduces the view and browser back/forward walks through it.
// The URL is the single source of truth: values are read from it on every
// render and written back with `update`. Defaults are left out of the URL,
// and a value that turns out to be invalid (e.g. a player id from another
// league) is quietly removed once the page knows it's invalid.
import { useCallback, useEffect, useMemo, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { useStore } from "./store";
import {
  ACTIVITY_OPTS,
  BOWLING_OPTS,
  POSITION_OPTS,
  ROLE_OPTS,
  type Filters,
} from "./filters";

/** Own-key check, so "constructor" in a URL isn't mistaken for a lookup-table key. */
export const hasKey = (obj: object | null | undefined, k: string) =>
  !!obj && Object.prototype.hasOwnProperty.call(obj, k);

type Patch = Record<string, string | number | null | undefined>;
export interface UpdateOpts {
  /** true (default) for continuous inputs; false adds a history entry for discrete picks. */
  replace?: boolean;
}

/** The current hash-route query, read at call time so several setters in one tick compose. */
function liveParams(fallback: URLSearchParams): URLSearchParams {
  if (typeof window === "undefined") return new URLSearchParams(fallback);
  const h = window.location.hash;
  const q = h.indexOf("?");
  return new URLSearchParams(q >= 0 ? h.slice(q + 1) : "");
}

export function useUrlParams() {
  const [params, setParams] = useSearchParams();
  const { collection } = useStore();
  const update = useCallback(
    (patch: Patch, opts: UpdateOpts = {}) => {
      const next = liveParams(params);
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === undefined || v === "") next.delete(k);
        else next.set(k, String(v));
      }
      // a link with page state also carries its league (`c`), since player ids are per league
      next.delete("c");
      if ([...next.keys()].length > 0) next.set("c", collection);
      if (next.toString() === liveParams(params).toString()) return;
      setParams(next, { replace: opts.replace ?? true });
    },
    [params, setParams, collection],
  );
  return { params, update };
}

interface StateOpts<T extends string> extends UpdateOpts {
  /** Accept only these values; anything else reads as the fallback and is cleaned from the URL. */
  valid?: readonly T[] | ((v: string) => boolean);
  /** Whether `valid` can be judged yet (e.g. the player list has loaded). Default true. */
  ready?: boolean;
}

/**
 * One string param. Returns the value (or `fallback` when absent/invalid) and
 * a setter; setting the fallback (or "") removes the key.
 */
export function useUrlState<T extends string = string>(
  key: string,
  fallback: T,
  opts: StateOpts<T> = {},
): [T, (v: T | null) => void] {
  const { params, update } = useUrlParams();
  const { valid, ready = true, replace } = opts;
  const raw = params.get(key);
  const ok = (v: string) =>
    !valid ? true : typeof valid === "function" ? valid(v) : (valid as readonly string[]).includes(v);
  const value = raw !== null && raw !== "" && (!ready || ok(raw)) ? (raw as T) : fallback;
  const bad = raw !== null && ready && (raw === "" || !ok(raw));

  useEffect(() => {
    if (bad) update({ [key]: null }, { replace: true });
  }, [bad, key, update]);

  const set = useCallback(
    (v: T | null) => update({ [key]: v === fallback ? null : v }, { replace }),
    [key, fallback, update, replace],
  );
  return [value, set];
}

/** A whole-number param clamped to [min, max]. */
export function useUrlNumber(
  key: string,
  fallback: number,
  { min = 0, max = Number.MAX_SAFE_INTEGER }: { min?: number; max?: number } = {},
): [number, (v: number) => void] {
  const [raw, setRaw] = useUrlState(key, String(fallback), {
    valid: (v) => /^\d+$/.test(v) && Number(v) >= min && Number(v) <= max,
  });
  const set = useCallback((v: number) => setRaw(String(v)), [setRaw]);
  return [Number(raw), set];
}

/**
 * An id param (e.g. a player's cricsheet id) that must exist in `ids`. Once
 * `ready`, an unknown id (another league's, a typo) is dropped from the URL.
 * Picking pushes a history entry so back/forward walks through the picks.
 */
export function useUrlId(
  key: string,
  ids: { has: (id: string) => boolean },
  ready: boolean,
): [string | null, (v: string | null) => void] {
  const [v, set] = useUrlState<string>(key, "", { valid: (x) => ids.has(x), ready, replace: false });
  return [v || null, set];
}

/** Remove `keys` from the URL when `value` changes (not on first render) — e.g. picks on a league switch. */
export function useClearOnChange(value: unknown, keys: string[]) {
  const { update } = useUrlParams();
  const prev = useRef(value);
  const keyList = keys.join(",");
  useEffect(() => {
    if (prev.current !== value) update(Object.fromEntries(keyList.split(",").map((k) => [k, null])));
    prev.current = value;
  }, [value, keyList, update]);
}

// ---- player-row filters (FilterBar) ---------------------------------------

const FILTER_KEYS = {
  minMatches: "min",
  activity: "active",
  role: "role",
  bowling: "bowl",
  position: "pos",
  country: "country",
} as const satisfies Record<keyof Filters, string>;

const values = (opts: { value: string }[]) => opts.map((o) => o.value);
const FILTER_VALID: Record<keyof Filters, (v: string) => boolean> = {
  minMatches: (v) => /^\d+$/.test(v) && Number(v) <= 500,
  activity: (v) => values(ACTIVITY_OPTS).includes(v),
  role: (v) => values(ROLE_OPTS).includes(v),
  bowling: (v) => values(BOWLING_OPTS).includes(v),
  position: (v) => values(POSITION_OPTS).includes(v),
  country: (v) => /^[A-Za-z]{2,4}$/.test(v),
};

const DIMS = Object.keys(FILTER_KEYS) as (keyof Filters)[];

/** FilterBar state in the URL; only the dimensions that differ from `defaults` are written. */
export function useUrlFilters(defaults: Filters): [Filters, (f: Filters) => void] {
  const { params, update } = useUrlParams();
  const filters = useMemo(() => {
    const f: Record<string, unknown> = { ...defaults };
    for (const d of DIMS) {
      const raw = params.get(FILTER_KEYS[d]);
      if (raw === null || raw === "" || !FILTER_VALID[d](raw)) continue;
      f[d] = d === "minMatches" ? Number(raw) : raw;
    }
    return f as unknown as Filters;
  }, [params, defaults]);

  const badKeys = DIMS
    .filter((d) => {
      const raw = params.get(FILTER_KEYS[d]);
      return raw !== null && (raw === "" || !FILTER_VALID[d](raw));
    })
    .map((d) => FILTER_KEYS[d])
    .join(",");
  useEffect(() => {
    if (badKeys) update(Object.fromEntries(badKeys.split(",").map((k) => [k, null])));
  }, [badKeys, update]);

  const set = useCallback(
    (f: Filters) => {
      const patch: Patch = {};
      for (const d of DIMS) patch[FILTER_KEYS[d]] = f[d] === defaults[d] ? null : String(f[d]);
      update(patch);
    },
    [defaults, update],
  );
  return [filters, set];
}
