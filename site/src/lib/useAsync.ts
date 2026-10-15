import { useEffect, useRef, useState } from "react";
import { useStore } from "./store";

interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/** Run an async fetcher, re-running whenever any dep changes — and on every Refresh. Cancels stale results so
 * fast collection-switching never flashes old data. A dep change (new metric, new player) shows `loading`; a
 * Refresh re-fetches in the background and keeps the current data on screen until the new copy arrives. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const { version } = useStore();
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    loading: true,
    error: null,
  });
  const lastDeps = useRef<string | null>(null);

  useEffect(() => {
    let alive = true;
    const key = JSON.stringify(deps);
    const refreshOnly = lastDeps.current === key; // same inputs, only the Refresh counter moved
    lastDeps.current = key;
    if (!refreshOnly) setState((s) => ({ ...s, loading: true, error: null }));
    fn()
      .then((data) => {
        if (alive) setState({ data, loading: false, error: null });
      })
      .catch((e: unknown) => {
        if (!alive) return;
        const error = e instanceof Error ? e.message : String(e);
        // a failed background refresh keeps the data that's already on screen
        setState((s) => (refreshOnly && s.data !== null ? { ...s, loading: false } : { data: null, loading: false, error }));
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, version]);

  return state;
}
