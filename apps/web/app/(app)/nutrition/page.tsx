"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Globe, Plus, ScanBarcode, Search, Trash2, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { TopBar } from "@/components/nav";
import { BarcodeScanner } from "@/components/barcode-scanner";
import {
  Button, Card, CardTitle, Empty, Field, Input, PageLoading, Select, Sheet, Spinner, useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import type { Food, FoodLog } from "@/lib/types";
import { MEAL_TYPES, cx, fmtNumber, todayISO } from "@/lib/utils";
import { ImportSheet } from "./import-sheet";

export default function NutritionPage() {
  const [day, setDay] = useState(todayISO());
  const [logOpen, setLogOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [editItem, setEditItem] = useState<{ log: FoodLog; index: number } | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["nutrition", day],
    queryFn: () => api.dailyNutrition(day),
  });
  const queryClient = useQueryClient();
  const toast = useToast();

  const del = useMutation({
    mutationFn: api.deleteFoodLog,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["nutrition"] }),
    onError: (e) => toast(e.message, "err"),
  });

  const t = data?.targets || {};

  return (
    <>
      <TopBar
        title="Nutrition"
        right={
          <div className="flex items-center gap-1.5 sm:gap-2">
            <Input type="date" value={day} onChange={(e) => setDay(e.target.value)}
                   className="h-9 w-[7.6rem] px-2 text-xs sm:w-auto sm:px-3.5 sm:text-sm" />
            <Button size="sm" onClick={() => setLogOpen(true)} aria-label="Log food">
              <Plus size={15} /><span className="hidden sm:inline">Log food</span>
            </Button>
          </div>
        }
      />
      <main className="mx-auto max-w-5xl space-y-4 px-4 py-5 sm:px-6">
        {isLoading || !data ? (
          <PageLoading />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                { l: "Calories", v: data.calories, target: t.calories, unit: "kcal", c: "var(--accent)" },
                { l: "Protein", v: data.protein, target: t.protein, unit: "g", c: "var(--olive)" },
                { l: "Carbs", v: data.carbs, unit: "g", c: "var(--gold)" },
                { l: "Fat", v: data.fat, unit: "g", c: "var(--berry)" },
              ].map((m) => (
                <Card key={m.l} className="p-4">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.08em]" style={{ color: m.c }}>{m.l}</div>
                  <div className="mt-1 font-display text-[26px] font-semibold leading-none">
                    {fmtNumber(m.v)}
                    <span className="ml-1 text-xs font-normal text-muted">{m.unit}</span>
                  </div>
                  {m.target != null && (
                    <div className="mt-1 text-[11px] text-faint">of {fmtNumber(m.target)} {m.unit}</div>
                  )}
                </Card>
              ))}
            </div>

            {data.logs.length === 0 ? (
              <Card>
                <Empty
                  title="Nothing logged"
                  hint="Search the food database and log a meal in a few taps."
                  action={<Button onClick={() => setLogOpen(true)}><Plus size={15} /> Log food</Button>}
                />
              </Card>
            ) : (
              data.logs.map((log) => (
                <Card key={log.id}>
                  <CardTitle
                    right={
                      <div className="flex items-center gap-3">
                        <span className="font-display text-lg font-semibold normal-case tracking-normal text-ink">
                          {fmtNumber(log.calories)} kcal
                        </span>
                        <button onClick={() => del.mutate(log.id)} aria-label="Delete" className="text-faint hover:text-bad">
                          <Trash2 size={15} />
                        </button>
                      </div>
                    }
                  >
                    {log.meal_type.replace("_", " ")}
                  </CardTitle>
                  <ul className="divide-y divide-line">
                    {log.items.map((item, i) => (
                      <li key={i} className="group flex items-center justify-between py-2 text-sm">
                        <button className="min-w-0 flex-1 text-left" onClick={() => setEditItem({ log, index: i })}>
                          <span className="group-hover:text-accent">{item.name}</span>
                          <span className="ml-2 text-xs text-faint">
                            {fmtNumber(item.quantity)}{item.unit}
                            {item.unmatched && <span className="ml-1 text-gold">· not in database</span>}
                            {item.estimated && !item.unmatched && <span className="ml-1 text-gold">· est</span>}
                          </span>
                        </button>
                        <span className="text-muted">{fmtNumber(item.calories)} kcal · {fmtNumber(item.protein)}g P</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              ))
            )}

            <Card>
              <CardTitle
                right={
                  <Button size="sm" variant="outline" onClick={() => setImportOpen(true)}>
                    <Upload size={14} /> Import
                  </Button>
                }
              >
                Import data
              </CardTitle>
              <p className="text-sm text-muted">
                Bring in measurements, food logs or workouts from a CSV or JSON export.
              </p>
            </Card>
          </>
        )}
      </main>
      <LogFoodSheet open={logOpen} onClose={() => setLogOpen(false)} day={day} />
      <EditItemSheet target={editItem} onClose={() => setEditItem(null)} />
      <ImportSheet open={importOpen} onClose={() => setImportOpen(false)} />
    </>
  );
}

