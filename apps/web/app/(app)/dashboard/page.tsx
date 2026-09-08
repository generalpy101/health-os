"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { useState } from "react";
import { TopBar } from "@/components/nav";
import { Button, Card, CardTitle, PageLoading, ProgressBar, ProgressRing, Sheet, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import type { DailySummary, Goal } from "@/lib/types";
import { cx, fmtDuration, fmtMl, fmtNumber } from "@/lib/utils";

// Safe widget registry — dashboards are data, widgets come from here only.
const WIDGETS = ["nutrition_rings", "water", "weight", "sleep", "workouts_week", "habits", "goals", "schedule_today", "recommendations"] as const;
type WidgetType = (typeof WIDGETS)[number];

const WIDGET_META: Record<WidgetType, { title: string }> = {
  nutrition_rings: { title: "Nutrition" },
  water: { title: "Water" },
  weight: { title: "Weight" },
  sleep: { title: "Sleep" },
  workouts_week: { title: "Training (7d)" },
  habits: { title: "Habits" },
  goals: { title: "Active goals" },
  schedule_today: { title: "Today" },
  recommendations: { title: "Recommendations" },
};

const DEFAULT_LAYOUT: WidgetType[] = ["nutrition_rings", "water", "weight", "habits", "goals", "workouts_week", "recommendations"];

function useLayout() {
  const { data: prefs } = useQuery({ queryKey: ["preferences"], queryFn: api.preferences });
  const queryClient = useQueryClient();
  const layout = (prefs?.data?.dashboard_layout as WidgetType[] | undefined) || DEFAULT_LAYOUT;
  const save = useMutation({
    mutationFn: (next: WidgetType[]) => api.updatePreferences({ dashboard_layout: next }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["preferences"] }),
  });
  return { layout: layout.filter((w) => WIDGETS.includes(w)), save };
}

export default function DashboardPage() {
  const { layout, save } = useLayout();
  const [editing, setEditing] = useState(false);

  const { data: summary } = useQuery({ queryKey: ["daily"], queryFn: () => api.dailySummary() });
  const { data: range } = useQuery({ queryKey: ["range", 7], queryFn: () => api.rangeSummary(7) });
  const { data: goals } = useQuery({ queryKey: ["goals"], queryFn: () => api.goals("active") });
  const { data: habits } = useQuery({ queryKey: ["habits-progress"], queryFn: () => api.habitsProgress(7) });

  if (!summary) return <PageLoading />;

  const move = (i: number, dir: -1 | 1) => {
    const next = [...layout];
    const j = i + dir;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    save.mutate(next);
  };

  return (
    <>
      <TopBar
        title="Dashboard"
        right={
          <Button variant={editing ? "primary" : "outline"} size="sm" onClick={() => setEditing(!editing)}>
            {editing ? "Done" : "Customize"}
          </Button>
        }
      />
      <main className="mx-auto max-w-5xl px-4 py-5 sm:px-6">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {layout.map((w, i) => (
            <div key={w} className="relative">
              {editing && (
                <div className="absolute -top-2 right-2 z-10 flex gap-1">
                  <button onClick={() => move(i, -1)} className="rounded-lg border border-line bg-surface p-1 shadow"><ArrowUp size={13} /></button>
                  <button onClick={() => move(i, 1)} className="rounded-lg border border-line bg-surface p-1 shadow"><ArrowDown size={13} /></button>
                  <button onClick={() => save.mutate(layout.filter((x) => x !== w))} className="rounded-lg border border-line bg-surface p-1 text-bad shadow"><X size={13} /></button>
                </div>
              )}
              <WidgetRenderer type={w} summary={summary} range={range} goals={goals} habits={habits} />
            </div>
          ))}
          {editing && <AddWidget layout={layout} onAdd={(w) => save.mutate([...layout, w])} />}
        </div>
      </main>
    </>
  );
}

