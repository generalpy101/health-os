"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { TopBar } from "@/components/nav";
import { Button, Card, CardTitle, Empty, PageLoading, Segmented, Stat, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, fmtDuration, fmtNumber } from "@/lib/utils";

const RANGES = [
  { value: 7, label: "7D" },
  { value: 30, label: "30D" },
  { value: 90, label: "90D" },
];

export default function ProgressPage() {
  const [days, setDays] = useState(30);
  const { data, isLoading } = useQuery({ queryKey: ["range", days], queryFn: () => api.rangeSummary(days) });

  return (
    <>
      <TopBar title="Progress" right={<Segmented options={RANGES} value={days} onChange={setDays} />} />
      <main className="mx-auto max-w-5xl space-y-4 px-4 py-5 sm:px-6">
        {isLoading || !data ? (
          <PageLoading />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Card className="p-4">
                <Stat label="Avg calories" value={fmtNumber(data.avg_calories)} unit="kcal/d" tone="var(--accent)" />
              </Card>
              <Card className="p-4">
                <Stat label="Avg protein" value={fmtNumber(data.avg_protein)} unit="g/d" tone="var(--olive)" />
              </Card>
              <Card className="p-4">
                <Stat label="Avg sleep" value={fmtDuration(data.avg_sleep_minutes)} tone="var(--berry)" />
              </Card>
              <Card className="p-4">
                <Stat label="Workouts" value={data.workout_count} unit={`/ ${data.days}d`} tone="var(--lake)" />
              </Card>
            </div>

            {(data.calorie_adherence != null || data.protein_adherence != null || data.habit_adherence != null) && (
              <Card>
                <CardTitle>Adherence</CardTitle>
                <div className="grid grid-cols-3 gap-3 text-center">
                  {[
                    { l: "Calories", v: data.calorie_adherence },
                    { l: "Protein", v: data.protein_adherence },
                    { l: "Habits", v: data.habit_adherence },
                  ].filter((a) => a.v != null).map((a) => (
                    <div key={a.l}>
                      <div className="font-display text-3xl font-semibold">{Math.round((a.v ?? 0) * 100)}%</div>
                      <div className="mt-0.5 text-[11px] font-semibold uppercase tracking-wide text-faint">{a.l}</div>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            <Card>
              <CardTitle
                right={
                  data.weight.weekly_rate != null ? (
                    <span className="text-xs normal-case tracking-normal text-muted">
                      {data.weight.weekly_rate > 0 ? "+" : ""}{data.weight.weekly_rate.toFixed(2)} kg/wk
                    </span>
                  ) : undefined
                }
              >
                Weight trend
              </CardTitle>
              {data.weight.points.length === 0 ? (
                <Empty title="No weight data" hint="Log your weight daily to see the trend and 7-day average." />
              ) : (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart
                      data={data.weight.points.map((p) => ({
                        ...p,
                        ma: data.weight.moving_average.find((m) => m.date === p.date)?.value,
                      }))}
                      margin={{ top: 8, right: 8, bottom: 0, left: -16 }}
                    >
                      <CartesianGrid stroke="var(--line)" strokeDasharray="2 6" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fontSize: 11, fill: "var(--faint)" }}
                             tickLine={false} axisLine={false} minTickGap={40} />
                      <YAxis domain={["dataMin - 1", "dataMax + 1"]} tick={{ fontSize: 11, fill: "var(--faint)" }}
                             tickLine={false} axisLine={false} />
                      <Tooltip content={<ChartTip unit="kg" />} />
                      <Line type="monotone" dataKey="value" stroke="var(--faint)" strokeWidth={1.5}
                            dot={{ r: 2.5, fill: "var(--faint)", strokeWidth: 0 }} name="Weight" />
                      <Line type="monotone" dataKey="ma" stroke="var(--accent)" strokeWidth={2.5}
                            dot={false} name="7-day average" />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              )}
              <div className="mt-2 flex gap-4 text-[11px] text-faint">
                <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded bg-faint" /> Daily</span>
                <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded bg-accent" /> 7-day average</span>
              </div>
            </Card>

            <MeasurementExplorer />

            <Card>
              <CardTitle>Nutrition by day</CardTitle>
              {data.daily_calories.length === 0 ? (
                <Empty title="No food logged" hint="Log meals to see daily calories and protein." />
              ) : (
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data.daily_calories} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                      <CartesianGrid stroke="var(--line)" strokeDasharray="2 6" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fontSize: 11, fill: "var(--faint)" }}
                             tickLine={false} axisLine={false} minTickGap={40} />
                      <YAxis tick={{ fontSize: 11, fill: "var(--faint)" }} tickLine={false} axisLine={false} />
                      <Tooltip content={<ChartTip unit="kcal" />} cursor={{ fill: "var(--surface-2)" }} />
                      <Bar dataKey="calories" fill="var(--accent)" radius={[5, 5, 0, 0]} maxBarSize={26} name="Calories" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>
          </>
        )}
      </main>
    </>
  );
}

function ChartTip({ active, payload, label, unit }: { active?: boolean; payload?: { name: string; value: number }[]; label?: string; unit: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-line bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-semibold">{label ? fmtDate(label) : ""}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex justify-between gap-4 text-muted">
          <span>{p.name}</span>
          <span className="font-semibold text-ink">{fmtNumber(p.value, 1)} {unit}</span>
        </div>
      ))}
    </div>
  );
}

