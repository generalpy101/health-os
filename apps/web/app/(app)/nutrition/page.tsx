"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { TopBar } from "@/components/nav";
import {
  Button, Card, CardTitle, Empty, Field, Input, PageLoading, Select, Sheet, Spinner, useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import type { Food } from "@/lib/types";
import { MEAL_TYPES, cx, fmtNumber, todayISO } from "@/lib/utils";

export default function NutritionPage() {
  const [day, setDay] = useState(todayISO());
  const [logOpen, setLogOpen] = useState(false);
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
          <div className="flex items-center gap-2">
            <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} className="h-9 w-auto text-sm" />
            <Button size="sm" onClick={() => setLogOpen(true)}><Plus size={15} /> Log food</Button>
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
                      <li key={i} className="flex items-center justify-between py-2 text-sm">
                        <span>
                          {item.name}
                          <span className="ml-2 text-xs text-faint">
                            {fmtNumber(item.quantity)}{item.unit}
                            {item.unmatched && <span className="ml-1 text-gold">· not in database</span>}
                          </span>
                        </span>
                        <span className="text-muted">{fmtNumber(item.calories)} kcal · {fmtNumber(item.protein)}g P</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              ))
            )}
          </>
        )}
      </main>
      <LogFoodSheet open={logOpen} onClose={() => setLogOpen(false)} day={day} />
    </>
  );
}

function LogFoodSheet({ open, onClose, day }: { open: boolean; onClose: () => void; day: string }) {
  const [meal, setMeal] = useState<string>("lunch");
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<{ food: Food; quantity: number }[]>([]);
  const [customName, setCustomName] = useState("");
  const queryClient = useQueryClient();
  const toast = useToast();

  const { data: results, isFetching } = useQuery({
    queryKey: ["foods", query],
    queryFn: () => api.searchFoods(query, 12),
    enabled: open,
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
    onSuccess: () => {
      queryClient.invalidateQueries();
      toast("Meal logged");
      setPicked([]);
      setQuery("");
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

        <div className="relative">
          <Search size={16} className="absolute left-3.5 top-3.5 text-faint" />
          <Input className="pl-10" placeholder="Search foods — rice, eggs, chicken…" value={query}
                 onChange={(e) => setQuery(e.target.value)} autoFocus />
        </div>

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
              <span className="font-medium">{food.name}</span>
              <span className="text-xs text-muted">
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

        <Button className="w-full" disabled={picked.length === 0 || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Log meal"}
        </Button>
      </div>
    </Sheet>
  );
}
