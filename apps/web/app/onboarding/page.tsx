"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Card, Field, Input, PageLoading, Textarea, useToast } from "@/components/ui";
import { ProviderPicker } from "@/components/ai-picker";
import { api } from "@/lib/api";
import type { OnboardingProposal } from "@/lib/types";
import { useQueryClient } from "@tanstack/react-query";

const EXAMPLE = "I want to lose fat, keep muscle, train four times a week, swim twice a week, eat mostly home-cooked food, and I work from 10 to 7.";

type EditableProposal = OnboardingProposal & {
  events: { type: string; title: string; bydays?: number[]; hour?: number; end_hour?: number }[];
};

/** LLMs and fallbacks can both drop keys — never trust the shape. */
function normalizeProposal(p: unknown): EditableProposal {
  const o = (p && typeof p === "object" ? p : {}) as Partial<OnboardingProposal>;
  return {
    profile: o.profile ?? {},
    weight_kg: o.weight_kg ?? null,
    goals: Array.isArray(o.goals) ? o.goals : [],
    targets: Array.isArray(o.targets) ? o.targets : [],
    suggested_targets: Array.isArray(o.suggested_targets) ? o.suggested_targets : [],
    events: Array.isArray(o.events) ? o.events : [],
    workout_plan: o.workout_plan ?? null,
    memories: Array.isArray(o.memories) ? o.memories : [],
  };
}

export default function OnboardingPage() {
  const router = useRouter();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [step, setStep] = useState<"write" | "review">("write");
  const [text, setText] = useState("");
  const [proposal, setProposal] = useState<EditableProposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [replace, setReplace] = useState(false);

  useEffect(() => {
    setReplace(new URLSearchParams(window.location.search).get("replace") === "1");
  }, []);

  async function parse() {
    setBusy(true);
    try {
      const res = await api.parseOnboarding(text);
      if (res.status === "done") {
        setProposal(normalizeProposal(res.result));
        setStep("review");
        return;
      }
      // real provider → background job; poll until done
      const jobId = res.job_id;
      const deadline = Date.now() + 180_000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 2000));
        const job = await api.aiJob(jobId);
        if (job.status === "done" && job.result) {
          setProposal(normalizeProposal(job.result));
          setStep("review");
          return;
        }
        if (job.status === "failed") {
          throw new Error(job.error || "Analysis failed");
        }
      }
      throw new Error("Still working after 3 minutes — try again or pick a faster provider");
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
      const targets = [...(proposal.targets || []), ...(proposal.suggested_targets || [])];
      await api.commitOnboarding({
        profile: proposal.profile,
        weight_kg: proposal.weight_kg ?? undefined,
        goals: proposal.goals,
        targets,
        events,
        habits: [],
        memories: proposal.memories,
        workout_plan: proposal.workout_plan ?? undefined,
        replace,
      });
      queryClient.clear();
      toast(replace ? "Plan replaced." : "You're all set.");
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
            {replace ? "Rethink the plan." : "Tell me about your life."}
          </h1>
          {replace && (
            <p className="mt-2 rounded-xl border border-gold/40 bg-gold-soft px-3.5 py-2.5 text-[13px] text-gold">
              Replace mode: your current active goals and targets are archived, and schedule events created
              during onboarding are removed — before the new setup is written. Your logs and history are untouched.
            </p>
          )}
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
          {busy && (
            <p className="mt-3 text-center text-xs leading-relaxed text-faint">
              Your AI provider is reading this now — with a CLI provider (Claude Code, Codex, opencode)
              this can take up to a minute. Keep this tab open; the work continues even if the connection blips.
            </p>
          )}
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
            {(proposal.weight_kg || proposal.profile?.height_cm || proposal.profile?.birth_year || proposal.profile?.sex) && (
              <Card>
                <div className="mb-2 text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">Your stats</div>
                <div className="flex flex-wrap gap-2 text-sm">
                  {proposal.profile?.birth_year != null && (
                    <span className="rounded-lg bg-surface-2 px-2.5 py-1">{new Date().getFullYear() - proposal.profile.birth_year} yrs</span>
                  )}
                  {proposal.profile?.height_cm != null && (
                    <span className="rounded-lg bg-surface-2 px-2.5 py-1">{proposal.profile.height_cm} cm</span>
                  )}
                  {proposal.weight_kg != null && (
                    <span className="rounded-lg bg-surface-2 px-2.5 py-1">{proposal.weight_kg} kg</span>
                  )}
                  {proposal.profile?.sex && (
                    <span className="rounded-lg bg-surface-2 px-2.5 py-1 capitalize">{proposal.profile.sex}</span>
                  )}
                </div>
                <p className="mt-2 text-[11px] text-faint">Weight is saved as your first measurement, so trends start today.</p>
              </Card>
            )}

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

            {(proposal.targets.length > 0 || (proposal.suggested_targets?.length ?? 0) > 0) && (
              <Card>
                <div className="mb-2 text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">Targets</div>
                <div className="space-y-2">
                  {proposal.targets.map((t, i) => (
                    <div key={i} className="flex items-center justify-between text-sm">
                      <span className="font-medium capitalize">{t.key.replaceAll("_", " ")}</span>
                      <span className="text-muted">{t.value} {t.unit} / {t.period.replace("ly", "")}</span>
                    </div>
                  ))}
                  {(proposal.suggested_targets || []).map((t, i) => (
                    <div key={`s${i}`} className="rounded-xl bg-surface-2/60 px-3 py-2">
                      <div className="flex items-center justify-between text-sm">
                        <span className="font-medium capitalize">
                          {t.key.replaceAll("_", " ")}
                          <span className="ml-2 rounded bg-olive-soft px-1.5 py-0.5 text-[10px] font-bold uppercase text-olive">calculated</span>
                        </span>
                        <span className="text-muted">{t.value} {t.unit} / {t.period.replace("ly", "")}</span>
                      </div>
                      {t.reason && <p className="mt-1 text-[11px] leading-snug text-faint">{t.reason}</p>}
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {(proposal.workout_plan?.days?.length ?? 0) > 0 && (
              <Card>
                <div className="mb-2 text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">Starter training plan</div>
                <div className="mb-1 text-sm font-semibold">{proposal.workout_plan!.name}</div>
                <div className="space-y-1">
                  {proposal.workout_plan!.days.map((d, i) => (
                    <div key={i} className="flex items-center justify-between text-sm">
                      <span className="font-medium">{d.name}</span>
                      <span className="text-xs text-faint">{d.exercises.length} exercises</span>
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-[11px] text-faint">Fully editable later under Workouts → Plans.</p>
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
