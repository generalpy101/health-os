"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Repeat, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { TopBar } from "@/components/nav";
import { Button, Card, Empty, Field, Input, PageLoading, Select, Sheet, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { EVENT_COLORS, addDays, cx, fmtTime, toISODate } from "@/lib/utils";

const DAY_LETTERS = ["M", "T", "W", "T", "F", "S", "S"];
const EVENT_TYPES = ["workout", "swimming", "meal", "sleep", "work", "reminder", "habit", "custom"];

export default function SchedulePage() {
  const [weekOffset, setWeekOffset] = useState(0);
  const [open, setOpen] = useState(false);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const toast = useToast();

  const { start, days } = useMemo(() => {
    const now = new Date();
    const monday = addDays(now, -((now.getDay() + 6) % 7) + weekOffset * 7);
    return {
      start: monday,
      days: Array.from({ length: 7 }, (_, i) => addDays(monday, i)),
    };
  }, [weekOffset]);

  const startISO = toISODate(start);
  const endISO = toISODate(addDays(start, 6));

  const { data: events, isLoading } = useQuery({
    queryKey: ["schedule", startISO],
    queryFn: () => api.schedule(startISO, endISO),
  });

  const del = useMutation({
    mutationFn: api.deleteEvent,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedule"] }),
    onError: (e) => toast(e.message, "err"),
  });

  const todayStr = toISODate(new Date());
  const weekLabel = `${start.toLocaleDateString(undefined, { month: "short", day: "numeric" })} – ${addDays(start, 6).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;

  return (
    <>
      <TopBar
        title="Planner"
        right={<Button size="sm" onClick={() => { setSelectedDay(todayStr); setOpen(true); }}><Plus size={15} /> Add event</Button>}
      />
      <main className="mx-auto max-w-5xl px-4 py-5 sm:px-6">
        <div className="mb-4 flex items-center justify-between">
          <Button variant="ghost" size="sm" onClick={() => setWeekOffset(weekOffset - 1)}>← Prev</Button>
          <div className="text-center">
            <div className="font-display text-lg font-semibold">{weekLabel}</div>
            {weekOffset !== 0 && (
              <button className="text-xs font-medium text-accent" onClick={() => setWeekOffset(0)}>Jump to this week</button>
            )}
          </div>
          <Button variant="ghost" size="sm" onClick={() => setWeekOffset(weekOffset + 1)}>Next →</Button>
        </div>

        {isLoading ? (
          <PageLoading />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-7 lg:gap-2">
            {days.map((day) => {
              const iso = toISODate(day);
              const dayEvents = (events || []).filter((e) => toISODate(new Date(e.start_at)) === iso);
              const isToday = iso === todayStr;
              return (
                <div
                  key={iso}
                  className={cx(
                    "min-h-32 rounded-2xl border p-2.5 transition-colors",
                    isToday ? "border-accent/50 bg-accent-soft/30" : "border-line bg-surface"
                  )}
                >
                  <div className="mb-2 flex items-center justify-between px-1">
                    <div>
                      <span className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                        {DAY_LETTERS[(day.getDay() + 6) % 7]}
                      </span>
                      <div className={cx("font-display text-lg font-semibold leading-none", isToday && "text-accent")}>
                        {day.getDate()}
                      </div>
                    </div>
                    <button
                      aria-label={`Add event on ${iso}`}
                      onClick={() => { setSelectedDay(iso); setOpen(true); }}
                      className="rounded-lg p-1 text-faint hover:bg-surface-2 hover:text-ink"
                    >
                      <Plus size={14} />
                    </button>
                  </div>
                  <div className="space-y-1">
                    {dayEvents.map((e, i) => (
                      <div
                        key={`${e.id}-${i}`}
                        className="group flex items-center gap-1.5 rounded-lg px-1.5 py-1 text-xs"
                        style={{ background: `color-mix(in srgb, ${EVENT_COLORS[e.type] || "var(--muted)"} 14%, transparent)` }}
                      >
                        <span className="h-4 w-0.5 shrink-0 rounded-full" style={{ background: EVENT_COLORS[e.type] || "var(--muted)" }} />
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-medium leading-tight">{e.title}</div>
                          <div className="text-[10px] text-faint">
                            {fmtTime(e.start_at)}{e.recurring && <Repeat size={9} className="ml-1 inline" />}
                          </div>
                        </div>
                        <button
                          onClick={() => del.mutate(e.id)}
                          aria-label="Delete event"
                          className="hidden shrink-0 text-faint hover:text-bad group-hover:block"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>
      <NewEventSheet open={open} onClose={() => setOpen(false)} defaultDate={selectedDay || todayStr} />
    </>
  );
}

function NewEventSheet({ open, onClose, defaultDate }: { open: boolean; onClose: () => void; defaultDate: string }) {
  const [title, setTitle] = useState("");
  const [type, setType] = useState("workout");
  const [time, setTime] = useState("18:00");
  const [endTime, setEndTime] = useState("19:00");
  const [day, setDay] = useState(defaultDate);
  const [recurring, setRecurring] = useState<number[]>([]);
  const queryClient = useQueryClient();
  const toast = useToast();

  // keep local state in sync when opening for another day
  useMemo(() => { if (open) setDay(defaultDate); }, [open, defaultDate]);

  const save = useMutation({
    mutationFn: () => {
      const start = new Date(`${day}T${time}:00`);
      const end = endTime ? new Date(`${day}T${endTime}:00`) : null;
      return api.createEvent({
        type, title,
        start_at: start.toISOString(),
        ...(end && end > start ? { end_at: end.toISOString() } : {}),
        ...(recurring.length ? { recurrence: { freq: "weekly", bydays: recurring.sort() } } : {}),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedule"] });
      toast("Event added");
      setTitle(""); setRecurring([]);
      onClose();
    },
    onError: (e) => toast(e.message, "err"),
  });

  return (
    <Sheet open={open} onClose={onClose} title="New event">
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (title.trim()) save.mutate(); }}>
        <Field label="Title">
          <Input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Gym session" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Type">
            <Select value={type} onChange={(e) => setType(e.target.value)}>
              {EVENT_TYPES.map((t) => <option key={t} value={t} className="capitalize">{t}</option>)}
            </Select>
          </Field>
          <Field label="Date">
            <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
          </Field>
          <Field label="Start">
            <Input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
          </Field>
          <Field label="End">
            <Input type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} />
          </Field>
        </div>
        <Field label="Repeat weekly on">
          <div className="flex gap-1.5">
            {DAY_LETTERS.map((d, i) => (
              <button
                type="button"
                key={i}
                onClick={() => setRecurring(recurring.includes(i) ? recurring.filter((x) => x !== i) : [...recurring, i])}
                className={cx(
                  "h-9 w-9 rounded-lg border text-xs font-semibold transition-colors",
                  recurring.includes(i) ? "border-accent bg-accent text-accent-ink" : "border-line text-muted hover:text-ink"
                )}
              >
                {d}
              </button>
            ))}
          </div>
        </Field>
        <Button type="submit" className="w-full" disabled={!title.trim() || save.isPending}>
          {save.isPending ? "Saving…" : recurring.length ? "Add recurring event" : "Add event"}
        </Button>
      </form>
    </Sheet>
  );
}
