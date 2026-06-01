import { useMemo } from "react";
import { useAsync } from "./useAsync";
import { getPlayers, type PlayerRow } from "./data";
import type { Option } from "@/components/Combobox";

export function usePlayers(collection: string) {
  const { data, loading, error } = useAsync(() => getPlayers(collection), [collection]);

  const players = data ?? [];

  const options: Option[] = useMemo(
    () =>
      players.map((p) => ({
        value: p.cricsheet_id,
        // Show the full name when we have it; keep the Cricsheet short
        // form alongside so searching either ("Manish" or "MK Pandey")
        // matches. The Combobox filters on `label` + `search`.
        label: p.full_name && p.full_name !== p.name ? `${p.full_name} (${p.name})` : p.name,
        search: `${p.full_name} ${p.name}`,
        hint: `${p.matches} matches`,
      })),
    [players],
  );

  const byName = useMemo(() => {
    const m = new Map<string, PlayerRow>();
    for (const p of players) m.set(p.name, p);
    return m;
  }, [players]);

  const byId = useMemo(() => {
    const m = new Map<string, PlayerRow>();
    for (const p of players) m.set(p.cricsheet_id, p);
    return m;
  }, [players]);

  return { players, options, byName, byId, loading, error };
}
