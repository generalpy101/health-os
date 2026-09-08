"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Camera, Droplet, MessageCircle, Moon, Plus, Ruler, Scale, UtensilsCrossed } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Button, Input, Field, Select, Sheet, Spinner, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtNumber } from "@/lib/utils";

type Mode = null | "menu" | "food" | "water" | "weight" | "sleep" | "photo" | "measure";

export function QuickLog() {
  const [mode, setMode] = useState<Mode>(null);
  const router = useRouter();
  return (
    <>
      <button
        onClick={() => setMode("menu")}
        aria-label="Quick log"
        className="fixed bottom-20 right-4 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-accent text-accent-ink shadow-xl transition-transform hover:scale-105 active:scale-95 md:bottom-8 md:right-8"
      >
        <Plus size={26} strokeWidth={2.5} />
      </button>

      <Sheet open={mode === "menu"} onClose={() => setMode(null)} title="Quick log">
        <div className="grid grid-cols-2 gap-2.5">
          {[
            { icon: UtensilsCrossed, label: "Food", action: () => setMode("food"), tone: "var(--accent)" },
            { icon: Camera, label: "Meal photo", action: () => setMode("photo"), tone: "var(--accent)" },
            { icon: Droplet, label: "Water", action: () => setMode("water"), tone: "var(--lake)" },
            { icon: Scale, label: "Weight", action: () => setMode("weight"), tone: "var(--gold)" },
            { icon: Moon, label: "Sleep", action: () => setMode("sleep"), tone: "var(--berry)" },
            { icon: Ruler, label: "Measure", action: () => setMode("measure"), tone: "var(--gold)" },
          ].map((a) => (
            <button
              key={a.label}
              onClick={a.action}
              className="flex items-center gap-3 rounded-xl border border-line bg-surface p-4 text-left transition-colors hover:bg-surface-2"
            >
              <a.icon size={20} style={{ color: a.tone }} />
              <span className="text-sm font-semibold">{a.label}</span>
            </button>
          ))}
          <button
            onClick={() => router.push("/workouts")}
            className="flex items-center gap-3 rounded-xl border border-line bg-surface p-4 text-left transition-colors hover:bg-surface-2"
          >
            <Plus size={20} style={{ color: "var(--olive)" }} />
            <span className="text-sm font-semibold">Workout</span>
          </button>
          <button
            onClick={() => router.push("/assistant")}
            className="flex items-center gap-3 rounded-xl border border-line bg-surface p-4 text-left transition-colors hover:bg-surface-2"
          >
            <MessageCircle size={20} style={{ color: "var(--ink)" }} />
            <span className="text-sm font-semibold">Ask AI</span>
          </button>
        </div>
      </Sheet>

      <FoodQuickLog open={mode === "food"} onClose={() => setMode(null)} />
      <WaterQuickLog open={mode === "water"} onClose={() => setMode(null)} />
      <WeightQuickLog open={mode === "weight"} onClose={() => setMode(null)} />
      <SleepQuickLog open={mode === "sleep"} onClose={() => setMode(null)} />
      <PhotoQuickLog open={mode === "photo"} onClose={() => setMode(null)} />
      <MeasureQuickLog open={mode === "measure"} onClose={() => setMode(null)} />
    </>
  );
}

const MEASURE_TYPES: [string, string][] = [
  ["waist", "cm"], ["chest", "cm"], ["arms", "cm"], ["hips", "cm"],
  ["neck", "cm"], ["body_fat", "%"], ["legs", "cm"],
];

function MeasureQuickLog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [type, setType] = useState("waist");
  const [v, setV] = useState("");
  const done = useDone(onClose);
  const toast = useToast();
  const unit = MEASURE_TYPES.find(([t]) => t === type)?.[1] || "cm";
  return (
    <Sheet open={open} onClose={onClose} title="Log measurement">
      <form
        className="space-y-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const n = parseFloat(v);
          if (!(n > 0)) return;
          try {
            await api.recordMeasurement({ type, value: n, unit });
            done(`${type.replace("_", " ")}: ${n} ${unit}`);
          } catch (err) {
            toast(err instanceof Error ? err.message : "Failed", "err");
          }
        }}
      >
        <Field label="Type">
          <Select value={type} onChange={(e) => setType(e.target.value)}>
            {MEASURE_TYPES.map(([t, u]) => <option key={t} value={t}>{t.replace("_", " ")} ({u})</option>)}
          </Select>
        </Field>
        <Field label={`Value (${unit})`}>
          <Input autoFocus inputMode="decimal" value={v} onChange={(e) => setV(e.target.value)} placeholder="0" />
        </Field>
        <Button type="submit" className="w-full" disabled={!v}>Save</Button>
      </form>
    </Sheet>
  );
}

