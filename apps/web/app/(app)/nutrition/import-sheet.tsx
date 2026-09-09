"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Field, Segmented, Sheet, Spinner, Textarea, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { ImportKind, ImportPreview } from "@/lib/types";
import { fmtNumber } from "@/lib/utils";

const KINDS: { value: ImportKind; label: string }[] = [
  { value: "measurements", label: "Measurements" },
  { value: "food_logs", label: "Food logs" },
  { value: "workouts", label: "Workouts" },
];

const HINTS: Record<ImportKind, string> = {
  measurements: "CSV columns: date, value, type, unit — e.g. 2024-05-01, 81.2, weight, kg. Unknown types become custom measurements.",
  food_logs: "CSV columns: date, name, meal_type, quantity, unit, calories, protein, carbs, fat. Rows for the same date + meal are merged.",
  workouts: "CSV columns: date, exercise, title, sets, reps, weight. Rows for the same date + title become one workout.",
};

export function ImportSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [kind, setKind] = useState<ImportKind>("measurements");
  const [format, setFormat] = useState<"csv" | "json">("csv");
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const queryClient = useQueryClient();
  const toast = useToast();

  const previewMut = useMutation({
    mutationFn: () => api.importPreview({ kind, format, text }),
    onSuccess: setPreview,
    onError: (e) => toast(e.message, "err"),
  });

  const commitMut = useMutation({
    mutationFn: () => api.importCommit({ kind, rows: preview?.rows ?? [] }),
    onSuccess: (r) => {
      toast(`Imported ${fmtNumber(r.imported)}${r.skipped ? ` · skipped ${fmtNumber(r.skipped)}` : ""}`);
      queryClient.invalidateQueries();
      setText("");
      setPreview(null);
      onClose();
    },
    onError: (e) => toast(e.message, "err"),
  });

  const resetPreview = () => setPreview(null);
  const columns = preview?.rows.length ? Object.keys(preview.rows[0]) : [];

  return (
    <Sheet open={open} onClose={onClose} title="Import data" wide>
      <div className="space-y-4">
        <Field label="What are you importing?">
          <Segmented options={KINDS} value={kind} onChange={(k) => { setKind(k); resetPreview(); }} />
        </Field>

        <Field label="Format">
          <Segmented
            options={[{ value: "csv", label: "CSV" }, { value: "json", label: "JSON" }]}
            value={format}
            onChange={(f) => { setFormat(f); resetPreview(); }}
          />
        </Field>

        <Field label="Paste your data" hint={HINTS[kind]}>
          <Textarea
            className="min-h-36 font-mono text-[13px]"
            placeholder={format === "csv" ? "date,value,type,unit\n2024-05-01,81.2,weight,kg" : '[{"date": "2024-05-01", "value": 81.2, "type": "weight"}]'}
            value={text}
            onChange={(e) => { setText(e.target.value); resetPreview(); }}
          />
        </Field>

        {!preview && (
          <Button
            className="w-full"
            variant="outline"
            disabled={!text.trim() || previewMut.isPending}
            onClick={() => previewMut.mutate()}
          >
            {previewMut.isPending ? <Spinner /> : "Preview"}
          </Button>
        )}

        {preview && (
          <div className="space-y-3">
            <div className="text-sm font-medium">
              {preview.valid} of {preview.total} rows ready
              {preview.errors.length > 0 && <span className="text-bad"> · {preview.errors.length} with errors</span>}
            </div>

            {preview.errors.length > 0 && (
              <ul className="max-h-28 space-y-1 overflow-y-auto rounded-xl border border-bad/30 bg-berry-soft/40 p-3 text-xs text-bad">
                {preview.errors.slice(0, 20).map((e, i) => (
                  <li key={i}>Row {e.row || "—"}: {e.message}</li>
                ))}
                {preview.errors.length > 20 && <li>…and {preview.errors.length - 20} more</li>}
              </ul>
            )}

            {columns.length > 0 && (
              <div className="overflow-x-auto rounded-xl border border-line">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-line bg-surface-2/60">
                      {columns.map((c) => (
                        <th key={c} className="px-2.5 py-2 font-semibold uppercase tracking-wide text-faint">{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {preview.rows.slice(0, 8).map((row, i) => (
                      <tr key={i}>
                        {columns.map((c) => (
                          <td key={c} className="max-w-32 truncate px-2.5 py-1.5 text-muted">{String(row[c] ?? "")}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {preview.rows.length > 8 && (
                  <div className="border-t border-line px-2.5 py-1.5 text-[11px] text-faint">
                    …and {preview.rows.length - 8} more rows
                  </div>
                )}
              </div>
            )}

            <Button
              className="w-full"
              disabled={preview.valid === 0 || commitMut.isPending}
              onClick={() => commitMut.mutate()}
            >
              {commitMut.isPending ? "Importing…" : `Import ${preview.valid} row${preview.valid === 1 ? "" : "s"}`}
            </Button>
          </div>
        )}
      </div>
    </Sheet>
  );
}
