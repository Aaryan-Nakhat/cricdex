import {
  LayoutDashboard,
  Trophy,
  UserSearch,
  GitCompareArrows,
  Swords,
  Crosshair,
  Timer,
  TrendingUp,
  Network,
  Gavel,
  Medal,
  MapPin,
  Eye,
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
  { to: "/leaderboards", label: "Leaderboards", icon: Trophy, group: "Analyse", blurb: "10 novel impact metrics, ranked." },
  { to: "/player", label: "Player profile", icon: UserSearch, group: "Analyse", blurb: "Full dossier: skills, metrics, dismissals, twins." },
  { to: "/compare", label: "Compare", icon: GitCompareArrows, group: "Analyse", blurb: "Side-by-side across every number." },
  { to: "/head-to-head", label: "Head-to-head", icon: Swords, group: "Analyse", blurb: "P(A is better than B) from the Bayesian model." },
  { to: "/matchups", label: "Matchups", icon: Crosshair, group: "Analyse", blurb: "Batter vs bowler head-to-heads + how a batter fares against pace vs spin." },
  { to: "/phase", label: "Phase specialists", icon: Timer, group: "Analyse", blurb: "Who dominates the powerplay, middle overs & death." },
  { to: "/form", label: "Form board", icon: TrendingUp, group: "Analyse", blurb: "Last-12-months form vs career baseline — who's hot, who's cold." },
  { to: "/scout", label: "Scout", icon: Network, group: "Scout", blurb: "Look-alikes across IPL, SMAT & overseas (BBL/SA20/CPL/Blast) — price, savings & draft." },
  { to: "/auction", label: "Auction room", icon: Gavel, group: "Scout", blurb: "Simulate a real IPL auction — retain, then bid for the rest." },
  { to: "/records", label: "Records", icon: Medal, group: "Explore", blurb: "All-time record books." },
  { to: "/venues", label: "Venues", icon: MapPin, group: "Explore", blurb: "Ground conditions: totals, phases, chasing." },
  { to: "/umpires-eye", label: "Umpire's Eye", icon: Eye, group: "Explore", blurb: "Out or not out? A physics-sim LBW trainer — call it before the ball-tracking does." },
  { to: "/about", label: "How it works", icon: BookOpen, group: "Explore", blurb: "The models, plainly explained." },
];

export const NAV_GROUPS = ["Start", "Analyse", "Scout", "Explore"];
