"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { FoodLog, ScheduleEvent } from "@/lib/types";
import { cx, EVENT_COLORS, fmtNumber, todayISO } from "@/lib/utils";

const HOUR_PX = 52;
const DAY_MIN = 24 * 60;

export interface Block {
  id: string;
  title: string;
  sub?: string;
  startMin: number;   // absolute minutes from day 00:00 (can exceed 24h for after-midnight)
  endMin: number;
  color: string;
  soft: string;
  kind: "log" | "plan" | "event";
  refId: string;
  payload?: unknown;
}

/** Absolute minutes of a datetime relative to `day` 00:00 (local). */
function absMin(iso: string, day: string): number {
  const d = new Date(iso);
  const base = new Date(day + "T00:00:00");
  return Math.round((d.getTime() - base.getTime()) / 60000);
}

function hourLabel(absMinutes: number): string {
  const h = Math.floor(absMinutes / 60) % 24;
  return h === 0 ? "12a" : h < 12 ? `${h}a` : h === 12 ? "12p" : `${h - 12}p`;
}

export function DayTimeline({ day, onPickSlot, onPickBlock }: {
  day: string; onPickSlot: (timeMin: number) => void; onPickBlock: (block: Block) => void;
}) {
  const { data: prefs } = useQuery({ queryKey: ["preferences"], queryFn: api.preferences });
  const boundary = (prefs?.data?.day_start_minutes as number | undefined) || 0;
  const [mode, setMode] = useState<"myday" | "calendar">("myday");
  const useBoundary = boundary > 0 && mode === "myday";

  // window [winStart, winStart+1440) in absolute minutes from `day` 00:00
  const winStart = useBoundary ? boundary : 0;

  // in boundary mode the window spans two calendar dates — fetch both
  const nextDay = useMemo(() => {
    const d = new Date(day + "T00:00:00");
    d.setDate(d.getDate() + 1);
    return d.toISOString().slice(0, 10);
  }, [day]);

  const { data: plans } = useQuery({
    queryKey: ["meal-plans", useBoundary ? `${day}_${nextDay}` : day],
    queryFn: () => useBoundary ? api.mealPlans(day, nextDay) : api.mealPlans(day, day),
  });
  // calendar=1: raw date listing — the boundary window is applied client-side below
  const { data: logsA } = useQuery({ queryKey: ["food-logs-raw", day], queryFn: () => api.foodLogs(day, true) });
  const { data: logsB } = useQuery({
    queryKey: ["food-logs-raw", nextDay],
    queryFn: () => api.foodLogs(nextDay, true),
    enabled: useBoundary,
  });
  const { data: events } = useQuery({
    queryKey: ["schedule", useBoundary ? `${day}_${nextDay}` : day],
    queryFn: () => useBoundary ? api.schedule(day, nextDay) : api.schedule(day, day),
  });

  const logs = useMemo(() => [...(logsA || []), ...(useBoundary ? logsB || [] : [])], [logsA, logsB, useBoundary]);

  const { blocks, unscheduled } = useMemo(() => {
    const blocks: Block[] = [];
    const unscheduled: Block[] = [];
    const seenEvents = new Set<string>();
    const winEnd = winStart + DAY_MIN;

    for (const e of events || []) {
      const startMin = absMin(e.start_at, day);
      let endMin = e.end_at ? absMin(e.end_at, day) : startMin + 60;
      endMin = Math.max(startMin + 30, endMin);
      if (endMin <= winStart || startMin >= winEnd) continue;
      const dedupeKey = `${e.type}|${e.title}|${startMin}|${endMin}`;
      if (seenEvents.has(dedupeKey)) continue;
      seenEvents.add(dedupeKey);
      const color = EVENT_COLORS[e.type] || "var(--muted)";
      blocks.push({
        id: `ev-${e.id}-${startMin}`, title: e.title, sub: e.type,
        startMin: Math.max(startMin, winStart), endMin: Math.min(endMin, winEnd),
        color, soft: `color-mix(in srgb, ${color} 16%, transparent)`, kind: "event",
        refId: e.id, payload: e,
      });
    }

    for (const p of plans || []) {
      const color = "var(--olive)";
      const sub = p.recipe_id ? "planned recipe" : "planned";
      const planAbsDay = (new Date(p.date + "T00:00:00").getTime() - new Date(day + "T00:00:00").getTime()) / 60000;
      if (p.time == null) {
        // untimed plans belong to their calendar date (or its logical day when boundary set)
        if (useBoundary) {
          const inWindowByDate = planAbsDay === 0 || planAbsDay === DAY_MIN;
          if (!inWindowByDate) continue;
        } else if (planAbsDay !== 0) continue;
        unscheduled.push({ id: `plan-${p.id}`, title: p.name, sub, startMin: 0, endMin: 0, color, soft: "var(--olive-soft)", kind: "plan", refId: p.id, payload: p });
        continue;
      }
      const [h, m] = p.time.split(":").map(Number);
      const startMin = planAbsDay + h * 60 + m;
      if (startMin < winStart || startMin >= winEnd) continue;
      blocks.push({ id: `plan-${p.id}`, title: p.name, sub, startMin, endMin: startMin + 45, color, soft: "var(--olive-soft)", kind: "plan", refId: p.id, payload: p });
    }

    for (const l of logs || []) {
      const startMin = absMin(l.eaten_at || l.created_at, day);
      if (startMin < winStart || startMin >= winEnd) continue;
      blocks.push({
        id: `log-${l.id}`, title: l.items.map((i) => i.name).slice(0, 3).join(", ") || l.meal_type,
        sub: `${fmtNumber(l.calories)} kcal · logged`, startMin, endMin: startMin + 30,
        color: "var(--accent)", soft: "var(--accent-soft)", kind: "log",
        refId: l.id, payload: l,
      });
    }
    blocks.sort((a, b) => a.startMin - b.startMin);
    return { blocks, unscheduled };
  }, [plans, logs, events, day, winStart, useBoundary]);

  const isToday = day === todayISO();
  const nowAbs = Math.round((Date.now() - new Date(day + "T00:00:00").getTime()) / 60000);

  const winLabel = useBoundary
    ? `${hourLabel(winStart)} today → ${hourLabel(winStart)} tomorrow`
    : null;

  return (
    <div>
      {boundary > 0 && (
        <div className="mb-2 flex items-center justify-between">
          <div className="inline-flex rounded-lg border border-line bg-surface-2 p-0.5 text-[11px] font-semibold">
            {(["myday", "calendar"] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)}
                      className={cx("rounded-md px-2.5 py-1", mode === m ? "bg-surface text-ink shadow-sm" : "text-muted")}>
                {m === "myday" ? "My day" : "Calendar day"}
              </button>
            ))}
          </div>
          {useBoundary && <span className="text-[11px] text-faint">{winLabel}</span>}
        </div>
      )}

      {unscheduled.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {unscheduled.map((b) => (
            <button key={b.id} onClick={() => onPickBlock(b)}
                    className="rounded-lg px-2.5 py-1 text-[11px] font-medium" style={{ background: b.soft, color: b.color }}>
              {b.title} <span className="opacity-60">· anytime</span>
            </button>
          ))}
        </div>
      )}

      <div className="relative overflow-y-auto rounded-2xl border border-line bg-surface" style={{ maxHeight: "62dvh" }}>
        <div style={{ height: 24 * HOUR_PX }} className="relative">
          {Array.from({ length: 24 }, (_, i) => {
            const abs = winStart + i * 60;
            return (
              <div key={i} className="absolute inset-x-0 flex items-start border-t border-line/60" style={{ top: i * HOUR_PX, height: HOUR_PX }}>
                <span className="-mt-2 w-12 shrink-0 bg-surface pr-2 text-right text-[10px] font-medium text-faint">
                  {hourLabel(abs)}
                </span>
                <button
                  className="h-full flex-1 cursor-cell hover:bg-surface-2/40"
                  aria-label={`Plan meal at ${hourLabel(abs)}`}
                  onClick={() => onPickSlot(abs % DAY_MIN)}
                />
              </div>
            );
          })}

          {/* midnight divider: where the calendar day changes inside "my day" */}
          {useBoundary && (
            <div className="pointer-events-none absolute inset-x-0 z-20 flex items-center" style={{ top: ((DAY_MIN - winStart) / 60) * HOUR_PX }}>
              <span className="ml-1 rounded bg-surface-2 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-faint">
                midnight
              </span>
              <div className="h-px flex-1 bg-line" style={{ borderTop: "1px dashed var(--faint)" }} />
            </div>
          )}

          {isToday && nowAbs >= winStart && nowAbs < winStart + DAY_MIN && (
            <div className="pointer-events-none absolute inset-x-0 z-20 flex items-center" style={{ top: ((nowAbs - winStart) / 60) * HOUR_PX }}>
              <span className="ml-1 h-2 w-2 rounded-full bg-accent" />
              <div className="h-0.5 flex-1 bg-accent/70" />
            </div>
          )}

          <div className="absolute inset-y-0" style={{ left: 56, right: 8 }}>
            <LayoutBlocks blocks={blocks} winStart={winStart} onPick={onPickBlock} />
          </div>
        </div>
      </div>
      <div className="mt-2 flex gap-3 px-1 text-[10px] text-faint">
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm" style={{ background: "var(--accent)" }} /> logged</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm" style={{ background: "var(--olive)" }} /> planned meal</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm" style={{ background: "var(--faint)" }} /> schedule</span>
        <span className="ml-auto">tap an hour to plan</span>
      </div>
    </div>
  );
}

