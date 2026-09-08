"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, Cpu } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { AIProviderInfo } from "@/lib/types";
import { cx } from "@/lib/utils";

export function useAiProviders() {
  const { data } = useQuery({ queryKey: ["ai-providers"], queryFn: api.aiProviders, staleTime: 60_000 });
  return data?.providers || [];
}

export function useAiSettings() {
  const { data } = useQuery({ queryKey: ["ai-settings"], queryFn: api.aiSettings });
  return data?.ai || {};
}

export function providerLabel(providers: AIProviderInfo[], id?: string): string {
  return providers.find((p) => p.id === (id || "mock"))?.label || "Built-in offline mode";
}

/** Compact provider switcher — assistant header, sidebar, onboarding. */
export function ProviderPicker({ compact = false }: { compact?: boolean }) {
  const providers = useAiProviders();
  const settings = useAiSettings();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const save = useMutation({
    mutationFn: (provider: string) => {
      const preset = providers.find((p) => p.id === provider);
      return api.updateAiSettings({
        provider,
        model: preset?.default_model || undefined,
        base_url: preset?.default_base_url || undefined,
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-settings"] }),
  });

  const current = providers.find((p) => p.id === (settings.provider || "mock"));
  const currentDetected = current?.detected ?? true;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className={cx(
          "flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 text-[12px] font-medium text-muted transition-colors hover:text-ink",
          !currentDetected && "border-gold/50 text-gold"
        )}
        aria-label="AI provider"
        title={current?.hint}
      >
        <Cpu size={13} />
        <span className="max-w-28 truncate">{current?.label || "Offline"}</span>
        <ChevronDown size={12} className={cx("transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="absolute right-0 top-9 z-50 w-72 rounded-2xl border border-line bg-surface p-1.5 shadow-xl">
          <div className="px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
            AI provider
          </div>
          {providers.map((p) => {
            const active = (settings.provider || "mock") === p.id;
            return (
              <button
                key={p.id}
                onClick={() => { save.mutate(p.id); setOpen(false); }}
                className={cx(
                  "flex w-full items-start gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors hover:bg-surface-2",
                  active && "bg-surface-2"
                )}
              >
                <span className={cx(
                  "mt-1.5 h-2 w-2 shrink-0 rounded-full",
                  p.detected ? "bg-good" : "bg-faint"
                )} />
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-semibold">{p.label}</span>
                  <span className="block truncate text-[11px] text-faint">
                    {p.detected ? p.hint : `Not detected — ${p.hint}`}
                  </span>
                </span>
                {active && <Check size={14} className="mt-1 shrink-0 text-accent" />}
              </button>
            );
          })}
          <Link
            href="/settings#ai"
            onClick={() => setOpen(false)}
            className="mt-1 block rounded-xl border-t border-line px-2.5 py-2 text-[12px] font-medium text-accent hover:bg-accent-soft"
          >
            Configure models & keys →
          </Link>
        </div>
      )}
    </div>
  );
}