interface PhotoEstimate {
  name: string; quantity: number; unit: string; calories_est: number;
  protein_est: number; confidence: number; lower_kcal?: number; upper_kcal?: number;
}

function PhotoQuickLog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [photoId, setPhotoId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [items, setItems] = useState<PhotoEstimate[] | null>(null);
  const [message, setMessage] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const done = useDone(onClose);
  const toast = useToast();

  function reset() {
    setFile(null); setPhotoId(null); setItems(null); setMessage(""); setBusy(false);
  }

  async function uploadAndAnalyze(f: File) {
    setBusy(true);
    setFile(f);
    try {
      const photo = await api.uploadPhoto(f, "meal");
      setPhotoId(photo.id);
      const res = await api.analyzePhoto(photo.id);
      if (res.ok && res.items.length) {
        setItems(res.items);
      } else {
        setMessage(res.message || "Could not identify foods — log manually instead.");
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function logItems() {
    if (!items) return;
    setBusy(true);
    try {
      await api.logFood({
        meal_type: "other",
        note: "Photo estimate",
        items: items.map((i) => ({
          name: i.name, quantity: i.quantity, unit: i.unit,
          calories: i.calories_est, protein: i.protein_est,
          estimated: true, confidence: i.confidence,
          ...(i.lower_kcal != null ? { lower_kcal: i.lower_kcal } : {}),
          ...(i.upper_kcal != null ? { upper_kcal: i.upper_kcal } : {}),
        })),
      });
      reset();
      done("Meal logged from photo");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed", "err");
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} onClose={() => { reset(); onClose(); }} title="Meal photo">
      <input
        ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadAndAnalyze(f); e.target.value = ""; }}
      />
      {!file ? (
        <button
          onClick={() => fileRef.current?.click()}
          className="flex w-full flex-col items-center gap-2 rounded-2xl border border-dashed border-line py-10 text-muted transition-colors hover:border-accent hover:text-accent"
        >
          <Camera size={28} />
          <span className="text-sm font-medium">Take or choose a photo</span>
          <span className="text-xs text-faint">AI estimates items with calorie ranges — you review before logging</span>
        </button>
      ) : (
        <div className="space-y-4">
          {file && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={URL.createObjectURL(file)} alt="Meal" className="max-h-44 w-full rounded-xl object-cover" />
          )}
          {busy && !items && (
            <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted">
              <Spinner /> Analyzing…
            </div>
          )}
          {message && (
            <div className="rounded-xl border border-gold/40 bg-gold-soft px-3.5 py-3 text-sm text-gold">{message}</div>
          )}
          {items && (
            <>
              <div className="space-y-1.5">
                {items.map((i, idx) => (
                  <div key={idx} className="flex items-center justify-between rounded-xl border border-line px-3 py-2.5 text-sm">
                    <span className="font-medium">{i.name} <span className="text-xs text-faint">{i.quantity}{i.unit}</span></span>
                    <span className="text-right text-xs text-muted">
                      {i.lower_kcal != null && i.upper_kcal != null
                        ? <span className="font-semibold text-ink">{fmtNumber(i.lower_kcal)}–{fmtNumber(i.upper_kcal)} kcal</span>
                        : <span className="font-semibold text-ink">~{fmtNumber(i.calories_est)} kcal</span>}
                      <span className="block text-faint">confidence {Math.round((i.confidence || 0) * 100)}%</span>
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-[11px] leading-relaxed text-faint">
                These are estimates with uncertainty — totals land in your log marked as estimated.
              </p>
              <div className="flex gap-2">
                <Button variant="outline" className="flex-1" onClick={reset}>Retake</Button>
                <Button className="flex-1" onClick={logItems} disabled={busy}>
                  {busy ? "Logging…" : "Log these"}
                </Button>
              </div>
            </>
          )}
        </div>
      )}
    </Sheet>
  );
}

function useDone(close: () => void) {
  const queryClient = useQueryClient();
  const toast = useToast();
  return (message: string) => {
    toast(message);
    queryClient.invalidateQueries();
    close();
  };
}

function FoodQuickLog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const done = useDone(onClose);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    try {
      const res = await api.chat(text.trim());
      done(res.reply || "Logged");
      setText("");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed", "err");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title="Log food">
      <form onSubmit={submit} className="space-y-4">
        <Field label="What did you eat?" hint='e.g. "two eggs and 200g rice for lunch" — the assistant structures it'>
          <Input autoFocus value={text} onChange={(e) => setText(e.target.value)}
                 placeholder="two eggs, 200g rice and dal for lunch" />
        </Field>
        <div className="flex gap-2">
          <Button type="submit" className="flex-1" disabled={busy || !text.trim()}>
            {busy ? "Logging…" : "Log with AI"}
          </Button>
          <Button type="button" variant="outline" onClick={() => { onClose(); }}>
            Manual
          </Button>
        </div>
      </form>
    </Sheet>
  );
}

function WaterQuickLog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const done = useDone(onClose);
  const toast = useToast();
  async function log(ml: number) {
    try {
      await api.logWater(ml);
      done(`+${ml >= 1000 ? `${ml / 1000}L` : `${ml}ml`} water`);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed", "err");
    }
  }
  return (
    <Sheet open={open} onClose={onClose} title="Log water">
      <div className="grid grid-cols-2 gap-2.5">
        {[250, 330, 500, 750].map((ml) => (
          <button
            key={ml}
            onClick={() => log(ml)}
            className="rounded-xl border border-line bg-surface p-5 text-center transition-colors hover:bg-lake-soft"
          >
            <div className="font-display text-2xl font-semibold">{ml}</div>
            <div className="text-xs font-medium text-muted">ml</div>
          </button>
        ))}
      </div>
      <CustomAmount onLog={log} />
    </Sheet>
  );
}

function CustomAmount({ onLog }: { onLog: (ml: number) => void }) {
  const [v, setV] = useState("");
  return (
    <form
      className="mt-3 flex gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        const n = parseFloat(v);
        if (n > 0) onLog(n);
      }}
    >
      <Input inputMode="numeric" value={v} onChange={(e) => setV(e.target.value)} placeholder="Custom ml" />
      <Button type="submit" variant="outline">Log</Button>
    </form>
  );
}