/** Naive overlap layout: concurrent blocks share the width equally. */
function LayoutBlocks({ blocks, winStart, onPick }: { blocks: Block[]; winStart: number; onPick: (b: Block) => void }) {
  const clusters: Block[][] = [];
  for (const b of blocks) {
    const last = clusters[clusters.length - 1];
    if (last && b.startMin < Math.max(...last.map((x) => x.endMin))) {
      last.push(b);
    } else {
      clusters.push([b]);
    }
  }
  return (
    <>
      {clusters.flatMap((cluster) => {
        const cols: Block[][] = [];
        for (const b of cluster) {
          const col = cols.find((c) => c.every((x) => x.endMin <= b.startMin || b.endMin <= x.startMin));
          if (col) col.push(b);
          else cols.push([b]);
        }
        return cluster.map((b) => {
          const colIdx = cols.findIndex((c) => c.includes(b));
          const w = 100 / cols.length;
          return (
            <button
              key={b.id}
              onClick={(e) => { e.stopPropagation(); onPick(b); }}
              className={cx("absolute cursor-pointer overflow-hidden rounded-lg border-l-2 px-2 py-1 text-left transition-transform hover:scale-[1.02] hover:shadow-md", b.kind === "log" && "z-10")}
              style={{
                top: ((b.startMin - winStart) / 60) * HOUR_PX,
                height: Math.max(((b.endMin - b.startMin) / 60) * HOUR_PX, 22),
                left: `${colIdx * w}%`, width: `calc(${w}% - 3px)`,
                background: b.soft, borderColor: b.color,
              }}
              title={b.sub ? `${b.title} — ${b.sub}` : b.title}
            >
              <div className="truncate text-[11px] font-semibold leading-tight" style={{ color: b.color === "var(--faint)" ? "var(--muted)" : b.color }}>
                {b.title}
              </div>
              {b.sub && (b.endMin - b.startMin) >= 45 && (
                <div className="truncate text-[10px] capitalize text-faint">{b.sub}</div>
              )}
            </button>
          );
        });
      })}
    </>
  );
}
