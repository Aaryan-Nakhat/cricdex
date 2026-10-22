import {
  LayoutDashboard,
  Trophy,
  UserSearch,
  GitCompareArrows,
  Swords,
  Crosshair,
  Timer,
  TrendingUp,
  Handshake,
  Activity,
  Network,
  Gavel,
  Scale,
  ClipboardList,
  Medal,
  MapPin,
  BookOpen,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  group: string;
  blurb: string;
}

export const NAV: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, group: "Start", blurb: "The dataset at a glance + what CricDex does." },
  { to: "/leaderboards", label: "Leaderboards", icon: Trophy, group: "Analyse", blurb: "Twelve boards — win chance added per match, nine context metrics, keeping and fielding — each with how to read it." },
  { to: "/player", label: "Player profile", icon: UserSearch, group: "Analyse", blurb: "Full dossier: skills, metrics, dismissals, twins." },
  { to: "/compare", label: "Compare", icon: GitCompareArrows, group: "Analyse", blurb: "Side-by-side across every number." },
  { to: "/head-to-head", label: "Head-to-head", icon: Swords, group: "Analyse", blurb: "P(A is better than B) from the Bayesian model." },
  { to: "/matchups", label: "Matchups", icon: Crosshair, group: "Analyse", blurb: "Batter vs bowler head-to-heads + how a batter fares against pace vs spin." },
  { to: "/phase", label: "Phase specialists", icon: Timer, group: "Analyse", blurb: "Who dominates the powerplay, middle overs & death." },
  { to: "/form", label: "Form board", icon: TrendingUp, group: "Analyse", blurb: "Last-12-months form vs career baseline — who's hot, who's cold." },
  { to: "/partnerships", label: "Partnerships", icon: Handshake, group: "Analyse", blurb: "Batter-pair stands — most productive partners + all-time best partnerships." },
  { to: "/aging", label: "Aging curves", icon: Activity, group: "Analyse", blurb: "How batting & bowling performance changes with age — with a per-player overlay." },
  { to: "/scout", label: "Scout", icon: Network, group: "Scout", blurb: "Look-alikes across IPL, SMAT & every overseas league — price, savings & draft." },
  { to: "/auction", label: "Auction room", icon: Gavel, group: "Scout", blurb: "Simulate a real IPL auction — retain, then bid for the rest." },
  { to: "/keep", label: "Keep or release", icon: Scale, group: "Scout", blurb: "Before the retention deadline: which players to keep, at what surplus, and what the squad needs after." },
  { to: "/bidplan", label: "Bid plan (beta)", icon: ClipboardList, group: "Scout", blurb: "Beta. Before the auction: whom to bid for, each target's max bid and odds, and a fallback per role. Not yet proven against real franchises." },
  { to: "/records", label: "Records", icon: Medal, group: "Explore", blurb: "All-time record books." },
  { to: "/venues", label: "Venues", icon: MapPin, group: "Explore", blurb: "Ground conditions: totals, phases, chasing." },
  { to: "/about", label: "How it works", icon: BookOpen, group: "Explore", blurb: "The models, plainly explained." },
];

export const NAV_GROUPS = ["Start", "Analyse", "Scout", "Explore"];
