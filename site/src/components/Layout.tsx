import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Menu, X } from "lucide-react";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { useStore } from "@/lib/store";
import { Spinner, ErrorBox } from "./ui";
import { cn } from "@/lib/utils";

export function Layout() {
  const { loading, error } = useStore();
  const [mobileNav, setMobileNav] = useState(false);
  const loc = useLocation();
  const drawer = useRef<HTMLDivElement>(null);

  // Mobile drawer: Escape closes it, focus moves in, and a route change closes it.
  useEffect(() => {
    if (!mobileNav) return;
    drawer.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMobileNav(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mobileNav]);
  useEffect(() => setMobileNav(false), [loc.pathname]);

  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-xl focus:bg-card focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <Header />
      <div className="mx-auto flex max-w-[1400px] gap-0 px-0 sm:px-6">
        <aside className="sticky top-16 hidden h-[calc(100vh-4rem)] w-60 shrink-0 overflow-y-auto border-r border-border lg:block">
          <Sidebar />
        </aside>

        <button
          className="btn fixed bottom-5 right-5 z-40 h-12 w-12 rounded-full p-0 shadow-glow lg:hidden"
          onClick={() => setMobileNav(true)}
          aria-label="Open menu"
          aria-expanded={mobileNav}
        >
          <Menu className="h-5 w-5" />
        </button>
        {mobileNav && (
          <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setMobileNav(false)} />
            <div
              ref={drawer}
              tabIndex={-1}
              className="absolute left-0 top-0 h-full w-72 overflow-y-auto border-r border-border bg-bg outline-none"
            >
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <span className="font-bold">Menu</span>
                <button onClick={() => setMobileNav(false)} aria-label="Close menu" className="rounded-lg p-1">
                  <X className="h-5 w-5 text-muted" />
                </button>
              </div>
              <Sidebar onNavigate={() => setMobileNav(false)} />
            </div>
          </div>
        )}

        <main id="main" className={cn("min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8", "pb-24 lg:pb-10")}>
          {loading ? (
            <Spinner label="Loading leagues…" />
          ) : error ? (
            <ErrorBox message={error} />
          ) : (
            <div key={loc.pathname} className="animate-fade-up">
              <Outlet />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
