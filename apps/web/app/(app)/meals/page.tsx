"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChefHat, Plus, ShoppingBasket, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { TopBar } from "@/components/nav";
import { DayTimeline } from "@/components/day-timeline";
import { Button, Card, Empty, Field, Input, PageLoading, Segmented, Select, Sheet, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { Recipe } from "@/lib/types";
import { addDays, cx, fmtNumber, toISODate, todayISO } from "@/lib/utils";

const SLOTS = ["breakfast", "lunch", "dinner", "snack"] as const;
const DAY_LETTERS = ["M", "T", "W", "T", "F", "S", "S"];

export default function MealsPage() {
  const [weekOffset, setWeekOffset] = useState(0);
  const [view, setView] = useState<"board" | "timeline">("board");
  const [tlDay, setTlDay] = useState(todayISO());
  const [slot, setSlot] = useState<{ date: string; meal: string; time?: string } | null>(null);
  const [groceryOpen, setGroceryOpen] = useState(false);
  const queryClient = useQueryClient();
  const toast = useToast();

  const { start, days } = useMemo(() => {
    const now = new Date();
    const monday = addDays(now, -((now.getDay() + 6) % 7) + weekOffset * 7);
    return { start: monday, days: Array.from({ length: 7 }, (_, i) => addDays(monday, i)) };
  }, [weekOffset]);
  const startISO = toISODate(start);
  const endISO = toISODate(addDays(start, 6));

  const { data: plans, isLoading } = useQuery({
    queryKey: ["meal-plans", startISO],
    queryFn: () => api.mealPlans(startISO, endISO),
  });
  // what you actually ate — shown alongside the plan
  const { data: weekLogs } = useQuery({
    queryKey: ["food-logs", startISO],
    queryFn: () => api.foodLogsRange(startISO, endISO),
  });
  const { data: recipes } = useQuery({ queryKey: ["recipes", ""], queryFn: () => api.recipes() });

  const del = useMutation({
    mutationFn: api.deleteMealPlan,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["meal-plans"] }),
    onError: (e) => toast(e.message, "err"),
  });

  const logPlanned = useMutation({
    mutationFn: async (planId: string) => {
      const plan = plans?.find((p) => p.id === planId);
      if (!plan) return;
      let items: { name: string; quantity: number; unit: string; food_id?: string }[];
      if (plan.recipe_id) {
        const recipe = recipes?.find((r) => r.id === plan.recipe_id);
        if (!recipe) throw new Error("Recipe not loaded");
        const scale = (plan.servings || 1) / (recipe.servings || 1);
        items = recipe.ingredients.map((i) => ({
          name: i.name, quantity: Math.round(i.quantity * scale * 10) / 10,
          unit: i.unit, ...(i.food_id ? { food_id: i.food_id } : {}),
        }));
      } else {
        items = [{ name: plan.name, quantity: 1, unit: "serving" }];
      }
      return api.logFood({ date: todayISO(), meal_type: plan.meal_type, items, note: `Planned: ${plan.name}` });
    },
    onSuccess: () => {
      queryClient.invalidateQueries();
      toast("Logged to today");
    },
    onError: (e) => toast(e.message, "err"),
  });

  const todayStr = todayISO();

  return (
    <>
      <TopBar
        title="Meal planner"
        right={
          <div className="flex items-center gap-1.5 sm:gap-2">
            <Segmented options={[{ value: "board", label: "Board" }, { value: "timeline", label: "Timeline" }]}
                       value={view} onChange={setView} />
            <Button size="sm" variant="outline" onClick={() => setGroceryOpen(true)}>
              <ShoppingBasket size={15} /><span className="hidden sm:inline"> Groceries</span>
            </Button>
          </div>
        }
      />
      <main className="mx-auto max-w-5xl px-4 py-5 sm:px-6">
        {view === "timeline" ? (
          <>
            <div className="mb-4 flex items-center justify-between">
              <Button variant="ghost" size="sm" onClick={() => setTlDay(toISODate(addDays(new Date(tlDay), -1)))}>← Prev</Button>
              <div className="text-center">
                <div className="font-display text-lg font-semibold">
                  {new Date(tlDay + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
                </div>
                {tlDay !== todayISO() && (
                  <button className="text-xs font-medium text-accent" onClick={() => setTlDay(todayISO())}>Today</button>
                )}
              </div>
              <Button variant="ghost" size="sm" onClick={() => setTlDay(toISODate(addDays(new Date(tlDay), 1)))}>Next →</Button>
            </div>
            <DayTimeline
              day={tlDay}
              onPickSlot={(min) => setSlot({
                date: tlDay, meal: "other",
                time: `${String(Math.floor(min / 60)).padStart(2, "0")}:00`,
              })}
            />
          </>
        ) : (
          <>
        <div className="mb-4 flex items-center justify-between">
          <Button variant="ghost" size="sm" onClick={() => setWeekOffset(weekOffset - 1)}>← Prev</Button>
          <div className="text-center">
            <div className="font-display text-lg font-semibold">
              {start.toLocaleDateString(undefined, { month: "short", day: "numeric" })} – {addDays(start, 6).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
            </div>
            {weekOffset !== 0 && <button className="text-xs font-medium text-accent" onClick={() => setWeekOffset(0)}>This week</button>}
          </div>
          <Button variant="ghost" size="sm" onClick={() => setWeekOffset(weekOffset + 1)}>Next →</Button>
        </div>

        {isLoading ? (
          <PageLoading />
        ) : (
          <div className="space-y-3">
            {days.map((day) => {
              const iso = toISODate(day);
              const dayPlans = (plans || []).filter((p) => p.date === iso);
              const isToday = iso === todayStr;
              return (
                <Card key={iso} className={cx("p-3.5", isToday && "border-accent/50")}>
                  <div className="mb-2 flex items-center gap-2 px-1">
                    <span className="text-[11px] font-bold uppercase tracking-wide text-faint">
                      {DAY_LETTERS[(day.getDay() + 6) % 7]}
                    </span>
                    <span className={cx("font-display text-lg font-semibold", isToday && "text-accent")}>
                      {day.getDate()}
                    </span>
                    {isToday && <span className="rounded-md bg-accent-soft px-1.5 py-0.5 text-[10px] font-bold uppercase text-accent">Today</span>}
                  </div>
                  <div className="grid gap-1.5 sm:grid-cols-4">
                    {SLOTS.map((meal) => {
                      const slotPlans = dayPlans.filter((p) => p.meal_type === meal);
                      const loggedForSlot = (weekLogs || []).find((l) => l.date === iso && l.meal_type === meal);
                      return (
                        <div key={meal} className="rounded-xl bg-surface-2/50 p-2.5">
                          <div className="mb-1.5 flex items-center justify-between">
                            <span className="text-[10px] font-bold uppercase tracking-wide text-faint">{meal}</span>
                            <button
                              aria-label={`Add ${meal}`}
                              onClick={() => setSlot({ date: iso, meal })}
                              className="rounded p-0.5 text-faint hover:text-accent"
                            >
                              <Plus size={13} />
                            </button>
                          </div>
                          {slotPlans.length === 0 && !loggedForSlot && (
                            <div className="py-1 text-[11px] text-faint/60">—</div>
                          )}
                          {loggedForSlot && (
                            <div className="mb-1 rounded-lg bg-olive-soft/60 px-2 py-1 text-[11px] font-medium text-olive"
                                 title={loggedForSlot.items.map((i) => i.name).join(", ")}>
                              ✓ {loggedForSlot.calories > 0 ? `${fmtNumber(loggedForSlot.calories)} kcal logged` : "logged"}
                            </div>
                          )}
                          {slotPlans.length > 0 && (
                            slotPlans.map((p) => (
                              <div key={p.id} className="group mb-1 rounded-lg bg-surface px-2 py-1.5 text-xs">
                                <div className="flex items-center gap-1">
                                  <span className="min-w-0 flex-1 truncate font-medium">{p.name}</span>
                                  <button
                                    aria-label="Log this meal today"
                                    title="Log this meal today"
                                    onClick={() => logPlanned.mutate(p.id)}
                                    className="shrink-0 text-faint hover:text-good"
                                  >
                                    <Check size={12} />
                                  </button>
                                  <button
                                    aria-label="Remove from plan"
                                    onClick={() => del.mutate(p.id)}
                                    className="shrink-0 text-faint hover:text-bad"
                                  >
                                    <Trash2 size={12} />
                                  </button>
                                </div>
                                {p.recipe_id && (
                                  <div className="text-[10px] text-faint">
                                    {recipes?.find((r) => r.id === p.recipe_id)
                                      ? `${fmtNumber((recipes.find((r) => r.id === p.recipe_id)!.nutrition?.per_serving?.calories || 0) * (p.servings || 1))} kcal`
                                      : "recipe"}
                                  </div>
                                )}
                              </div>
                            ))
                          )}
                        </div>
                      );
                    })}
                  </div>
                </Card>
              );
            })}
          </div>
        )}
          </>
        )}
      </main>

      <AddMealSheet slot={slot} onClose={() => setSlot(null)} recipes={recipes || []} />
      <GrocerySheet open={groceryOpen} onClose={() => setGroceryOpen(false)} start={startISO} end={endISO} />
    </>
  );
}

function AddMealSheet({ slot, onClose, recipes }: {
  slot: { date: string; meal: string; time?: string } | null; onClose: () => void; recipes: Recipe[];
}) {
  const [name, setName] = useState("");
  const [recipeId, setRecipeId] = useState("");
  const [time, setTime] = useState("");
  const queryClient = useQueryClient();
  const toast = useToast();

  useEffect(() => { if (slot) setTime(slot.time || ""); }, [slot]);

  const save = useMutation({
    mutationFn: () =>
      api.createMealPlan({
        date: slot!.date, meal_type: slot!.meal,
        ...(time ? { time } : {}),
        ...(recipeId ? { recipe_id: recipeId, name: recipes.find((r) => r.id === recipeId)?.name || name } : { name }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["meal-plans"] });
      toast("Added to plan");
      setName(""); setRecipeId("");
      onClose();
    },
    onError: (e) => toast(e.message, "err"),
  });

  return (
    <Sheet open={!!slot} onClose={onClose} title={slot ? `${slot.meal[0].toUpperCase() + slot.meal.slice(1)} — ${slot.date}` : ""}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (name.trim() || recipeId) save.mutate(); }}>
        <Field label="Time (optional)" hint="Leave empty for 'anytime' — your schedule isn't rigid">
          <Input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
        </Field>
        <Field label="From your recipes">
          <Select value={recipeId} onChange={(e) => setRecipeId(e.target.value)}>
            <option value="">— pick a recipe —</option>
            {recipes.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name} · {fmtNumber(r.nutrition?.per_serving?.calories)} kcal
              </option>
            ))}
          </Select>
        </Field>
        {!recipeId && (
          <Field label="Or free text" hint='e.g. "Dal + rice + salad"'>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Simple meal" />
          </Field>
        )}
        <Button type="submit" className="w-full" disabled={(!name.trim() && !recipeId) || save.isPending}>
          {save.isPending ? "Adding…" : "Add to plan"}
        </Button>
        {recipes.length === 0 && (
          <p className="text-center text-xs text-faint">
            No recipes yet — <a href="/recipes" className="text-accent underline">create one</a> to plan with nutrition.
          </p>
        )}
      </form>
    </Sheet>
  );
}