function AddWidget({ layout, onAdd }: { layout: WidgetType[]; onAdd: (w: WidgetType) => void }) {
  const [open, setOpen] = useState(false);
  const available = WIDGETS.filter((w) => !layout.includes(w));
  if (available.length === 0) return null;
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex min-h-28 w-full items-center justify-center gap-2 rounded-2xl border border-dashed border-line text-sm font-medium text-muted hover:border-accent hover:text-accent"
      >
        <Plus size={16} /> Add widget
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Add widget">
        <div className="space-y-1">
          {available.map((w) => (
            <button
              key={w}
              onClick={() => { onAdd(w); setOpen(false); }}
              className="w-full rounded-xl px-3 py-3 text-left text-sm font-medium hover:bg-surface-2"
            >
              {WIDGET_META[w].title}
            </button>
          ))}
        </div>
      </Sheet>
    </>
  );
}

function WidgetRenderer({
  type, summary, range, goals, habits,
}: {
  type: WidgetType;
  summary: DailySummary;
  range?: import("@/lib/types").RangeSummary;
  goals?: Goal[];
  habits?: import("@/lib/types").HabitProgress[];
}) {
  const t = summary.targets;
  switch (type) {
    case "nutrition_rings": {
      const calPct = t.calories ? summary.nutrition.calories / t.calories : 0;
      return (
        <Card>
          <CardTitle>Nutrition</CardTitle>
          <div className="flex items-center gap-4">
            <ProgressRing value={calPct} size={104} label={fmtNumber(summary.nutrition.calories)} sub={t.calories ? `/ ${t.calories}` : "kcal"} />
            <div className="flex-1 space-y-2.5">
              {[
                { l: "Protein", v: summary.nutrition.protein, t: t.protein, c: "var(--olive)" },
                { l: "Carbs", v: summary.nutrition.carbs, t: undefined, c: "var(--gold)" },
                { l: "Fat", v: summary.nutrition.fat, t: undefined, c: "var(--berry)" },
              ].map((m) => (
                <div key={m.l}>
                  <div className="mb-1 flex justify-between text-xs">
                    <span className="font-medium text-muted">{m.l}</span>
                    <span className="font-semibold">{fmtNumber(m.v)}{m.t ? ` / ${m.t}` : ""}g</span>
                  </div>
                  <ProgressBar value={m.t ? m.v / m.t : 0.4} color={m.c} />
                </div>
              ))}
            </div>
          </div>
        </Card>
      );
    }
    case "water":
      return (
        <Card>
          <CardTitle>Water</CardTitle>
          <div className="font-display text-3xl font-semibold">{fmtMl(summary.water_ml)}</div>
          <div className="mt-1 text-xs text-muted">{t.water ? `of ${fmtMl(t.water)} goal` : "today"}</div>
          <ProgressBar className="mt-3" value={t.water ? summary.water_ml / t.water : 0} color="var(--lake)" />
        </Card>
      );
    case "weight":
      return (
        <Card>
          <CardTitle>Weight</CardTitle>
          <div className="font-display text-3xl font-semibold">{summary.weight ?? "—"}<span className="text-sm text-muted"> kg</span></div>
          {range?.weight.weekly_rate != null && (
            <div className="mt-1 text-xs text-muted">
              {range.weight.weekly_rate > 0 ? "+" : ""}{range.weight.weekly_rate.toFixed(2)} kg / week
            </div>
          )}
        </Card>
      );
    case "sleep":
      return (
        <Card>
          <CardTitle>Sleep</CardTitle>
          <div className="font-display text-3xl font-semibold">{fmtDuration(summary.sleep_minutes)}</div>
          <div className="mt-1 text-xs text-muted">
            {range?.avg_sleep_minutes ? `7-day avg ${fmtDuration(range.avg_sleep_minutes)}` : "last night"}
          </div>
        </Card>
      );
    case "workouts_week":
      return (
        <Card>
          <CardTitle>Training — 7 days</CardTitle>
          <div className="font-display text-3xl font-semibold">{range?.workout_count ?? 0}<span className="text-sm text-muted"> sessions</span></div>
          <div className="mt-1 text-xs text-muted">{fmtNumber(range?.workout_volume)} kg total volume</div>
        </Card>
      );
    case "habits": {
      const avg = habits?.length ? habits.reduce((a, h) => a + h.adherence, 0) / habits.length : 0;
      return (
        <Card>
          <CardTitle>Habits — 7 days</CardTitle>
          <div className="font-display text-3xl font-semibold">{Math.round(avg * 100)}<span className="text-sm text-muted">%</span></div>
          <div className="mt-1 text-xs text-muted">
            {habits?.filter((h) => h.streak > 0).length ?? 0} active streaks
          </div>
        </Card>
      );
    }
    case "goals":
      return (
        <Card className="sm:col-span-2 lg:col-span-1">
          <CardTitle>Active goals</CardTitle>
          {!goals?.length ? (
            <p className="text-sm text-faint">No active goals.</p>
          ) : (
            <ul className="space-y-2.5">
              {goals.slice(0, 4).map((g) => <GoalRow key={g.id} goal={g} />)}
            </ul>
          )}
        </Card>
      );
    case "recommendations":
      return <RecommendationsWidget />;
    case "schedule_today":
      return (
        <Card>
          <CardTitle>Today</CardTitle>
          {summary.schedule.length === 0 ? (
            <p className="text-sm text-faint">Nothing planned.</p>
          ) : (
            <ul className="space-y-1.5">
              {summary.schedule.slice(0, 4).map((e, i) => (
                <li key={i} className="flex justify-between text-sm">
                  <span className="truncate font-medium">{e.title}</span>
                  <span className="ml-2 shrink-0 text-xs text-faint">{new Date(e.start_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      );
  }
}

function RecommendationsWidget() {
  const queryClient = useQueryClient();
  const { data: recs } = useQuery({ queryKey: ["recommendations"], queryFn: api.recommendations });
  const respond = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => api.updateRecommendation(id, status),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["recommendations"] }),
  });
  return (
    <Card className="sm:col-span-2 lg:col-span-3">
      <CardTitle
        right={<span className="text-[10px] normal-case tracking-normal text-faint">from your real data — refreshed every few hours</span>}
      >
        Recommendations
      </CardTitle>
      {!recs?.length ? (
        <p className="text-sm text-faint">Nothing to flag right now — keep logging and I&rsquo;ll spot patterns.</p>
      ) : (
        <div className="grid gap-2.5" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))" }}>
          {recs.slice(0, 3).map((r) => (
            <div key={r.id} className="rounded-xl border border-line bg-surface-2/40 p-3.5">
              <div className="flex items-start justify-between gap-2">
                <div className="text-sm font-semibold leading-snug">{r.title}</div>
                <span className={cx(
                  "shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase",
                  r.priority === "high" ? "bg-accent-soft text-accent" : "bg-gold-soft text-gold"
                )}>
                  {Math.round(r.confidence * 100)}%
                </span>
              </div>
              {r.reason && <p className="mt-1.5 text-xs leading-relaxed text-muted">{r.reason}</p>}
              {(r.actions as { text?: string; href?: string }[])?.map((a, i) => (
                <div key={i} className="mt-1.5 text-xs font-medium text-olive">
                  {a.href ? <a href={a.href} className="underline">{a.text}</a> : a.text}
                </div>
              ))}
              <div className="mt-2.5 flex gap-1.5">
                <button onClick={() => respond.mutate({ id: r.id, status: "accepted" })}
                        className="rounded-lg bg-olive-soft px-2.5 py-1 text-[11px] font-semibold text-olive hover:brightness-95">
                  Accept
                </button>
                <button onClick={() => respond.mutate({ id: r.id, status: "rejected" })}
                        className="rounded-lg bg-surface-2 px-2.5 py-1 text-[11px] font-semibold text-muted hover:text-ink">
                  Dismiss
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function GoalRow({ goal }: { goal: Goal }) {
  const { data } = useQuery({ queryKey: ["goal-progress", goal.id], queryFn: () => api.goalProgress(goal.id) });
  return (
    <li>
      <div className="mb-1 flex justify-between text-sm">
        <span className="truncate font-medium">{goal.title}</span>
        {goal.target_value != null && (
          <span className="text-xs text-muted">
            {data?.current ?? goal.start_value ?? "—"} → {goal.target_value} {goal.unit}
          </span>
        )}
      </div>
      {data?.progress != null && <ProgressBar value={data.progress} />}
    </li>
  );
}
