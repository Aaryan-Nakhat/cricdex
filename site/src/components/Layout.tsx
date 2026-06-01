import { useState } from "react";
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

  return (
    <div className="min-h-screen">
      <Header />
      <div className="mx-auto flex max-w-[1400px] gap-0 px-0 sm:px-6">
        {/* desktop sidebar */}
        <aside className="sticky top-16 hidden h-[calc(100vh-4rem)] w-60 shrink-0 overflow-y-auto border-r border-border lg:block">
          <Sidebar />
        </aside>

        {/* mobile nav toggle */}
        <button
          className="btn fixed bottom-5 right-5 z-40 h-12 w-12 rounded-full p-0 shadow-card lg:hidden"
          onClick={() => setMobileNav(true)}
          aria-label="menu"
        >
          <Menu className="h-5 w-5" />
        </button>
        {mobileNav && (
          <div className="fixed inset-0 z-50 lg:hidden">
            <div className="absolute inset-0 bg-black/60" onClick={() => setMobileNav(false)} />
            <div className="absolute left-0 top-0 h-full w-72 overflow-y-auto border-r border-border bg-bg">
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <span className="font-bold">Menu</span>
                <button onClick={() => setMobileNav(false)}>
                  <X className="h-5 w-5 text-muted" />
                </button>
              </div>
              <Sidebar onNavigate={() => setMobileNav(false)} />
            </div>
          </div>
        )}

        {/* main */}
        <main className={cn("min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8", "pb-24 lg:pb-10")}>
          {loading ? (
            <Spinner label="Loading collections…" />
          ) : error ? (
            <ErrorBox message={error} />
          ) : (
            <div key={loc.pathname}>
              <Outlet />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