function WeightQuickLog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [v, setV] = useState("");
  const done = useDone(onClose);
  const toast = useToast();
  return (
    <Sheet open={open} onClose={onClose} title="Log weight">
      <form
        className="space-y-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const n = parseFloat(v);
          if (!(n > 0)) return;
          try {
            await api.recordMeasurement({ type: "weight", value: n, unit: "kg" });
            done(`Weight: ${n} kg`);
          } catch (err) {
            toast(err instanceof Error ? err.message : "Failed", "err");
          }
        }}
      >
        <Field label="Weight (kg)">
          <Input autoFocus inputMode="decimal" value={v} onChange={(e) => setV(e.target.value)} placeholder="81.3" />
        </Field>
        <Button type="submit" className="w-full" disabled={!v}>Save</Button>
      </form>
    </Sheet>
  );
}

function SleepQuickLog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [hours, setHours] = useState("");
  const done = useDone(onClose);
  const toast = useToast();
  return (
    <Sheet open={open} onClose={onClose} title="Log sleep">
      <form
        className="space-y-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const h = parseFloat(hours);
          if (!(h > 0 && h < 20)) return;
          const end = new Date();
          end.setMinutes(0, 0, 0);
          if (end.getHours() > 12) end.setDate(end.getDate() - 1), end.setHours(9);
          const start = new Date(end.getTime() - h * 3600_000);
          try {
            await api.logSleep({ sleep_start: start.toISOString(), sleep_end: end.toISOString() });
            done(`Sleep: ${h}h`);
          } catch (err) {
            toast(err instanceof Error ? err.message : "Failed", "err");
          }
        }}
      >
        <Field label="Hours slept" hint="Ending this morning — exact times can be set in the Assistant">
          <Input autoFocus inputMode="decimal" value={hours} onChange={(e) => setHours(e.target.value)} placeholder="7.5" />
        </Field>
        <Button type="submit" className="w-full" disabled={!hours}>Save</Button>
      </form>
    </Sheet>
  );
}
