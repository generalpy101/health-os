"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { TopBar } from "@/components/nav";
import { Button, Card, CardTitle, Empty, Field, Input, PageLoading, Segmented, Sheet, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { NewPR, Workout, WorkoutPlan, WorkoutSet } from "@/lib/types";
import { fmtDate, fmtNumber, todayISO } from "@/lib/utils";

interface DraftExercise {
  name: string;
  sets: { weight: string; reps: string }[];
}

export default function WorkoutsPage() {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"history" | "plans">("history");
  const [prefill, setPrefill] = useState<{ title: string; exercises: DraftExercise[] } | null>(null);
  const { data: workouts, isLoading } = useQuery({ queryKey: ["workouts"], queryFn: () => api.workouts(40) });
  const { data: range } = useQuery({ queryKey: ["range", 7], queryFn: () => api.rangeSummary(7) });
  // TRACK D: records strip + PR badges on freshly logged sessions
  const { data: prs } = useQuery({ queryKey: ["workout-prs"], queryFn: api.workoutPrs });
  const [prBadges, setPrBadges] = useState<Record<string, NewPR[]>>({});
  const queryClient = useQueryClient();
  const toast = useToast();

  const del = useMutation({
    mutationFn: api.deleteWorkout,
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (e) => toast(e.message, "err"),
  });

  const onLogged = (w: Workout) => {
    if (!w.new_prs?.length) return;
    setPrBadges((m) => ({ ...m, [w.id]: w.new_prs! }));
    for (const pr of w.new_prs) {
      toast(pr.kind === "weight"
        ? `New PR: ${pr.exercise} ${fmtNumber(pr.value, 1)}kg!`
        : `Volume PR: ${pr.exercise} ${fmtNumber(pr.value)}kg!`);
    }
  };

  const recentPrs = [...(prs || [])]
    .sort((a, b) => (b.date || "").localeCompare(a.date || ""))
    .slice(0, 6);

  return (
    <>
      <TopBar
        title="Workouts"
        right={
          <div className="flex items-center gap-2">
            <Segmented options={[{ value: "history", label: "History" }, { value: "plans", label: "Plans" }]}
                       value={tab} onChange={setTab} />
            <Button size="sm" onClick={() => { setPrefill(null); setOpen(true); }}><Plus size={15} /> Log workout</Button>
          </div>
        }
      />
      <main className="mx-auto max-w-5xl space-y-4 px-4 py-5 sm:px-6">
        {tab === "plans" ? (
          <PlansTab onStartDay={(title, exercises) => { setPrefill({ title, exercises }); setOpen(true); }} />
        ) : (
        <>
        {recentPrs.length > 0 && (
          <div>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Records</div>
            <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1">
              {recentPrs.map((p) => (
                <div key={p.exercise} className="min-w-[7.5rem] shrink-0 rounded-xl border border-line bg-surface p-3">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-xs font-semibold">{p.exercise}</span>
                    {p.is_recent && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-gold" />}
                  </div>
                  <div className="mt-0.5 font-display text-xl font-semibold">
                    {fmtNumber(p.best_weight, 1)}<span className="text-xs font-normal text-muted"> kg</span>
                  </div>
                  <div className="text-[10px] text-faint">
                    ×{fmtNumber(p.reps_at_best)}{p.date ? ` · ${fmtDate(p.date)}` : ""}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Card className="p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-accent">Sessions · 7d</div>
            <div className="mt-1 font-display text-3xl font-semibold">{range?.workout_count ?? 0}</div>
          </Card>
          <Card className="p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-olive">Volume · 7d</div>
            <div className="mt-1 font-display text-3xl font-semibold">{fmtNumber(range?.workout_volume)}<span className="text-sm text-muted"> kg</span></div>
          </Card>
        </div>

        {isLoading ? (
          <PageLoading />
        ) : !workouts?.length ? (
          <Card>
            <Empty title="No workouts yet" hint="Log your first session — sets, reps and weight; volume is computed for you."
                   action={<Button onClick={() => setOpen(true)}><Plus size={15} /> Log workout</Button>} />
          </Card>
        ) : (
          workouts.map((w) => (
            <Card key={w.id}>
              <CardTitle
                right={
                  <div className="flex items-center gap-3">
                    <span className="text-xs normal-case tracking-normal text-faint">
                      {fmtDate(w.date)}{w.duration_min ? ` · ${w.duration_min}min` : ""} · {fmtNumber(w.total_volume)} kg
                    </span>
                    <button onClick={() => del.mutate(w.id)} aria-label="Delete" className="text-faint hover:text-bad"><Trash2 size={15} /></button>
                  </div>
                }
              >
                {w.title}
                {prBadges[w.id]?.length ? (
                  <span className="ml-2 rounded-md bg-gold-soft px-1.5 py-0.5 align-middle text-[10px] font-bold uppercase tracking-wide text-gold">
                    PR{prBadges[w.id].length > 1 ? ` ×${prBadges[w.id].length}` : ""}
                  </span>
                ) : null}
              </CardTitle>
              <ul className="divide-y divide-line">
                {w.exercises.map((ex, i) => (
                  <li key={i} className="flex items-center justify-between py-2 text-sm">
                    <span className="font-medium">{ex.name}</span>
                    <span className="text-muted">
                      {ex.sets.length > 0
                        ? ex.sets.map((s) => `${s.weight ?? "—"}×${s.reps ?? "—"}`).join("  ·  ")
                        : "logged"}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          ))
        )}
        </>
        )}
      </main>
      <LogWorkoutSheet open={open} onClose={() => setOpen(false)} prefill={prefill} onLogged={onLogged} />
    </>
  );
}

// ---------- plans tab ----------

function PlansTab({ onStartDay }: { onStartDay: (title: string, exercises: DraftExercise[]) => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [createOpen, setCreateOpen] = useState(false);
  const { data: plans, isLoading } = useQuery({ queryKey: ["workout-plans"], queryFn: api.workoutPlans });
  const del = useMutation({
    mutationFn: api.deleteWorkoutPlan,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workout-plans"] }),
    onError: (e) => toast(e.message, "err"),
  });

  if (isLoading) return <PageLoading />;
  return (
    <div className="space-y-3">
      {!plans?.length ? (
        <Card>
          <Empty title="No training plans"
                 hint="A plan turns 'I should train' into a concrete set of days. Create one — or ask the assistant."
                 action={<Button onClick={() => setCreateOpen(true)}><Plus size={15} /> Create plan</Button>} />
        </Card>
      ) : (
        plans.map((p) => (
          <Card key={p.id}>
            <CardTitle
              right={<button onClick={() => del.mutate(p.id)} aria-label="Delete plan" className="text-faint hover:text-bad"><Trash2 size={15} /></button>}
            >
              {p.name}
            </CardTitle>
            <div className="space-y-2">
              {(p.days || []).map((d, i) => (
                <div key={i} className="flex items-center gap-3 rounded-xl bg-surface-2/50 px-3.5 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold">{d.name || `Day ${i + 1}`}</div>
                    <div className="truncate text-xs text-faint">
                      {(d.exercises || []).map((e) => `${e.name} ${e.sets ?? ""}${e.reps ? `×${e.reps}` : ""}`.trim()).join(" · ")}
                    </div>
                  </div>
                  <Button
                    size="sm" variant="outline"
                    onClick={() =>
                      onStartDay(
                        d.name || p.name,
                        (d.exercises || []).map((e) => ({
                          name: e.name,
                          sets: Array.from({ length: e.sets || 3 }, () => ({
                            weight: e.weight != null ? String(e.weight) : "",
                            reps: e.reps != null ? String(e.reps) : "",
                          })),
                        }))
                      )
                    }
                  >
                    <Play size={13} /> Start
                  </Button>
                </div>
              ))}
              {(!p.days || p.days.length === 0) && <p className="text-sm text-faint">No days defined.</p>}
            </div>
          </Card>
        ))
      )}
      <Button variant="outline" className="w-full" onClick={() => setCreateOpen(true)}>
        <Plus size={15} /> New plan
      </Button>
      <NewPlanSheet open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}

interface PlanDayExercise { name: string; sets: string; reps: string; weight: string }
interface PlanDay { name: string; exercises: PlanDayExercise[] }

function NewPlanSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [name, setName] = useState("");
  const [days, setDays] = useState<PlanDay[]>([{ name: "Day 1", exercises: [{ name: "", sets: "3", reps: "10", weight: "" }] }]);
  const queryClient = useQueryClient();
  const toast = useToast();

  const save = useMutation({
    mutationFn: () =>
      api.createWorkoutPlan({
        name,
        days: days.map((d) => ({
          name: d.name,
          exercises: d.exercises
            .filter((e) => e.name.trim())
            .map((e) => ({
              name: e.name.trim(),
              ...(e.sets ? { sets: parseInt(e.sets) } : {}),
              ...(e.reps ? { reps: parseInt(e.reps) } : {}),
              ...(e.weight ? { weight: parseFloat(e.weight) } : {}),
            })),
        })).filter((d) => d.exercises.length > 0),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workout-plans"] });
      toast("Plan created");
      setName("");
      setDays([{ name: "Day 1", exercises: [{ name: "", sets: "3", reps: "10", weight: "" }] }]);
      onClose();
    },
    onError: (e) => toast(e.message, "err"),
  });

  const setDay = (di: number, next: PlanDay) => {
    const copy = [...days];
    copy[di] = next;
    setDays(copy);
  };

  return (
    <Sheet open={open} onClose={onClose} title="New workout plan" wide>
      <div className="space-y-4">
        <Field label="Plan name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Push / Pull / Legs" autoFocus />
        </Field>
        {days.map((d, di) => (
          <div key={di} className="rounded-xl border border-line p-3">
            <div className="mb-2 flex items-center gap-2">
              <Input className="h-9 font-medium" value={d.name}
                     onChange={(e) => setDay(di, { ...d, name: e.target.value })} />
              <button onClick={() => setDays(days.filter((_, i) => i !== di))} className="p-1.5 text-faint hover:text-bad" aria-label="Remove day">
                <X size={15} />
              </button>
            </div>
            <div className="space-y-1.5">
              <div className="grid grid-cols-[1fr_52px_52px_64px_28px] gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-faint">
                <span>Exercise</span><span>Sets</span><span>Reps</span><span>Weight</span><span />
              </div>
              {d.exercises.map((ex, ei) => (
                <div key={ei} className="grid grid-cols-[1fr_52px_52px_64px_28px] items-center gap-1.5">
                  <Input className="h-9" placeholder="Bench press" value={ex.name}
                         onChange={(e) => { const exs = [...d.exercises]; exs[ei] = { ...ex, name: e.target.value }; setDay(di, { ...d, exercises: exs }); }} />
                  <Input className="h-9 px-1 text-center" inputMode="numeric" value={ex.sets}
                         onChange={(e) => { const exs = [...d.exercises]; exs[ei] = { ...ex, sets: e.target.value }; setDay(di, { ...d, exercises: exs }); }} />
                  <Input className="h-9 px-1 text-center" inputMode="numeric" value={ex.reps}
                         onChange={(e) => { const exs = [...d.exercises]; exs[ei] = { ...ex, reps: e.target.value }; setDay(di, { ...d, exercises: exs }); }} />
                  <Input className="h-9 px-1 text-center" inputMode="decimal" placeholder="kg" value={ex.weight}
                         onChange={(e) => { const exs = [...d.exercises]; exs[ei] = { ...ex, weight: e.target.value }; setDay(di, { ...d, exercises: exs }); }} />
                  <button onClick={() => setDay(di, { ...d, exercises: d.exercises.filter((_, i) => i !== ei) })}
                          className="p-1 text-faint hover:text-bad" aria-label="Remove exercise">
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
              <button className="text-xs font-semibold text-accent"
                      onClick={() => setDay(di, { ...d, exercises: [...d.exercises, { name: "", sets: "3", reps: "10", weight: "" }] })}>
                + Exercise
              </button>
            </div>
          </div>
        ))}
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setDays([...days, { name: `Day ${days.length + 1}`, exercises: [{ name: "", sets: "3", reps: "10", weight: "" }] }])}>
            + Day
          </Button>
          <Button className="flex-1" disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : "Create plan"}
          </Button>
        </div>
      </div>
    </Sheet>
  );
}

function LogWorkoutSheet({ open, onClose, prefill, onLogged }: { open: boolean; onClose: () => void; prefill?: { title: string; exercises: DraftExercise[] } | null; onLogged?: (w: Workout) => void }) {
  const [title, setTitle] = useState("");
  const [duration, setDuration] = useState("");
  const [exerciseQuery, setExerciseQuery] = useState("");
  const [draft, setDraft] = useState<DraftExercise[]>([]);
  const queryClient = useQueryClient();
  const toast = useToast();

  const { data: exercises } = useQuery({
    queryKey: ["exercises", exerciseQuery],
    queryFn: () => api.exercises(exerciseQuery),
    enabled: open,
  });

  // prefill from a plan day ("Start" button)
  useEffect(() => {
    if (open && prefill) {
      setTitle(prefill.title);
      setDraft(prefill.exercises.map((e) => ({ name: e.name, sets: e.sets.map((s) => ({ ...s })) })));
    }
    if (!open) {
      setExerciseQuery("");
    }
  }, [open, prefill]);

  const save = useMutation({
    mutationFn: () =>
      api.logWorkout({
        title: title || "Workout",
        date: todayISO(),
        duration_min: duration ? parseInt(duration) : undefined,
        exercises: draft.map((d) => ({
          name: d.name,
          sets: d.sets
            .filter((s) => s.weight || s.reps)
            .map((s) => ({
              ...(s.weight ? { weight: parseFloat(s.weight) } : {}),
              ...(s.reps ? { reps: parseFloat(s.reps) } : {}),
            }) as WorkoutSet),
        })),
      }),
    onSuccess: (w) => {
      queryClient.invalidateQueries();
      toast(`Logged — ${fmtNumber(w.total_volume)} kg volume`);
      onLogged?.(w);
      setDraft([]); setTitle(""); setDuration("");
      onClose();
    },
    onError: (e) => toast(e.message, "err"),
  });

  const addExercise = (name: string) => {
    if (!draft.find((d) => d.name === name)) {
      setDraft([...draft, { name, sets: [{ weight: "", reps: "" }] }]);
    }
    setExerciseQuery("");
  };

  return (
    <Sheet open={open} onClose={onClose} title="Log workout" wide>
      <div className="space-y-4">
        <div className="grid grid-cols-3 gap-2">
          <div className="col-span-2">
            <Field label="Title">
              <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Push day" />
            </Field>
          </div>
          <Field label="Duration (min)">
            <Input inputMode="numeric" value={duration} onChange={(e) => setDuration(e.target.value)} placeholder="60" />
          </Field>
        </div>

        <div className="relative">
          <Search size={16} className="absolute left-3.5 top-3.5 text-faint" />
          <Input className="pl-10" placeholder="Add exercise — bench, squat, row…" value={exerciseQuery}
                 onChange={(e) => setExerciseQuery(e.target.value)} />
        </div>
        {exerciseQuery && (
          <div className="max-h-40 space-y-0.5 overflow-y-auto rounded-xl border border-line">
            {exercises?.slice(0, 8).map((ex) => (
              <button key={ex.id} onClick={() => addExercise(ex.name)}
                      className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-surface-2">
                <span className="font-medium">{ex.name}</span>
                <span className="text-xs text-faint">{(ex.muscle_groups || []).join(", ")}</span>
              </button>
            ))}
            <button onClick={() => addExercise(exerciseQuery)}
                    className="w-full px-3 py-2 text-left text-sm font-medium text-accent hover:bg-accent-soft">
              + Add &ldquo;{exerciseQuery}&rdquo; as custom exercise
            </button>
          </div>
        )}

        {draft.map((d, di) => (
          <div key={d.name} className="rounded-xl border border-line p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold">{d.name}</span>
              <button onClick={() => setDraft(draft.filter((_, i) => i !== di))} className="text-faint hover:text-bad">
                <X size={15} />
              </button>
            </div>
            <div className="space-y-1.5">
              {d.sets.map((s, si) => (
                <div key={si} className="flex items-center gap-2">
                  <span className="w-8 text-xs font-medium text-faint">#{si + 1}</span>
                  <Input className="h-9 text-right" inputMode="decimal" placeholder="kg" value={s.weight}
                         onChange={(e) => {
                           const next = [...draft];
                           next[di].sets[si].weight = e.target.value;
                           setDraft([...next]);
                         }} />
                  <span className="text-xs text-faint">×</span>
                  <Input className="h-9 text-right" inputMode="numeric" placeholder="reps" value={s.reps}
                         onChange={(e) => {
                           const next = [...draft];
                           next[di].sets[si].reps = e.target.value;
                           setDraft([...next]);
                         }} />
                  <button onClick={() => {
                    const next = [...draft];
                    next[di].sets = next[di].sets.filter((_, i) => i !== si);
                    setDraft([...next]);
                  }} className="text-faint hover:text-bad"><Trash2 size={13} /></button>
                </div>
              ))}
              <button
                onClick={() => {
                  const next = [...draft];
                  const last = d.sets[d.sets.length - 1];
                  next[di].sets.push(last ? { ...last } : { weight: "", reps: "" });
                  setDraft([...next]);
                }}
                className="mt-1 text-xs font-semibold text-accent"
              >
                + Add set
              </button>
            </div>
          </div>
        ))}

        <Button className="w-full" onClick={() => save.mutate()} disabled={save.isPending || (draft.length === 0 && !title)}>
          {save.isPending ? "Saving…" : "Save workout"}
        </Button>
      </div>
    </Sheet>
  );
}
