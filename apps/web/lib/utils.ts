import clsx, { type ClassValue } from "clsx";

export const cx = (...args: ClassValue[]) => clsx(...args);

export function todayISO(): string {
  return toISODate(new Date());
}

export function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function addDays(d: Date, n: number): Date {
  const c = new Date(d);
  c.setDate(c.getDate() + n);
  return c;
}

export function fmtDate(iso: string): string {
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function fmtDateFull(iso: string): string {
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}

export function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function fmtDuration(min: number | null | undefined): string {
  if (min == null) return "—";
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

export function fmtNumber(n: number | null | undefined, digits = 0): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function fmtMl(ml: number): string {
  return ml >= 1000 ? `${(ml / 1000).toFixed(1)}L` : `${Math.round(ml)}ml`;
}

export function greeting(): string {
  const h = new Date().getHours();
  if (h < 5) return "Still up";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

export const MEAL_TYPES = [
  "breakfast", "brunch", "lunch", "snack", "dinner", "dessert", "pre_workout", "post_workout", "other",
] as const;

export const GOAL_TYPES = [
  "weight_loss", "weight_gain", "maintenance", "muscle_gain", "strength", "endurance",
  "fitness", "sleep", "hydration", "habit", "nutrition", "activity", "sport", "custom",
] as const;

export const EVENT_COLORS: Record<string, string> = {
  workout: "var(--accent)",
  swimming: "var(--lake)",
  meal: "var(--olive)",
  sleep: "var(--berry)",
  work: "var(--faint)",
  habit: "var(--gold)",
  reminder: "var(--gold)",
  custom: "var(--muted)",
};
