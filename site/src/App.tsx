import { Routes, Route } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { Overview } from "@/pages/Overview";
import { Leaderboards } from "@/pages/Leaderboards";
import { PlayerProfile } from "@/pages/PlayerProfile";
import { Compare } from "@/pages/Compare";
import { HeadToHead } from "@/pages/HeadToHead";
import { Scout } from "@/pages/Scout";
import { Auction } from "@/pages/Auction";
import { Records } from "@/pages/Records";
import { Venues } from "@/pages/Venues";
import { About } from "@/pages/About";
import { NotFound } from "@/pages/NotFound";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Overview />} />
        <Route path="/leaderboards" element={<Leaderboards />} />
        <Route path="/player" element={<PlayerProfile />} />
        <Route path="/compare" element={<Compare />} />
        <Route path="/head-to-head" element={<HeadToHead />} />
        <Route path="/scout" element={<Scout />} />
        <Route path="/auction" element={<Auction />} />
        <Route path="/records" element={<Records />} />
        <Route path="/venues" element={<Venues />} />
        <Route path="/about" element={<About />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
