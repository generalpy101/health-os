"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { TopBar } from "@/components/nav";
import { Button, Card, Empty, Field, Input, PageLoading, Select, Sheet, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { Food, PantryItem } from "@/lib/types";
import { cx, fmtDate, fmtNumber, todayISO } from "@/lib/utils";

const LOCATIONS = ["pantry", "fridge", "freezer", "other"];

function expiryInfo(iso: string | null): { text: string; cls: string } | null {
  if (!iso) return null;
  const ms = new Date(iso + "T00:00:00").getTime() - new Date(todayISO() + "T00:00:00").getTime();
  const days = Math.round(ms / 86_400_000);
  if (days < 0) return { text: "expired", cls: "text-bad" };
  if (days === 0) return { text: "expires today", cls: "text-gold" };
  if (days === 1) return { text: "expires tomorrow", cls: "text-gold" };
  if (days <= 3) return { text: `expires in ${days}d`, cls: "text-gold" };
  return { text: fmtDate(iso), cls: "text-faint" };
}

export default function PantryPage() {
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<PantryItem | null>(null);
  const { data: items, isLoading } = useQuery({ queryKey: ["pantry"], queryFn: api.pantry });
  const queryClient = useQueryClient();
  const toast = useToast();

  const del = useMutation({
    mutationFn: api.deletePantryItem,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["pantry"] }),
    onError: (e) => toast(e.message, "err"),
  });

  const groups = useMemo(() => {
    const by: Record<string, PantryItem[]> = {};
    for (const item of items || []) (by[item.location] ||= []).push(item);
    return Object.entries(by); // service already sorts by location, name
  }, [items]);

  return (
    <>
      <TopBar
        title="Pantry"
        right={
          <Button size="sm" onClick={() => { setEditing(null); setSheetOpen(true); }}>
            <Plus size={15} /> Add item
          </Button>
        }
      />
      <main className="mx-auto max-w-5xl space-y-4 px-4 py-5 sm:px-6">
        {isLoading ? (
          <PageLoading />
        ) : !items?.length ? (
          <Card>
            <Empty
              title="Pantry is empty"
              hint="Track what you have on hand — recipes show what you can cook, and grocery runs restock it."
              action={<Button onClick={() => { setEditing(null); setSheetOpen(true); }}><Plus size={15} /> Add item</Button>}
            />
          </Card>
        ) : (
          groups.map(([location, rows]) => (
            <Card key={location}>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                {location}
              </div>
              <ul className="divide-y divide-line">
                {rows.map((item) => {
                  const expiry = expiryInfo(item.expires_on);
                  return (
                    <li key={item.id} className="flex items-center gap-3 py-2.5">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">{item.name}</div>
                        <div className="text-xs text-faint">
                          {fmtNumber(item.quantity, 1)} {item.unit}
                          {item.food_id && <span className="ml-1.5 text-olive">· linked</span>}
                        </div>
                      </div>
                      {expiry && (
                        <span className={cx("shrink-0 text-xs font-medium", expiry.cls)}>{expiry.text}</span>
                      )}
                      <button
                        aria-label={`Edit ${item.name}`}
                        onClick={() => { setEditing(item); setSheetOpen(true); }}
                        className="shrink-0 text-faint hover:text-ink"
                      >
                        <Pencil size={15} />
                      </button>
                      <button
                        aria-label={`Delete ${item.name}`}
                        onClick={() => del.mutate(item.id)}
                        className="shrink-0 text-faint hover:text-bad"
                      >
                        <Trash2 size={15} />
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Card>
          ))
        )}
      </main>
      <PantryItemSheet open={sheetOpen} onClose={() => setSheetOpen(false)} item={editing} />
    </>
  );
}

function PantryItemSheet({ open, onClose, item }: { open: boolean; onClose: () => void; item: PantryItem | null }) {
  const [name, setName] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [unit, setUnit] = useState("g");
  const [location, setLocation] = useState("pantry");
  const [expires, setExpires] = useState("");
  const [foodQuery, setFoodQuery] = useState("");
  const [food, setFood] = useState<{ id: string; name: string } | null>(null);
  const queryClient = useQueryClient();
  const toast = useToast();

  useEffect(() => {
    if (!open) return;
    setName(item?.name || "");
    setQuantity(item ? String(item.quantity) : "1");
    setUnit(item?.unit || "g");
    setLocation(item?.location || "pantry");
    setExpires(item?.expires_on || "");
    setFood(item?.food_id ? { id: item.food_id, name: "Linked food" } : null);
    setFoodQuery("");
  }, [open, item]);

  const { data: foods } = useQuery({
    queryKey: ["foods", foodQuery],
    queryFn: () => api.searchFoods(foodQuery, 6),
    enabled: open && foodQuery.length > 0,
  });

  const save = useMutation({
    mutationFn: () => {
      const base = {
        name: name.trim(),
        quantity: parseFloat(quantity) || 0,
        unit: unit.trim() || "pcs",
        location,
      };
      if (item) {
        return api.updatePantryItem(item.id, {
          ...base,
          expires_on: expires || null,
          food_id: food ? food.id : null,
        });
      }
      return api.addPantryItem({
        ...base,
        ...(expires ? { expires_on: expires } : {}),
        ...(food ? { food_id: food.id } : {}),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pantry"] });
      queryClient.invalidateQueries({ queryKey: ["pantry-matches"] });
      toast(item ? "Item updated" : "Added to pantry");
      onClose();
    },
    onError: (e) => toast(e.message, "err"),
  });

  return (
    <Sheet open={open} onClose={onClose} title={item ? "Edit item" : "Add to pantry"}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (name.trim()) save.mutate(); }}>
        <Field label="Name">
          <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Chicken breast" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Quantity">
            <Input inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </Field>
          <Field label="Unit">
            <Input value={unit} onChange={(e) => setUnit(e.target.value)} placeholder="g / ml / pcs" />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Location">
            <Select value={location} onChange={(e) => setLocation(e.target.value)}>
              {LOCATIONS.map((l) => <option key={l} value={l} className="capitalize">{l}</option>)}
            </Select>
          </Field>
          <Field label="Expires on">
            <Input type="date" value={expires} onChange={(e) => setExpires(e.target.value)} />
          </Field>
        </div>

        <Field label="Link a food (optional)" hint="Connects the item to nutrition data from your food database">
          {food ? (
            <div className="flex items-center justify-between rounded-xl border border-olive/40 bg-olive-soft px-3 py-2.5 text-sm">
              <span className="font-medium text-olive">{food.name}</span>
              <button type="button" onClick={() => setFood(null)} aria-label="Unlink food" className="text-faint hover:text-bad">
                <X size={15} />
              </button>
            </div>
          ) : (
            <div className="relative">
              <Search size={15} className="absolute left-3.5 top-3.5 text-faint" />
              <Input className="pl-10" placeholder="Search foods…" value={foodQuery}
                     onChange={(e) => setFoodQuery(e.target.value)} />
            </div>
          )}
        </Field>
        {!food && foodQuery && (
          <div className="max-h-36 space-y-0.5 overflow-y-auto rounded-xl border border-line">
            {foods?.map((f: Food) => (
              <button
                type="button" key={f.id}
                onClick={() => {
                  setFood({ id: f.id, name: f.name });
                  if (!name.trim()) setName(f.name);
                  setFoodQuery("");
                }}
                className="flex w-full justify-between px-3 py-2 text-left text-sm hover:bg-surface-2"
              >
                <span>{f.name}</span>
                <span className="text-xs text-faint">{fmtNumber(f.calories)} kcal / {fmtNumber(f.serving_size)}{f.serving_unit}</span>
              </button>
            ))}
          </div>
        )}

        <Button type="submit" className="w-full" disabled={!name.trim() || save.isPending}>
          {save.isPending ? "Saving…" : item ? "Save changes" : "Add item"}
        </Button>
      </form>
    </Sheet>
  );
}