const MEASURE_TYPES = ["weight", "body_fat", "waist", "chest", "arms", "hips", "neck"];

function MeasurementExplorer() {
  const [type, setType] = useState("weight");
  const { data } = useQuery({
    queryKey: ["measurements", type],
    queryFn: () => api.measurements(type, 180),
  });
  const [uploading, setUploading] = useState(false);
  const queryClient = useQueryClient();
  const { data: photos } = useQuery({ queryKey: ["photos", "progress"], queryFn: () => api.photos("progress") });
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);

  const points = (data || []).map((m) => ({ date: m.date, value: m.value }));
  const unit = data?.[0]?.unit || (type === "body_fat" ? "%" : type === "weight" ? "kg" : "cm");

  return (
    <>
      <Card>
        <CardTitle
          right={
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="rounded-lg border border-line bg-surface px-2 py-1 text-xs font-medium capitalize text-muted focus:outline-none"
            >
              {MEASURE_TYPES.map((t) => <option key={t} value={t}>{t.replace("_", " ")}</option>)}
            </select>
          }
        >
          Measurements
        </CardTitle>
        {points.length === 0 ? (
          <Empty title={`No ${type.replace("_", " ")} data`} hint="Log measurements from the + button." />
        ) : (
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                <CartesianGrid stroke="var(--line)" strokeDasharray="2 6" vertical={false} />
                <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fontSize: 11, fill: "var(--faint)" }} tickLine={false} axisLine={false} minTickGap={40} />
                <YAxis domain={["dataMin", "dataMax"]} tick={{ fontSize: 11, fill: "var(--faint)" }} tickLine={false} axisLine={false} width={44} />
                <Tooltip content={<ChartTip unit={unit} />} />
                <Line type="monotone" dataKey="value" stroke="var(--lake)" strokeWidth={2} dot={{ r: 2.5, fill: "var(--lake)", strokeWidth: 0 }} name={type} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      <Card>
        <CardTitle
          right={
            <>
              <input
                ref={fileRef} type="file" accept="image/*" className="hidden"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  setUploading(true);
                  try {
                    await api.uploadPhoto(file, "progress");
                    queryClient.invalidateQueries({ queryKey: ["photos"] });
                    toast("Photo added");
                  } catch (err) {
                    toast(err instanceof Error ? err.message : "Upload failed", "err");
                  } finally {
                    setUploading(false);
                    e.target.value = "";
                  }
                }}
              />
              <Button size="sm" variant="outline" disabled={uploading} onClick={() => fileRef.current?.click()}>
                {uploading ? "Uploading…" : "+ Photo"}
              </Button>
            </>
          }
        >
          Progress photos
        </CardTitle>
        {!photos?.length ? (
          <p className="text-sm text-faint">Add a photo monthly — trends you can see beat numbers you can imagine.</p>
        ) : (
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
            {photos.map((p) => (
              <a key={p.id} href={api.photoUrl(p.id)} target="_blank" rel="noreferrer" className="group relative">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={api.photoUrl(p.id)} alt={p.notes || "Progress photo"}
                     className="aspect-square w-full rounded-xl border border-line object-cover" />
                <span className="absolute bottom-1 left-1 rounded-md bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-white">
                  {p.date ? fmtDate(p.date) : ""}
                </span>
              </a>
            ))}
          </div>
        )}
      </Card>
    </>
  );
}
