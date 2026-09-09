"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Button, Field, Input, Sheet, useToast } from "@/components/ui";
import { api } from "@/lib/api";

/** Register a food from its package label — user foods always win over the
    generic database and over barcode lookups for the same barcode. */
export function AddFoodSheet({ open, onClose, prefill }: {
  open: boolean; onClose: () => void;
  prefill?: { name?: string; barcode?: string } | null;
}) {
  const [name, setName] = useState("");
  const [brand, setBrand] = useState("");
  const [barcode, setBarcode] = useState("");
  const [servingSize, setServingSize] = useState("100");
  const [servingUnit, setServingUnit] = useState("g");
  const [calories, setCalories] = useState("");
  const [protein, setProtein] = useState("");
  const [carbs, setCarbs] = useState("");
  const [fat, setFat] = useState("");
  const queryClient = useQueryClient();
  const toast = useToast();

  useEffect(() => {
    if (open) {
      setName(prefill?.name || "");
      setBarcode(prefill?.barcode || "");
    }
  }, [open, prefill]);

  const save = useMutation({
    mutationFn: () =>
      api.createFood({
        name: name.trim(),
        brand: brand.trim() || null,
        barcode: barcode.trim() || null,
        serving_size: parseFloat(servingSize) || 100,
        serving_unit: servingUnit,
        calories: parseFloat(calories) || 0,
        protein: parseFloat(protein) || 0,
        carbs: parseFloat(carbs) || 0,
        fat: parseFloat(fat) || 0,
      }),
    onSuccess: (f) => {
      queryClient.invalidateQueries({ queryKey: ["foods"] });
      toast(`${f.name} saved — your label wins from now on`);
      setName(""); setBrand(""); setBarcode(""); setCalories(""); setProtein(""); setCarbs(""); setFat("");
      onClose();
    },
    onError: (e) => toast(e.message, "err"),
  });

  const num = (v: string) => parseFloat(v) || 0;
  return (
    <Sheet open={open} onClose={onClose} title="Add food from its label">
      <form className="space-y-3.5" onSubmit={(e) => { e.preventDefault(); if (name.trim() && calories) save.mutate(); }}>
        <p className="text-xs leading-relaxed text-faint">
          Package labels are the source of truth. This saves as <em>your</em> food — it outranks the
          generic database, and if you add a barcode, it wins every future scan of that pack.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Name"><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Chicken breast (my pack)" /></Field>
          <Field label="Brand (optional)"><Input value={brand} onChange={(e) => setBrand(e.target.value)} placeholder="Brand" /></Field>
          <Field label="Barcode (optional)"><Input inputMode="numeric" value={barcode} onChange={(e) => setBarcode(e.target.value)} placeholder="8901234567890" /></Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Serving size"><Input inputMode="decimal" value={servingSize} onChange={(e) => setServingSize(e.target.value)} /></Field>
            <Field label="Unit">
              <select value={servingUnit} onChange={(e) => setServingUnit(e.target.value)}
                      className="h-11 w-full rounded-xl border border-line bg-surface px-3 text-[15px] focus:border-accent focus:outline-none">
                <option value="g">g</option><option value="ml">ml</option>
                <option value="piece">piece</option><option value="serving">serving</option>
              </select>
            </Field>
          </div>
        </div>
        <div className="rounded-xl border border-line p-3">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-faint">
            Per {servingSize || "100"}{servingUnit}
          </div>
          <div className="grid grid-cols-4 gap-2">
            <Field label="kcal*"><Input inputMode="decimal" value={calories} onChange={(e) => setCalories(e.target.value)} placeholder="109" /></Field>
            <Field label="Protein"><Input inputMode="decimal" value={protein} onChange={(e) => setProtein(e.target.value)} placeholder="21.9" /></Field>
            <Field label="Carbs"><Input inputMode="decimal" value={carbs} onChange={(e) => setCarbs(e.target.value)} placeholder="0" /></Field>
            <Field label="Fat"><Input inputMode="decimal" value={fat} onChange={(e) => setFat(e.target.value)} placeholder="1.5" /></Field>
          </div>
        </div>
        <Button type="submit" className="w-full" disabled={!name.trim() || !calories || save.isPending}>
          {save.isPending ? "Saving…" : "Save my food"}
        </Button>
      </form>
    </Sheet>
  );
}
