import {
  LayoutDashboard,
  Trophy,
  UserSearch,
  GitCompareArrows,
  Swords,
  Network,
  Gavel,
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
  { to: "/leaderboards", label: "Leaderboards", icon: Trophy, group: "Analyse", blurb: "10 novel impact metrics, ranked." },
  { to: "/player", label: "Player profile", icon: UserSearch, group: "Analyse", blurb: "Full dossier: skills, metrics, dismissals, twins." },
  { to: "/compare", label: "Compare", icon: GitCompareArrows, group: "Analyse", blurb: "Side-by-side across every number." },
  { to: "/head-to-head", label: "Head-to-head", icon: Swords, group: "Analyse", blurb: "P(A is better than B) from the Bayesian model." },
  { to: "/scout", label: "Scout", icon: Network, group: "Scout", blurb: "Find look-alikes across IPL, SMAT & BBL." },
  { to: "/auction", label: "Auction room", icon: Gavel, group: "Scout", blurb: "Optimise a squad under purse + overseas caps." },
  { to: "/records", label: "Records", icon: Medal, group: "Explore", blurb: "All-time record books." },
  { to: "/venues", label: "Venues", icon: MapPin, group: "Explore", blurb: "Ground conditions: totals, phases, chasing." },
  { to: "/about", label: "How it works", icon: BookOpen, group: "Explore", blurb: "The models, plainly explained." },
];

export const NAV_GROUPS = ["Start", "Analyse", "Scout", "Explore"];
