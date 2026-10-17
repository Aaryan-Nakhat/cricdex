import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useSearchParams } from "react-router-dom";
import { bumpCacheBust, getCollections, getLeagues, type CollectionMeta } from "./data";

interface Store {
  collections: CollectionMeta[];
  collection: string;
  setCollection: (c: string) => void;
  meta: CollectionMeta | null;
  loading: boolean;
  error: string | null;
  refreshing: boolean;
  refresh: () => Promise<void>;
  /** Bumped on every Refresh; useAsync re-fetches on it, so open pages reload in place. */
  version: number;
}

const Ctx = createContext<Store | null>(null);

const LS_KEY = "cricdex.collection";

/** A shared link's `?c=<league>` wins over the remembered league (validated once the list loads). */
function initialCollection(): string {
  const h = typeof window === "undefined" ? "" : window.location.hash;
  const q = h.indexOf("?");
  const fromUrl = q >= 0 ? new URLSearchParams(h.slice(q + 1)).get("c") : null;
  return fromUrl || localStorage.getItem(LS_KEY) || "ipl";
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [collections, setCollections] = useState<CollectionMeta[]>([]);
  const [collection, setCollectionRaw] = useState<string>(initialCollection);
  const [params, setParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [version, setVersion] = useState(0);

  const load = useCallback(async (initial: boolean) => {
    if (initial) setLoading(true); // a refresh keeps the page mounted
    setError(null);
    try {
      // the registry gives every league its label; without it labels fall back to the key
      const [cols] = await Promise.all([getCollections(), getLeagues().catch(() => null)]);
      setCollections(cols);
      // keep current selection if still present, else first
      setCollectionRaw((prev) => {
        const next = cols.some((c) => c.collection === prev) ? prev : (cols[0]?.collection ?? "ipl");
        localStorage.setItem(LS_KEY, next);
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(true);
  }, [load]);

  const setCollection = useCallback(
    (c: string) => {
      setCollectionRaw(c);
      localStorage.setItem(LS_KEY, c);
      // keep a shared link's league tag in step, so a reload doesn't switch back
      if (params.has("c")) {
        const next = new URLSearchParams(params);
        next.set("c", c);
        setParams(next, { replace: true });
      }
    },
    [params, setParams],
  );

  // "Refresh" in a no-backend world = re-pull the cooked JSON past the
  // cache. The GitHub Action (manual "Run workflow") is what re-computes
  // to the latest match date; this button surfaces whatever it last produced.
  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      bumpCacheBust();
      await load(false);
      setVersion((v) => v + 1);
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  // A link can name its league (`?c=<league>`, e.g. a Scout row opening a BBL player's profile): follow it.
  const urlC = params.get("c");
  useEffect(() => {
    if (urlC && urlC !== collection && collections.some((c) => c.collection === urlC)) {
      setCollectionRaw(urlC);
      localStorage.setItem(LS_KEY, urlC);
    }
  }, [urlC, collection, collections]);

  const meta = collections.find((c) => c.collection === collection) ?? null;

  return (
    <Ctx.Provider
      value={{
        collections,
        collection,
        setCollection,
        meta,
        loading,
        error,
        refreshing,
        refresh,
        version,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useStore() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useStore outside provider");
  return v;
}
