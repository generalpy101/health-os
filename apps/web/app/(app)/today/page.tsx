"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Droplet, Flame } from "lucide-react";
import { useState } from "react";
import { TopBar } from "@/components/nav";
import { Card, CardTitle, PageLoading, ProgressRing, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { cx, EVENT_COLORS, fmtDateFull, fmtDuration, fmtMl, fmtNumber, fmtTime, greeting, todayISO } from "@/lib/utils";

export default function TodayPage() {
  const day = todayISO();
  const queryClient = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const { data: summary, isLoading } = useQuery({
    // no date: the server computes the current logical day (respects "my day starts at")
    queryKey: ["daily", "now"],
    queryFn: () => api.dailySummary(),
  });
  const { data: habits } = useQuery({ queryKey: ["habits-progress"], queryFn: () => api.habitsProgress(1) });

  const habitMutation = useMutation({
    mutationFn: (habitId: string) => api.logHabit(habitId, { status: "completed" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["habits-progress"] });
      queryClient.invalidateQueries({ queryKey: ["daily"] });
    },
  });

  if (isLoading || !summary) return <PageLoading />;

  const t = summary.targets;
  const calTarget = t.calories;
  const proteinTarget = t.protein;
  const waterTarget = t.water;

  return (
    <>
      <TopBar title={fmtDateFull(summary.date)} />
      <main className="mx-auto max-w-5xl space-y-4 px-4 py-5 sm:px-6">
        <div>
          <h2 className="font-display text-[28px] font-semibold tracking-tight">
            {greeting()}{me?.name ? `, ${me.name.split(" ")[0]}` : ""}.
          </h2>
          <p className="text-sm text-muted">
            {summary.habits_total > 0
              ? `${summary.habits_completed}/${summary.habits_total} habits · ${summary.workout_count > 0 ? "workout done" : "no workout yet"}`
              : "Here's your day at a glance."}
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <Card className="flex items-center gap-4">
            <ProgressRing
              value={calTarget ? summary.nutrition.calories / calTarget : 0}
              label={fmtNumber(summary.nutrition.calories)}
              sub="kcal"
            />
            <div className="space-y-2.5">
              <Stat label="Protein" value={fmtNumber(summary.nutrition.protein)} unit={proteinTarget ? `/ ${proteinTarget}g` : "g"} tone="var(--olive)" />
              <Stat label="Carbs" value={fmtNumber(summary.nutrition.carbs)} unit="g" tone="var(--gold)" />
              <Stat label="Fat" value={fmtNumber(summary.nutrition.fat)} unit="g" tone="var(--berry)" />
            </div>
          </Card>

          <Card>
            <CardTitle right={<Droplet size={15} className="text-lake" />}>Water</CardTitle>
            <div className="flex items-end justify-between">
              <div className="font-display text-3xl font-semibold">{fmtMl(summary.water_ml)}</div>
              {waterTarget != null && <div className="text-sm text-muted">of {fmtMl(waterTarget)}</div>}
            </div>
            <div className="mt-3 flex gap-2">
              {[250, 500].map((ml) => (
                <WaterButton key={ml} ml={ml} />
              ))}
            </div>
          </Card>

          <Card>
            <CardTitle>Sleep & body</CardTitle>
            <div className="flex items-end justify-between">
              <Stat label="Last sleep" value={fmtDuration(summary.sleep_minutes)} tone="var(--berry)" />
              <Stat label="Weight" value={summary.weight ?? "—"} unit={summary.weight ? "kg" : undefined} tone="var(--gold)" />
            </div>
            {summary.steps > 0 && (
              <div className="mt-2 text-sm text-muted">{fmtNumber(summary.steps)} steps today</div>
            )}
          </Card>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardTitle>Today&rsquo;s schedule</CardTitle>
            {summary.schedule.length === 0 ? (
              <p className="py-4 text-sm text-faint">Nothing scheduled. Add events in the Planner.</p>
            ) : (
              <ul className="divide-y divide-line">
                {summary.schedule.map((e, i) => (
                  <li key={`${e.id}-${i}`} className="flex items-center gap-3 py-2.5">
                    <span className="h-8 w-1 rounded-full" style={{ background: EVENT_COLORS[e.type] || "var(--muted)" }} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{e.title}</div>
                      <div className="text-xs text-faint">
                        {fmtTime(e.start_at)}{e.end_at ? ` – ${fmtTime(e.end_at)}` : ""}
                      </div>
                    </div>
                    <span className="text-[11px] font-medium uppercase tracking-wide text-faint">{e.type}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardTitle>Habits</CardTitle>
            {!habits || habits.length === 0 ? (
              <p className="py-4 text-sm text-faint">No habits yet — create one and it appears here.</p>
            ) : (
              <ul className="divide-y divide-line">
                {habits.map((h) => {
                  const doneHabit = h.today_status === "completed";
                  return (
                    <li key={h.habit_id} className="flex items-center gap-3 py-2.5">
                      <button
                        aria-label={`Complete ${h.name}`}
                        onClick={() => !doneHabit && habitMutation.mutate(h.habit_id)}
                        className={cx(
                          "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                          doneHabit ? "border-good bg-good text-white" : "border-line hover:border-accent"
                        )}
                      >
                        {doneHabit && <Check size={14} strokeWidth={3} />}
                      </button>
                      <div className="flex-1">
                        <div className={cx("text-sm font-medium", doneHabit && "text-faint line-through")}>{h.name}</div>
                      </div>
                      {h.streak > 0 && (
                        <span className="flex items-center gap-1 text-xs font-semibold text-gold">
                          <Flame size={13} /> {h.streak}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>
      </main>
    </>
  );
}

function WaterButton({ ml }: { ml: number }) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  return (
    <button
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await api.logWater(ml);
          await queryClient.invalidateQueries();
        } finally {
          setBusy(false);
        }
      }}
      className="flex-1 rounded-xl border border-line bg-surface-2 py-2 text-sm font-semibold text-lake transition-colors hover:border-lake/40 disabled:opacity-50"
    >
      +{ml}ml
    </button>
  );
}
