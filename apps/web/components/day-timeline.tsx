"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "@/lib/api";
import { cx, EVENT_COLORS, fmtNumber, todayISO } from "@/lib/utils";

const HOUR_PX = 52;

interface Block {
  id: string;
  title: string;
  sub?: string;
  startMin: number;
  endMin: number;
  color: string;
  soft: string;
  kind: "log" | "plan" | "event";
  refId: string; // underlying row id
  payload?: unknown;
}

export type { Block };

export function DayTimeline({ day, onPickSlot, onPickBlock }: {
  day: string; onPickSlot: (timeMin: number) => void; onPickBlock: (block: Block) => void;
}) {
  const { data: plans } = useQuery({ queryKey: ["meal-plans", day], queryFn: () => api.mealPlans(day, day) });
  const { data: logs } = useQuery({ queryKey: ["food-logs", day], queryFn: () => api.foodLogs(day) });
  const { data: events } = useQuery({ queryKey: ["schedule", day], queryFn: () => api.schedule(day, day) });

  const { blocks, unscheduled } = useMemo(() => {
    const blocks: Block[] = [];
    const unscheduled: Block[] = [];
    const seenEvents = new Set<string>();

    for (const e of events || []) {
      const start = new Date(e.start_at);
      const end = e.end_at ? new Date(e.end_at) : new Date(start.getTime() + 60 * 60_000);
      const startMin = start.getHours() * 60 + start.getMinutes();
      const endMin = Math.max(startMin + 30, end.getHours() * 60 + end.getMinutes() +
        (end.getDate() !== start.getDate() ? 24 * 60 : 0));
      // dedupe identical recurring rows (leftover duplicates from repeated onboarding runs)
      const dedupeKey = `${e.type}|${e.title}|${startMin}|${endMin}`;
      if (seenEvents.has(dedupeKey)) continue;
      seenEvents.add(dedupeKey);
      const color = EVENT_COLORS[e.type] || "var(--muted)";
      blocks.push({
        id: `ev-${e.id}-${startMin}`, title: e.title,
        sub: e.type, startMin, endMin: Math.min(endMin, 24 * 60),
        color, soft: `color-mix(in srgb, ${color} 16%, transparent)`, kind: "event",
        refId: e.id, payload: e,
      });
    }
    for (const p of plans || []) {
      const color = "var(--olive)";
      const sub = p.recipe_id ? "planned recipe" : "planned";
      if (p.time == null) {
        unscheduled.push({ id: `plan-${p.id}`, title: p.name, sub, startMin: 0, endMin: 0, color, soft: "var(--olive-soft)", kind: "plan", refId: p.id, payload: p });
      } else {
        const [h, m] = p.time.split(":").map(Number);
        const startMin = h * 60 + m;
        blocks.push({ id: `plan-${p.id}`, title: p.name, sub, startMin, endMin: startMin + 45, color, soft: "var(--olive-soft)", kind: "plan", refId: p.id, payload: p });
      }
    }
    for (const l of logs || []) {
      const at = new Date(l.eaten_at || l.created_at);
      const startMin = at.getHours() * 60 + at.getMinutes();
      blocks.push({
        id: `log-${l.id}`, title: l.items.map((i) => i.name).slice(0, 3).join(", ") || l.meal_type,
        sub: `${fmtNumber(l.calories)} kcal · logged`, startMin, endMin: startMin + 30,
        color: "var(--accent)", soft: "var(--accent-soft)", kind: "log",
        refId: l.id, payload: l,
      });
    }
    blocks.sort((a, b) => a.startMin - b.startMin);
    return { blocks, unscheduled };
  }, [plans, logs, events]);

  const isToday = day === todayISO();
  const nowMin = new Date().getHours() * 60 + new Date().getMinutes();

  return (
    <div>
      {unscheduled.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {unscheduled.map((b) => (
            <span key={b.id} className="rounded-lg px-2.5 py-1 text-[11px] font-medium" style={{ background: b.soft, color: b.color }}>
              {b.title} <span className="opacity-60">· anytime</span>
            </span>
          ))}
        </div>
      )}
      <div className="relative overflow-y-auto rounded-2xl border border-line bg-surface" style={{ maxHeight: "62dvh" }}>
        <div style={{ height: 24 * HOUR_PX }} className="relative">
          {Array.from({ length: 24 }, (_, h) => (
            <div key={h} className="absolute inset-x-0 flex items-start border-t border-line/60" style={{ top: h * HOUR_PX, height: HOUR_PX }}>
              <span className="-mt-2 w-12 shrink-0 bg-surface pr-2 text-right text-[10px] font-medium text-faint">
                {h === 0 ? "12a" : h < 12 ? `${h}a` : h === 12 ? "12p" : `${h - 12}p`}
              </span>
              {/* tap empty space to plan a meal at that hour */}
              <button
                className="h-full flex-1 cursor-cell hover:bg-surface-2/40"
                aria-label={`Plan meal at ${h}:00`}
                onClick={() => onPickSlot(h * 60)}
              />
            </div>
          ))}

          {isToday && (
            <div className="pointer-events-none absolute inset-x-0 z-20 flex items-center" style={{ top: (nowMin / 60) * HOUR_PX }}>
              <span className="ml-1 h-2 w-2 rounded-full bg-accent" />
              <div className="h-0.5 flex-1 bg-accent/70" />
            </div>
          )}

          {/* blocks — side-by-side columns when overlapping */}
          <div className="absolute inset-y-0" style={{ left: 56, right: 8 }}>
            <LayoutBlocks blocks={blocks} onPick={onPickBlock} />
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
function LayoutBlocks({ blocks, onPick }: { blocks: Block[]; onPick: (b: Block) => void }) {
  // group into overlap clusters
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
                top: (b.startMin / 60) * HOUR_PX,
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
