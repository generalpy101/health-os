"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Card, Field, Input, PageLoading, Textarea, useToast } from "@/components/ui";
import { ProviderPicker } from "@/components/ai-picker";
import { api } from "@/lib/api";
import type { OnboardingProposal } from "@/lib/types";
import { useQueryClient } from "@tanstack/react-query";

const EXAMPLE = "I want to lose fat, keep muscle, train four times a week, swim twice a week, eat mostly home-cooked food, and I work from 10 to 7.";

type EditableProposal = OnboardingProposal & {
  events: { type: string; title: string; bydays?: number[]; hour?: number; end_hour?: number }[];
};

export default function OnboardingPage() {
  const router = useRouter();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [step, setStep] = useState<"write" | "review">("write");
  const [text, setText] = useState("");
  const [proposal, setProposal] = useState<EditableProposal | null>(null);
  const [busy, setBusy] = useState(false);

  async function parse() {
    setBusy(true);
    try {
      const p = await api.parseOnboarding(text);
      setProposal(p as EditableProposal);
      setStep("review");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not parse", "err");
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    if (!proposal) return;
    setBusy(true);
    try {
      const now = new Date();
      const events = (proposal.events || []).map((e) => {
        if (!e.bydays?.length) return null;
        const start = new Date(now);
        start.setHours(e.hour ?? 18, 0, 0, 0);
        const end = new Date(start);
        end.setHours(e.end_hour ?? (e.hour ?? 18) + 1);
        return {
          type: e.type, title: e.title,
          start_at: start.toISOString(), end_at: end.toISOString(),
          recurrence: { freq: "weekly", bydays: e.bydays },
        };
      }).filter(Boolean);
      const targets = [...(proposal.targets || [])];
      if (proposal.defaults_suggested && !targets.find((t) => t.key === "protein")) {
        targets.push({ key: "protein", value: proposal.defaults_suggested.protein_g, unit: "g", period: "daily" });
        targets.push({ key: "water", value: proposal.defaults_suggested.water_ml, unit: "ml", period: "daily" });
      }
      await api.commitOnboarding({
        profile: proposal.profile,
        goals: proposal.goals,
        targets,
        events,
        habits: [],
        memories: proposal.memories,
      });
      queryClient.clear();
      toast("You're all set.");
      router.replace("/today");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to save", "err");
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto min-h-dvh max-w-xl px-5 py-10 sm:py-16">
      <div className="flex items-center justify-between">
        <div className="font-display text-2xl font-bold">Health<span className="text-accent">OS</span></div>
        <ProviderPicker />
      </div>

      {step === "write" && (
        <div className="mt-10">
          <h1 className="font-display text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
            Tell me about your life.
          </h1>
          <p className="mt-3 text-[15px] leading-relaxed text-muted">
            One honest paragraph — your goals, schedule, how you eat, how you train.
            I&rsquo;ll turn it into a plan you can edit. Nothing is set in stone.
          </p>
          <div className="mt-6">
            <Textarea
              autoFocus
              rows={6}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={EXAMPLE}
              className="text-[16px] leading-relaxed"
            />
            <button
              className="mt-2 text-left text-[13px] text-faint underline-offset-2 hover:text-muted hover:underline"
              onClick={() => setText(EXAMPLE)}
            >
              Use an example
            </button>
          </div>
          <Button size="lg" className="mt-6 w-full" disabled={text.trim().length < 10 || busy} onClick={parse}>
            {busy ? "Understanding…" : "Build my plan"}
          </Button>
          <button
            className="mt-4 w-full text-center text-sm text-muted hover:text-ink"
            onClick={async () => {
              await api.commitOnboarding({ profile: { onboarding_completed: true } as never, goals: [], targets: [], events: [], habits: [], memories: [] });
              queryClient.clear();
              router.replace("/today");
            }}
          >
            Skip — I&rsquo;ll set things up manually
          </button>
        </div>
      )}

      {step === "review" && proposal && (
        <div className="mt-10">
          <h1 className="font-display text-3xl font-semibold tracking-tight">Here&rsquo;s what I heard.</h1>
          <p className="mt-2 text-sm text-muted">Review and tweak — this becomes your starting setup.</p>

          <div className="mt-6 space-y-4">
            <Card>
              <div className="mb-2 text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">Goals</div>
              <div className="space-y-2">
                {proposal.goals.map((g, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="rounded-md bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent">
                      {g.type.replaceAll("_", " ")}
                    </span>
                    <Input value={g.title} onChange={(e) => {
                      const next = { ...proposal };
                      next.goals[i].title = e.target.value;
                      setProposal({ ...next });
                    }} className="h-9" />
                  </div>
                ))}
              </div>
            </Card>

            {proposal.targets.length > 0 && (
              <Card>
                <div className="mb-2 text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">Targets</div>
                <div className="space-y-1.5">
                  {proposal.targets.map((t, i) => (
                    <div key={i} className="flex items-center justify-between text-sm">
                      <span className="font-medium capitalize">{t.key.replaceAll("_", " ")}</span>
                      <span className="text-muted">{t.value} {t.unit} / {t.period.replace("ly", "")}</span>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {proposal.events.length > 0 && (
              <Card>
                <div className="mb-2 text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">Weekly schedule</div>
                <div className="space-y-1.5">
                  {proposal.events.map((e, i) => (
                    <div key={i} className="flex items-center justify-between text-sm">
                      <span className="font-medium">{e.title}</span>
                      <span className="text-muted">
                        {(e.bydays || []).map((d) => "MTWTFSS"[d]).join(" · ")}
                        {e.hour != null && ` · ${e.hour}:00`}
                      </span>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {(proposal.memories.length > 0 || Object.keys(proposal.profile.dietary || {}).length > 0) && (
              <Card>
                <div className="mb-2 text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">Noted about you</div>
                <ul className="space-y-1 text-sm text-muted">
                  {proposal.profile.dietary?.diet ? <li>Diet: {String(proposal.profile.dietary.diet)}</li> : null}
                  {(proposal.profile.dietary?.dislikes as string[] | undefined)?.map((d) => <li key={d}>Dislikes: {d}</li>)}
                  {proposal.memories.map((m, i) => (
                    <li key={i}>{m.key.replaceAll("_", " ")}: {m.value}</li>
                  ))}
                </ul>
              </Card>
            )}
          </div>

          <div className="mt-6 flex gap-2">
            <Button variant="outline" size="lg" onClick={() => setStep("write")} disabled={busy}>Back</Button>
            <Button size="lg" className="flex-1" onClick={commit} disabled={busy}>
              {busy ? "Setting up…" : "Looks right — start"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