function GrocerySheet({ open, onClose, start, end }: { open: boolean; onClose: () => void; start: string; end: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["grocery", start, end],
    queryFn: () => api.groceryList(start, end),
    enabled: open,
  });
  const queryClient = useQueryClient();
  const toast = useToast();
  // TRACK D: restock the pantry from the week's groceries in one tap
  const purchase = useMutation({
    mutationFn: () => api.purchaseGroceries(start, end),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ["pantry"] });
      queryClient.invalidateQueries({ queryKey: ["pantry-matches"] });
      toast(`Added ${r.added} item${r.added === 1 ? "" : "s"} to pantry`);
      onClose();
    },
    onError: (e) => toast(e.message, "err"),
  });
  return (
    <Sheet open={open} onClose={onClose} title="Grocery list — this week">
      {isLoading ? (
        <PageLoading />
      ) : !data?.items.length ? (
        <Empty title="Nothing to buy" hint="Plan meals with recipes and ingredients consolidate here automatically." />
      ) : (
        <>
          <ul className="divide-y divide-line">
            {data.items.map((i) => (
              <li key={i.name + i.unit} className="flex items-center justify-between py-2.5 text-sm">
                <span className="font-medium capitalize">{i.name}</span>
                <span className="font-display font-semibold">
                  {i.unit === "g" && i.quantity >= 1000
                    ? `${(i.quantity / 1000).toFixed(1)} kg`
                    : `${fmtNumber(i.quantity, 1)} ${i.unit}`}
                </span>
              </li>
            ))}
          </ul>
          <Button className="mt-4 w-full" variant="outline" onClick={() => purchase.mutate()} disabled={purchase.isPending}>
            <Check size={15} /> {purchase.isPending ? "Adding…" : "Mark all purchased"}
          </Button>
        </>
      )}
    </Sheet>
  );
}
