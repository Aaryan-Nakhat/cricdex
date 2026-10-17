import { useCallback, useMemo } from "react";
import { useAsync } from "./useAsync";
import { displayName, getPlayers, type PlayerRow } from "./data";
import type { Option } from "@/components/Combobox";

export function usePlayers(collection: string) {
  const { data, loading, error } = useAsync(() => getPlayers(collection), [collection]);

  const players = data ?? [];

  const options: Option[] = useMemo(
    () =>
      players.map((p) => {
        const shown = displayName(p);
        return {
          value: p.cricsheet_id,
          // the fan name, with the scorecard name alongside when it differs ("Virat Kohli (V Kohli)")
          // (older exports without display_name fall back to the full name)
          label:
            shown !== p.name
              ? `${shown} (${p.name})`
              : !p.display_name && p.full_name && p.full_name !== p.name
                ? `${p.full_name} (${p.name})`
                : p.name,
          // searchable by every name we know: scorecard, display, full name and aliases
          search: [p.name, p.display_name, p.full_name, ...(p.aliases ?? [])].filter(Boolean).join(" "),
          hint: `${p.matches} matches`,
        };
      }),
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

  /** Fan-facing name for a scorecard name (leaderboard rows carry the scorecard name). */
  const nameOf = useCallback((scorecard: string) => displayName(byName.get(scorecard) ?? { name: scorecard }), [byName]);

  return { players, options, byName, byId, nameOf, loading, error };
}
