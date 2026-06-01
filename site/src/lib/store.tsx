import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { bumpCacheBust, getCollections, type CollectionMeta } from "./data";

interface Store {
  collections: CollectionMeta[];
  collection: string;
  setCollection: (c: string) => void;
  meta: CollectionMeta | null;
  loading: boolean;
  error: string | null;
  refreshing: boolean;
  refresh: () => Promise<void>;
  lastRefreshed: number;
}

const Ctx = createContext<Store | null>(null);

const LS_KEY = "cricdex.collection";

export function StoreProvider({ children }: { children: ReactNode }) {
  const [collections, setCollections] = useState<CollectionMeta[]>([]);
  const [collection, setCollectionRaw] = useState<string>(
    () => localStorage.getItem(LS_KEY) ?? "ipl",
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const cols = await getCollections();
      setCollections(cols);
      // keep current selection if still present, else first
      setCollectionRaw((prev) =>
        cols.some((c) => c.collection === prev) ? prev : (cols[0]?.collection ?? "ipl"),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const setCollection = useCallback((c: string) => {
    setCollectionRaw(c);
    localStorage.setItem(LS_KEY, c);
  }, []);

  // "Refresh" in a no-backend world = re-pull the cooked JSON past the
  // cache. The GitHub Action (manual "Run workflow") is what re-computes
  // to the latest match date; this button surfaces whatever it last produced.
  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      bumpCacheBust();
      await load();
      setLastRefreshed(Date.now());
    } finally {
      setRefreshing(false);
    }
  }, [load]);

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
        lastRefreshed,
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
