"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity, Bell, CalendarDays, CalendarRange, ChefHat, Dumbbell, Home, MessageCircle, Settings, TrendingUp,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ProviderPicker } from "@/components/ai-picker";
import { api } from "@/lib/api";
import { cx } from "@/lib/utils";

const NAV = [
  { href: "/today", label: "Today", icon: Home },
  { href: "/dashboard", label: "Dashboard", icon: Activity },
  { href: "/nutrition", label: "Nutrition", icon: ChefHat },
  { href: "/meals", label: "Meals", icon: CalendarRange },
  { href: "/workouts", label: "Workouts", icon: Dumbbell },
  { href: "/schedule", label: "Planner", icon: CalendarDays },
  { href: "/progress", label: "Progress", icon: TrendingUp },
  { href: "/assistant", label: "Assistant", icon: MessageCircle },
  { href: "/settings", label: "Settings", icon: Settings },
];

const MOBILE = [NAV[0], NAV[1], NAV[2], NAV[4], NAV[6]];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-line bg-surface md:flex">
      <div className="px-5 pb-6 pt-7">
        <Link href="/today" className="font-display text-[22px] font-bold tracking-tight">
          Health<span className="text-accent">OS</span>
        </Link>
        <div className="mt-0.5 text-[11px] font-medium uppercase tracking-[0.14em] text-faint">
          Personal health system
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 px-3">
        {NAV.map((item) => {
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cx(
                "flex items-center gap-3 rounded-xl px-3 py-2.5 text-[14px] font-medium transition-colors",
                active ? "bg-surface-2 text-ink" : "text-muted hover:bg-surface-2/60 hover:text-ink"
              )}
            >
              <item.icon size={18} strokeWidth={active ? 2.4 : 2} className={active ? "text-accent" : ""} />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="space-y-3 p-4">
        <ProviderPicker direction="up" />
        <div className="text-[11px] leading-relaxed text-faint">
          Not a medical device.
          <br />
          For wellness tracking only.
        </div>
      </div>
    </aside>
  );
}

export function BottomNav() {
  const pathname = usePathname();
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/95 backdrop-blur md:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="grid grid-cols-5">
        {MOBILE.map((item) => {
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cx(
                "flex flex-col items-center gap-0.5 py-2.5 text-[10px] font-medium",
                active ? "text-accent" : "text-muted"
              )}
            >
              <item.icon size={21} strokeWidth={active ? 2.4 : 1.9} />
              {item.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

export function TopBar({ title, right }: { title: string; right?: React.ReactNode }) {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between gap-2 px-4 sm:px-6">
        <h1 className="min-w-0 truncate font-display text-lg font-semibold tracking-tight">{title}</h1>
        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          {right}
          <NotificationsBell />
        </div>
      </div>
    </header>
  );
}

function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { data } = useQuery({
    queryKey: ["notifications"],
    queryFn: api.notifications,
    refetchInterval: 5 * 60_000,
    staleTime: 60_000,
  });

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const count = data?.count ?? 0;
  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        aria-label={`Notifications${count ? ` (${count})` : ""}`}
        className="relative rounded-xl border border-line bg-surface p-2 text-muted transition-colors hover:text-ink"
      >
        <Bell size={16} />
        {count > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[9px] font-bold text-accent-ink">
            {count}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-11 z-50 w-80 rounded-2xl border border-line bg-surface p-2 shadow-xl">
          <div className="flex items-center justify-between px-2 py-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-faint">Notifications</span>
            {data?.quiet_hours_active && <span className="text-[10px] text-faint">quiet hours</span>}
          </div>
          {!data || data.notifications.length === 0 ? (
            <p className="px-2 py-4 text-center text-[13px] text-faint">All clear — nothing needs attention.</p>
          ) : (
            data.notifications.map((n, i) => (
              <Link
                key={i}
                href={n.href}
                onClick={() => setOpen(false)}
                className="block rounded-xl px-2.5 py-2.5 transition-colors hover:bg-surface-2"
              >
                <div className="flex items-center gap-2">
                  <span className={cx(
                    "h-1.5 w-1.5 shrink-0 rounded-full",
                    n.priority === "high" ? "bg-accent" : "bg-gold"
                  )} />
                  <span className="text-[13px] font-semibold">{n.title}</span>
                </div>
                <p className="mt-0.5 pl-3.5 text-xs text-faint">{n.reason}</p>
              </Link>
            ))
          )}
        </div>
      )}
    </div>
  );
}
