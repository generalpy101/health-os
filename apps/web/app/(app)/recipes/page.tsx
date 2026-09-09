"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, Plus, Search, Trash2, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { TopBar } from "@/components/nav";
import { Button, Card, Empty, Field, Input, PageLoading, Sheet, Textarea, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { Recipe } from "@/lib/types";
import { fmtNumber } from "@/lib/utils";

export default function RecipesPage() {
  const [open, setOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [editRecipe, setEditRecipe] = useState<Recipe | null>(null);
  const [q, setQ] = useState("");
  const { data: recipes, isLoading } = useQuery({ queryKey: ["recipes", q], queryFn: () => api.recipes(q) });
  // TRACK D: what you can cook from the pantry right now
  const { data: matches } = useQuery({ queryKey: ["pantry-matches"], queryFn: api.pantryRecipeMatches });
  const cookable = (matches || []).filter((m) => m.coverage >= 0.6);
  const queryClient = useQueryClient();
  const toast = useToast();
  const del = useMutation({
    mutationFn: api.deleteRecipe,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["recipes"] }),
    onError: (e) => toast(e.message, "err"),
  });

  return (
    <>
      <TopBar title="Recipes" right={<Button size="sm" onClick={() => setOpen(true)}><Plus size={15} /> New recipe</Button>} />
      <main className="mx-auto max-w-5xl px-4 py-5 sm:px-6">
        <div className="relative mb-4">
          <Search size={16} className="absolute left-3.5 top-3.5 text-faint" />
          <Input className="pl-10" placeholder="Search recipes…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {cookable.length > 0 && (
          <div className="mb-4">
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
              From your pantry
            </div>
            <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1">
              {cookable.map((m) => (
                <div key={m.recipe_id} className="min-w-[10rem] shrink-0 rounded-xl border border-line bg-surface p-3">
                  <div className="truncate text-sm font-semibold">{m.name}</div>
                  <div className="mt-1 text-[11px] text-faint">
                    <span className="font-semibold text-olive">{Math.round(m.coverage * 100)}% in pantry</span>
                    {m.missing.length > 0 && <span> · missing {m.missing.length}</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        {isLoading ? (
          <PageLoading />
        ) : !recipes?.length ? (
          <Card>
            <Empty title="No recipes yet"
                   hint="Build recipes from foods — nutrition per serving is calculated automatically."
                   action={<Button onClick={() => setOpen(true)}><Plus size={15} /> Create recipe</Button>} />
          </Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {recipes.map((r) => (
              <Card key={r.id} className="flex cursor-pointer flex-col p-4 transition-colors hover:border-accent/40"
                    onClick={() => setDetailId(r.id)}>
                <div className="flex items-start justify-between gap-2">
                  <h3 className="font-display text-lg font-semibold leading-tight">{r.name}</h3>
                  <button onClick={(e) => { e.stopPropagation(); del.mutate(r.id); }} aria-label="Delete" className="p-1 text-faint hover:text-bad">
                    <Trash2 size={15} />
                  </button>
                </div>
                {r.description && <p className="mt-1 line-clamp-2 text-[13px] text-muted">{r.description}</p>}
                <div className="mt-auto pt-3">
                  <div className="flex items-center gap-3 text-xs text-faint">
                    <span className="flex items-center gap-1"><Users size={12} /> {fmtNumber(r.servings)}</span>
                    {(r.prep_minutes || r.cook_minutes) && (
                      <span className="flex items-center gap-1"><Clock size={12} /> {(r.prep_minutes || 0) + (r.cook_minutes || 0)}min</span>
                    )}
                    {r.cuisine && <span className="capitalize">{r.cuisine}</span>}
                  </div>
                  <div className="mt-2 flex gap-2 text-[11px] font-semibold">
                    <span className="rounded-md bg-accent-soft px-2 py-1 text-accent">{fmtNumber(r.nutrition?.per_serving?.calories)} kcal</span>
                    <span className="rounded-md bg-olive-soft px-2 py-1 text-olive">{fmtNumber(r.nutrition?.per_serving?.protein)}g P</span>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </main>
      <NewRecipeSheet open={open} onClose={() => setOpen(false)} />
      <NewRecipeSheet
        open={!!editRecipe}
        onClose={() => setEditRecipe(null)}
        edit={editRecipe}
      />
      <RecipeDetailSheet
        recipe={recipes?.find((r) => r.id === detailId) ?? null}
        onClose={() => setDetailId(null)}
        onEdit={(r) => { setDetailId(null); setEditRecipe(r); }}
      />
    </>
  );
}

function RecipeDetailSheet({ recipe, onClose, onEdit }: {
  recipe: Recipe | null; onClose: () => void; onEdit: (r: Recipe) => void;
}) {
  const [servings, setServings] = useState(1);
  const [meal, setMeal] = useState("dinner");
  const queryClient = useQueryClient();
  const toast = useToast();

  const logIt = useMutation({
    mutationFn: () => {
      if (!recipe) return Promise.reject(new Error("no recipe"));
      const scale = servings / (recipe.servings || 1);
      return api.logFood({
        meal_type: meal,
        note: `Recipe: ${recipe.name}`,
        items: (recipe.ingredients || []).map((i) => ({
          name: i.name, quantity: Math.round(i.quantity * scale * 10) / 10, unit: i.unit,
          ...(i.food_id ? { food_id: i.food_id } : {}),
        })),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries();
      toast(`Logged ${recipe?.name}`);
      onClose();
    },
    onError: (e) => toast(e.message, "err"),
  });

  if (!recipe) return null;
  const n = recipe.nutrition?.per_serving || {};
  const totalMin = (recipe.prep_minutes || 0) + (recipe.cook_minutes || 0);

  return (
    <Sheet open={!!recipe} onClose={onClose} title={recipe.name} wide>
      <div className="space-y-4">
        {recipe.description && <p className="text-sm leading-relaxed text-muted">{recipe.description}</p>}
        <div className="flex flex-wrap gap-2 text-[11px] font-semibold">
          <span className="rounded-md bg-accent-soft px-2 py-1 text-accent">{fmtNumber(n.calories)} kcal</span>
          <span className="rounded-md bg-olive-soft px-2 py-1 text-olive">{fmtNumber(n.protein)}g protein</span>
          <span className="rounded-md bg-gold-soft px-2 py-1 text-gold">{fmtNumber(n.carbs)}g carbs</span>
          <span className="rounded-md bg-berry-soft px-2 py-1 text-berry">{fmtNumber(n.fat)}g fat</span>
          <span className="rounded-md bg-surface-2 px-2 py-1 text-muted">per serving · {fmtNumber(recipe.servings)} servings</span>
          {totalMin > 0 && <span className="rounded-md bg-surface-2 px-2 py-1 text-muted">{totalMin} min</span>}
        </div>

        {(recipe.ingredients?.length ?? 0) > 0 && (
          <div>
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">Ingredients</div>
            <ul className="divide-y divide-line rounded-xl border border-line">
              {recipe.ingredients.map((i, idx) => (
                <li key={idx} className="flex items-center justify-between px-3.5 py-2 text-sm">
                  <span>{i.name}</span>
                  <span className="text-muted">{fmtNumber(i.quantity, 1)}{i.unit}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {(recipe.steps?.length ?? 0) > 0 && (
          <div>
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">Steps</div>
            <ol className="space-y-2">
              {recipe.steps.map((s, i) => (
                <li key={i} className="flex gap-3 text-sm leading-relaxed">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[10px] font-bold text-muted">{i + 1}</span>
                  {s}
                </li>
              ))}
            </ol>
          </div>
        )}

        <div className="rounded-xl border border-line bg-surface-2/40 p-3.5">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">Log this recipe</div>
          <div className="flex items-center gap-2">
            <Input type="number" min={0.5} step={0.5} value={servings || ""}
                   onChange={(e) => setServings(parseFloat(e.target.value) || 0)}
                   className="h-10 w-20 text-center" aria-label="Servings" />
            <span className="text-xs text-faint">srv</span>
            <div className="flex flex-1 gap-1">
              {["breakfast", "lunch", "dinner", "snack"].map((m) => (
                <button key={m} onClick={() => setMeal(m)}
                        className={`flex-1 rounded-lg border px-1 py-1.5 text-[11px] font-medium capitalize ${meal === m ? "border-accent bg-accent-soft text-accent" : "border-line text-muted"}`}>
                  {m}
                </button>
              ))}
            </div>
          </div>
          <Button className="mt-2.5 w-full" onClick={() => logIt.mutate()} disabled={!servings || logIt.isPending}>
            {logIt.isPending ? "Logging…" : `Log ${servings || 0} serving${servings === 1 ? "" : "s"} (~${fmtNumber((n.calories || 0) * servings)} kcal)`}
          </Button>
        </div>

        <Button variant="outline" className="w-full" onClick={() => onEdit(recipe)}>Edit recipe</Button>
      </div>
    </Sheet>
  );
}

function NewRecipeSheet({ open, onClose, edit }: { open: boolean; onClose: () => void; edit?: Recipe | null }) {
  const [name, setName] = useState("");
  const [servings, setServings] = useState("2");
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<{ name: string; food_id?: string; quantity: number; unit: string }[]>([]);
  const [steps, setSteps] = useState("");
  const queryClient = useQueryClient();
  const toast = useToast();

  const { data: foods } = useQuery({
    queryKey: ["foods", query],
    queryFn: () => api.searchFoods(query, 8),
    enabled: open,
  });

  // edit mode: prefill from the recipe being edited
  useEffect(() => {
    if (open && edit) {
      setName(edit.name);
      setServings(String(edit.servings));
      setPicked((edit.ingredients || []).map((i) => ({
        name: i.name, quantity: i.quantity, unit: i.unit,
        ...(i.food_id ? { food_id: i.food_id } : {}),
      })));
      setSteps((edit.steps || []).join("\n"));
    } else if (open && !edit) {
      setName(""); setServings("2"); setPicked([]); setSteps("");
    }
  }, [open, edit]);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name, servings: parseFloat(servings) || 1,
        ingredients: picked,
        steps: steps.split("\n").map((s) => s.trim()).filter(Boolean),
      };
      return edit ? api.updateRecipe(edit.id, body) : api.createRecipe(body);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recipes"] });
      toast(edit ? "Recipe updated" : "Recipe created");
      setName(""); setPicked([]); setSteps("");
      onClose();
    },
    onError: (e) => toast(e.message, "err"),
  });

  return (
    <Sheet open={open} onClose={onClose} title={edit ? "Edit recipe" : "New recipe"} wide>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (name.trim()) save.mutate(); }}>
        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2">
            <Field label="Name"><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="High-protein rice bowl" /></Field>
          </div>
          <Field label="Servings"><Input inputMode="decimal" value={servings} onChange={(e) => setServings(e.target.value)} /></Field>
        </div>
        <Field label="Ingredients" hint="Search and add; nutrition is computed per serving">
          <Input placeholder="Search foods…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </Field>
        {query && (
          <div className="max-h-36 space-y-0.5 overflow-y-auto rounded-xl border border-line">
            {foods?.map((f) => (
              <button type="button" key={f.id}
                      onClick={() => { setPicked([...picked, { name: f.name, food_id: f.id, quantity: f.serving_size, unit: f.serving_unit }]); setQuery(""); }}
                      className="flex w-full justify-between px-3 py-2 text-left text-sm hover:bg-surface-2">
                <span>{f.name}</span>
                <span className="text-xs text-faint">{fmtNumber(f.calories)} kcal / {fmtNumber(f.serving_size)}{f.serving_unit}</span>
              </button>
            ))}
          </div>
        )}
        {picked.length > 0 && (
          <div className="space-y-1.5 rounded-xl border border-line p-3">
            {picked.map((p, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="flex-1 truncate text-sm font-medium">{p.name}</span>
                <Input type="number" className="h-9 w-24 text-right" value={p.quantity || ""}
                       onChange={(e) => {
                         const next = [...picked];
                         next[i] = { ...p, quantity: parseFloat(e.target.value) || 0 };
                         setPicked(next);
                       }} />
                <span className="w-10 text-xs text-faint">{p.unit}</span>
                <button type="button" onClick={() => setPicked(picked.filter((_, j) => j !== i))} className="text-faint hover:text-bad">
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
        <Field label="Steps (one per line)">
          <Textarea rows={4} value={steps} onChange={(e) => setSteps(e.target.value)} placeholder={"Cook rice\nGrill chicken\nAssemble"} />
        </Field>
        <Button type="submit" className="w-full" disabled={!name.trim() || save.isPending}>
          {save.isPending ? "Saving…" : "Create recipe"}
        </Button>
      </form>
    </Sheet>
  );
}
