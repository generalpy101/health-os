"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Flame, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { TopBar } from "@/components/nav";
import { Button, Card, Empty, Field, Input, PageLoading, ProgressBar, Sheet, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { cx } from "@/lib/utils";

export default function HabitsPage() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: progress, isLoading } = useQuery({ queryKey: ["habits-progress"], queryFn: () => api.habitsProgress(7) });

  const toggle = useMutation({
    mutationFn: ({ id, done }: { id: string; done: boolean }) =>
      api.logHabit(id, { status: done ? "skipped" : "completed" }),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (e) => toast(e.message, "err"),
  });

  const del = useMutation({
    mutationFn: api.deleteHabit,
    onSuccess: () => queryClient.invalidateQueries(),
  });

  return (
    <>
      <TopBar title="Habits" right={<Button size="sm" onClick={() => setOpen(true)}><Plus size={15} /> New habit</Button>} />
      <main className="mx-auto max-w-5xl px-4 py-5 sm:px-6">
        {isLoading ? (
          <PageLoading />
        ) : !progress?.length ? (
          <Card>
            <Empty title="No habits yet" hint="Small daily actions compound. Start with one."
                   action={<Button onClick={() => setOpen(true)}><Plus size={15} /> Create habit</Button>} />
          </Card>
        ) : (
          <div className="space-y-3">
            {progress.map((h) => {
              const done = h.today_status === "completed";
              return (
                <Card key={h.habit_id} className="flex items-center gap-4 p-4">
                  <button
                    aria-label={`Toggle ${h.name}`}
                    onClick={() => toggle.mutate({ id: h.habit_id, done })}
                    className={cx(
                      "flex h-11 w-11 shrink-0 items-center justify-center rounded-full border-2 transition-all active:scale-95",
                      done ? "border-good bg-good text-white" : "border-line hover:border-accent"
                    )}
                  >
                    {done && <Check size={18} strokeWidth={3} />}
                  </button>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className={cx("truncate text-[15px] font-semibold", done && "text-faint line-through")}>
                        {h.name}
                      </span>
                      {h.streak > 0 && (
                        <span className="flex items-center gap-0.5 text-xs font-bold text-gold">
                          <Flame size={13} />{h.streak}
                        </span>
                      )}
                    </div>
                    <div className="mt-1.5 flex items-center gap-2">
                      <ProgressBar value={h.adherence} color="var(--olive)" className="max-w-40" />
                      <span className="text-xs text-faint">{h.completed}/{h.window_days} this week</span>
                    </div>
                  </div>
                  <button onClick={() => del.mutate(h.habit_id)} aria-label="Delete habit" className="p-2 text-faint hover:text-bad">
                    <Trash2 size={16} />
                  </button>
                </Card>
              );
            })}
          </div>
        )}
      </main>
      <NewHabitSheet open={open} onClose={() => setOpen(false)} />
    </>
  );
}

function NewHabitSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [unit, setUnit] = useState("");
  const queryClient = useQueryClient();
  const toast = useToast();

  const save = useMutation({
    mutationFn: () =>
      api.createHabit({
        name,
        ...(target ? { target: parseFloat(target) } : {}),
        ...(unit ? { unit } : {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["habits-progress"] });
      toast("Habit created");
      setName(""); setTarget(""); setUnit("");
      onClose();
    },
    onError: (e) => toast(e.message, "err"),
  });

  return (
    <Sheet open={open} onClose={onClose} title="New habit">
      <form
        className="space-y-4"
        onSubmit={(e) => { e.preventDefault(); if (name.trim()) save.mutate(); }}
      >
        <Field label="Name" hint='e.g. "Take creatine", "Read 20 pages", "Stretch"'>
          <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Meditate" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Target (optional)">
            <Input inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="20" />
          </Field>
          <Field label="Unit (optional)">
            <Input value={unit} onChange={(e) => setUnit(e.target.value)} placeholder="minutes" />
          </Field>
        </div>
        <Button type="submit" className="w-full" disabled={!name.trim() || save.isPending}>
          {save.isPending ? "Creating…" : "Create habit"}
        </Button>
      </form>
    </Sheet>
  );
}
