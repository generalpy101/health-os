"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Trash2, X } from "lucide-react";
import { useState } from "react";
import { TopBar } from "@/components/nav";
import { Button, Card, CardTitle, Empty, Field, Input, PageLoading, Sheet, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { WorkoutSet } from "@/lib/types";
import { fmtDate, fmtDuration, fmtNumber, todayISO } from "@/lib/utils";

interface DraftExercise {
  name: string;
  sets: { weight: string; reps: string }[];
}

export default function WorkoutsPage() {
  const [open, setOpen] = useState(false);
  const { data: workouts, isLoading } = useQuery({ queryKey: ["workouts"], queryFn: () => api.workouts(40) });
  const { data: range } = useQuery({ queryKey: ["range", 7], queryFn: () => api.rangeSummary(7) });
  const queryClient = useQueryClient();
  const toast = useToast();

  const del = useMutation({
    mutationFn: api.deleteWorkout,
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (e) => toast(e.message, "err"),
  });

  return (
    <>
      <TopBar title="Workouts" right={<Button size="sm" onClick={() => setOpen(true)}><Plus size={15} /> Log workout</Button>} />
      <main className="mx-auto max-w-5xl space-y-4 px-4 py-5 sm:px-6">
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
      </main>
      <LogWorkoutSheet open={open} onClose={() => setOpen(false)} />
    </>
  );
}

function LogWorkoutSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
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