/** Correct one logged item: your label/knowledge beats the database (spec §61). */
function EditItemSheet({ target, onClose }: { target: { log: FoodLog; index: number } | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const item = target?.log.items[target.index];
  const [quantity, setQuantity] = useState("");
  const [calories, setCalories] = useState("");
  const [protein, setProtein] = useState("");

  useEffect(() => {
    if (item) {
      setQuantity(String(item.quantity));
      setCalories(String(item.calories));
      setProtein(String(item.protein));
    }
  }, [target]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: () => {
      if (!target) return Promise.reject(new Error("nothing to save"));
      const items = target.log.items.map((it, i) => ({
        name: it.name,
        quantity: i === target.index ? parseFloat(quantity) || it.quantity : it.quantity,
        unit: it.unit,
        food_id: it.food_id || undefined,
        ...(i === target.index
          ? { calories: parseFloat(calories) || 0, protein: parseFloat(protein) || 0, estimated: false }
          : {}),
      }));
      return api.updateFoodLog(target.log.id, { items });
    },
    onSuccess: () => {
      queryClient.invalidateQueries();
      toast("Corrected — totals recalculated");
      onClose();
    },
    onError: (e) => toast(e.message, "err"),
  });

  if (!target || !item) return null;
  return (
    <Sheet open={!!target} onClose={onClose} title={`Fix: ${item.name}`}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <p className="text-xs leading-relaxed text-faint">
          Have the real numbers (package label, recipe you made)? Enter them — they win over the database.
          This is a correction, stored as your value.
        </p>
        <div className="grid grid-cols-3 gap-2">
          <Field label={`Qty (${item.unit})`}>
            <Input inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </Field>
          <Field label="Calories">
            <Input inputMode="decimal" value={calories} onChange={(e) => setCalories(e.target.value)} />
          </Field>
          <Field label="Protein (g)">
            <Input inputMode="decimal" value={protein} onChange={(e) => setProtein(e.target.value)} />
          </Field>
        </div>
        <Button type="submit" className="w-full" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save correction"}
        </Button>
      </form>
    </Sheet>
  );
}

