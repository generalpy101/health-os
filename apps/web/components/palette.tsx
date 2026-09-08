"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "@/lib/api";
import { cx } from "@/lib/utils";
import { useToast } from "@/components/ui";

const ACTIONS = [
  { label: "Today", href: "/today", hint: "daily view" },
  { label: "Dashboard", href: "/dashboard", hint: "widgets & goals" },
  { label: "Log food", href: "/nutrition", hint: "nutrition" },
  { label: "Meal planner", href: "/meals", hint: "weekly plan" },
  { label: "Log workout", href: "/workouts", hint: "training" },
  { label: "Recipes", href: "/recipes", hint: "your recipes" },
  { label: "Planner", href: "/schedule", hint: "week schedule" },
  { label: "Progress", href: "/progress", hint: "trends & charts" },
  { label: "Habits", href: "/habits", hint: "daily habits" },
  { label: "Assistant", href: "/assistant", hint: "ask anything" },
  { label: "Settings", href: "/settings", hint: "profile & AI" },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const toast = useToast();
  const queryClient = useQueryClient();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setIndex(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  const items = useMemo(() => {
    const q = query.toLowerCase().trim();
    const base = ACTIONS.filter((a) => !q || a.label.toLowerCase().includes(q) || a.hint.includes(q));
    if (q) {
      return [
        ...base,
        { label: `Ask AI: “${query}”`, href: "__ai__", hint: "assistant" },
        { label: `Log it: “${query}”`, href: "__log__", hint: "natural language log" },
      ];
    }
    return base;
  }, [query]);

  async function run(href: string) {
    if (href === "__ai__") {
      setOpen(false);
      router.push("/assistant");
      // hand the query to the assistant page via sessionStorage (simple, no global store)
      sessionStorage.setItem("healthos-pending-chat", query);
      return;
    }
    if (href === "__log__") {
      setBusy(true);
      try {
        const res = await api.chat(query);
        toast(res.reply.slice(0, 120));
        queryClient.invalidateQueries();
        setOpen(false);
      } catch (e) {
        toast(e instanceof Error ? e.message : "Failed", "err");
      } finally {
        setBusy(false);
      }
      return;
    }
    setOpen(false);
    router.push(href);
  }

  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-[70] flex items-start justify-center px-4 pt-[18dvh]" role="dialog" aria-modal="true" aria-label="Command palette">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" onClick={() => setOpen(false)} />
      <div className="relative w-full max-w-lg overflow-hidden rounded-2xl border border-line bg-surface shadow-2xl">
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Search size={16} className="shrink-0 text-faint" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setIndex(0); }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setIndex((i) => Math.min(i + 1, items.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setIndex((i) => Math.max(i - 1, 0)); }
              if (e.key === "Enter" && items[index]) run(items[index].href);
            }}
            placeholder="Go anywhere, log anything, ask AI…"
            className="h-13 flex-1 bg-transparent py-3.5 text-[15px] placeholder:text-faint focus:outline-none"
          />
          <kbd className="rounded-md border border-line px-1.5 py-0.5 text-[10px] font-medium text-faint">esc</kbd>
        </div>
        <div className="max-h-80 overflow-y-auto p-1.5">
          {items.length === 0 && (
            <p className="px-3 py-6 text-center text-sm text-faint">No matches</p>
          )}
          {items.map((item, i) => (
            <button
              key={item.href + item.label}
              onMouseEnter={() => setIndex(i)}
              onClick={() => run(item.href)}
              disabled={busy}
              className={cx(
                "flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-left text-sm transition-colors",
                i === index ? "bg-surface-2 text-ink" : "text-muted"
              )}
            >
              <span className="font-medium">{item.label}</span>
              <span className="flex items-center gap-1.5 text-[11px] text-faint">
                {item.hint}
                {i === index && <ArrowRight size={12} />}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>,
    document.body
  );
}