function LogFoodSheet({ open, onClose, day }: { open: boolean; onClose: () => void; day: string }) {
  const [meal, setMeal] = useState<string>("lunch");
  const [query, setQuery] = useState("");
  const [online, setOnline] = useState(false);
  const [barcodeOpen, setBarcodeOpen] = useState(false);
  const [barcode, setBarcode] = useState("");
  const [scanning, setScanning] = useState(false);
  const [picked, setPicked] = useState<{ food: Food; quantity: number }[]>([]);
  const [customName, setCustomName] = useState("");
  // TRACK D: after a successful log, offer to keep the combo as a saved meal
  const [justLogged, setJustLogged] = useState<{ id: string; calories: number } | null>(null);
  const [mealName, setMealName] = useState("");
  const queryClient = useQueryClient();
  const toast = useToast();

  useEffect(() => {
    if (open) { setJustLogged(null); setMealName(""); }
  }, [open]);

  const { data: results, isFetching } = useQuery({
    queryKey: ["foods", query, online],
    queryFn: () => (online ? api.searchFoodsProvider(query, 12, "auto") : api.searchFoods(query, 12)),
    enabled: open,
  });

  const lookupBarcode = useMutation({
    mutationFn: (code: string) => api.foodByBarcode(code.trim()),
    onSuccess: (food) => {
      setPicked((prev) =>
        prev.find((p) => p.food.id === food.id) ? prev : [...prev, { food, quantity: food.serving_size }]);
      toast(`${food.name} added`);
      setBarcode("");
      setScanning(false);
      setBarcodeOpen(false);
    },
    onError: (e) => toast(e.message === "not found" ? "Barcode not found — try online search" : e.message, "err"),
  });

  const save = useMutation({
    mutationFn: () =>
      api.logFood({
        date: day,
        meal_type: meal,
        items: picked.map((p) => ({
          food_id: p.food.id, name: p.food.name, quantity: p.quantity, unit: p.food.serving_unit,
        })),
      }),
    onSuccess: (log) => {
      queryClient.invalidateQueries();
      toast("Meal logged");
      setPicked([]);
      setQuery("");
      setJustLogged({ id: log.id, calories: log.calories });
    },
    onError: (e) => toast(e.message, "err"),
  });

  const saveMeal = useMutation({
    mutationFn: () => api.createSavedMeal({ name: mealName.trim(), from_log_id: justLogged!.id }),
    onSuccess: (m) => {
      queryClient.invalidateQueries({ queryKey: ["saved-meals"] });
      toast(`Saved "${m.name}" — one tap next time`);
      setJustLogged(null);
      onClose();
    },
    onError: (e) => toast(e.message, "err"),
  });

  const totals = picked.reduce(
    (a, p) => {
      const f = p.quantity / (p.food.serving_unit === "piece" || p.food.serving_unit === "serving" ? 1 : p.food.serving_size);
      const factor = p.food.serving_unit === "piece" ? p.quantity : f;
      a.calories += p.food.calories * factor;
      a.protein += p.food.protein * factor;
      return a;
    },
    { calories: 0, protein: 0 }
  );

  return (
    <Sheet open={open} onClose={onClose} title="Log food" wide>
      <div className="space-y-4">
        <Field label="Meal">
          <div className="flex flex-wrap gap-1.5">
            {MEAL_TYPES.slice(0, 6).map((m) => (
              <button
                key={m}
                onClick={() => setMeal(m)}
                className={cx(
                  "rounded-lg border px-3 py-1.5 text-[13px] font-medium capitalize transition-colors",
                  meal === m ? "border-accent bg-accent-soft text-accent" : "border-line text-muted hover:text-ink"
                )}
              >
                {m.replace("_", " ")}
              </button>
            ))}
          </div>
        </Field>

        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-3.5 top-3.5 text-faint" />
            <Input className="pl-10" placeholder="Search foods — rice, eggs, chicken…" value={query}
                   onChange={(e) => setQuery(e.target.value)} autoFocus />
          </div>
          <Button
            variant="outline"
            className={cx("h-11 w-11 shrink-0 px-0", barcodeOpen && "border-accent text-accent")}
            onClick={() => setBarcodeOpen(!barcodeOpen)}
            aria-label="Look up barcode"
          >
            <ScanBarcode size={18} />
          </Button>
        </div>

        <button
          onClick={() => setOnline(!online)}
          className={cx(
            "flex items-center gap-1.5 text-xs font-medium transition-colors",
            online ? "text-accent" : "text-faint hover:text-muted"
          )}
        >
          <Globe size={13} /> Search online too{online ? " · on (USDA, OpenFoodFacts)" : ""}
        </button>

        {barcodeOpen && (
          <div className="space-y-2 rounded-xl border border-line bg-surface-2/50 p-3">
            <div className="flex gap-2">
              <Input
                className="h-9 text-sm"
                placeholder="Type or paste barcode…"
                inputMode="numeric"
                value={barcode}
                onChange={(e) => setBarcode(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && barcode.trim() && lookupBarcode.mutate(barcode)}
              />
              <Button
                size="sm"
                variant="outline"
                className="h-9 shrink-0"
                disabled={!barcode.trim() || lookupBarcode.isPending}
                onClick={() => lookupBarcode.mutate(barcode)}
              >
                {lookupBarcode.isPending ? "…" : "Look up"}
              </Button>
            </div>
            {scanning ? (
              <BarcodeScanner
                onResult={(code) => { setBarcode(code); setScanning(false); lookupBarcode.mutate(code); }}
                onError={() => setScanning(false)}
              />
            ) : (
              <button
                onClick={() => setScanning(true)}
                className="flex items-center gap-1.5 text-xs font-medium text-muted hover:text-ink"
              >
                <Camera size={13} /> Scan with camera
              </button>
            )}
          </div>
        )}

        {isFetching && <Spinner className="mx-auto" />}
        <div className="max-h-56 space-y-1 overflow-y-auto">
          {results?.map((food) => (
            <button
              key={food.id}
              onClick={() => {
                if (!picked.find((p) => p.food.id === food.id)) {
                  setPicked([...picked, { food, quantity: food.serving_size }]);
                }
              }}
              className="flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-left text-sm hover:bg-surface-2"
            >
              <span className="flex min-w-0 items-center font-medium">
                <span className="truncate">{food.name}</span>
                {(food.source === "usda" || food.source === "openfoodfacts") && (
                  <span className="ml-2 shrink-0 rounded-md bg-gold-soft px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gold">
                    {food.source === "usda" ? "USDA" : "OpenFoodFacts"}
                  </span>
                )}
              </span>
              <span className="shrink-0 text-xs text-muted">
                {fmtNumber(food.calories)} kcal / {fmtNumber(food.serving_size)}{food.serving_unit}
              </span>
            </button>
          ))}
          {query && results && results.length === 0 && (
            <div className="px-3 py-2 text-sm text-muted">
              Not in database.{" "}
              <button className="font-semibold text-accent" onClick={() => { setCustomName(query); }}>
                Log anyway (no nutrition)
              </button>
            </div>
          )}
        </div>

        {customName && (
          <div className="flex items-center gap-2 rounded-xl border border-gold/40 bg-gold-soft p-3 text-sm">
            <span className="flex-1">&ldquo;{customName}&rdquo; — quantity in grams, no nutrition data</span>
            <Button size="sm" variant="outline" onClick={() => {
              setPicked([...picked, {
                food: { id: "", name: customName, serving_size: 100, serving_unit: "g", calories: 0, protein: 0, carbs: 0, fat: 0, fiber: 0, brand: null, source: "custom" },
                quantity: 100,
              }]);
              setCustomName("");
            }}>Add</Button>
            <button onClick={() => setCustomName("")} className="text-faint">✕</button>
          </div>
        )}

        {picked.length > 0 && (
          <div className="rounded-xl border border-line bg-surface-2/50 p-3">
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-faint">
              {picked.length} item{picked.length > 1 ? "s" : ""} · ~{fmtNumber(totals.calories)} kcal · {fmtNumber(totals.protein)}g protein
            </div>
            {picked.map((p, i) => (
              <div key={p.food.id || p.food.name} className="flex items-center gap-2 py-1.5">
                <span className="flex-1 truncate text-sm font-medium">{p.food.name}</span>
                <Input
                  type="number" min={0} className="h-9 w-24 text-right" value={p.quantity || ""}
                  onChange={(e) => {
                    const next = [...picked];
                    next[i] = { ...p, quantity: parseFloat(e.target.value) || 0 };
                    setPicked(next);
                  }}
                />
                <span className="w-10 text-xs text-faint">{p.food.serving_unit}</span>
                <button onClick={() => setPicked(picked.filter((_, j) => j !== i))} className="text-faint hover:text-bad">
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}

        {justLogged ? (
          <div className="rounded-xl border border-olive/40 bg-olive-soft p-3.5">
            <div className="text-sm font-semibold text-olive">
              Logged — {fmtNumber(justLogged.calories)} kcal
            </div>
            <div className="mt-2.5 flex gap-2">
              <Input
                className="h-9 bg-surface text-sm" placeholder="Save as meal — name it"
                value={mealName} onChange={(e) => setMealName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && mealName.trim() && saveMeal.mutate()}
              />
              <Button size="sm" variant="outline" className="h-9 shrink-0 bg-surface"
                      disabled={!mealName.trim() || saveMeal.isPending} onClick={() => saveMeal.mutate()}>
                {saveMeal.isPending ? "Saving…" : "Save as meal"}
              </Button>
            </div>
            <button onClick={onClose} className="mt-2 text-xs font-medium text-faint hover:text-muted">
              Done — don&rsquo;t save
            </button>
          </div>
        ) : (
          <Button className="w-full" disabled={picked.length === 0 || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : "Log meal"}
          </Button>
        )}
      </div>
    </Sheet>
  );
}
