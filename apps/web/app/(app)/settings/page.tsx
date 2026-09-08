"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Moon, Sun, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { TopBar } from "@/components/nav";
import { ProviderPicker, useAiProviders, useAiSettings } from "@/components/ai-picker";
import { Button, Card, CardTitle, Field, Input, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { GOAL_TYPES, cx } from "@/lib/utils";

const TARGET_DEFS = [
  { key: "calories", label: "Calories", unit: "kcal", period: "daily" },
  { key: "protein", label: "Protein", unit: "g", period: "daily" },
  { key: "water", label: "Water", unit: "ml", period: "daily" },
  { key: "steps", label: "Steps", unit: "steps", period: "daily" },
  { key: "sleep_minutes", label: "Sleep", unit: "min", period: "daily" },
  { key: "workouts", label: "Workouts", unit: "sessions", period: "weekly" },
];

export default function SettingsPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const { data: profile } = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const { data: targets } = useQuery({ queryKey: ["targets"], queryFn: api.targets });
  const { data: goals } = useQuery({ queryKey: ["goals"], queryFn: () => api.goals("active") });
  const { data: memories } = useQuery({ queryKey: ["memories"], queryFn: api.memories });

  const [theme, setTheme] = useState<string>("light");
  useEffect(() => {
    setTheme(document.documentElement.dataset.theme || "light");
  }, []);
  const switchTheme = (t: string) => {
    document.documentElement.dataset.theme = t;
    localStorage.setItem("healthos-theme", t);
    setTheme(t);
  };

  const saveMe = useMutation({
    mutationFn: api.updateMe,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["me"] }); toast("Saved"); },
    onError: (e) => toast(e.message, "err"),
  });
  const saveProfile = useMutation({
    mutationFn: api.updateProfile,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["profile"] }); toast("Profile saved"); },
    onError: (e) => toast(e.message, "err"),
  });
  const addTarget = useMutation({
    mutationFn: api.createTarget,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["targets"] }); toast("Target set"); },
    onError: (e) => toast(e.message, "err"),
  });
  const removeTarget = useMutation({
    mutationFn: api.deleteTarget,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["targets"] }),
  });
  const addGoal = useMutation({
    mutationFn: api.createGoal,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["goals"] }); toast("Goal added"); },
    onError: (e) => toast(e.message, "err"),
  });
  const removeGoal = useMutation({
    mutationFn: api.deleteGoal,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["goals"] }),
  });
  const removeMemory = useMutation({
    mutationFn: api.deleteMemory,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["memories"] }),
  });

  const [newGoal, setNewGoal] = useState({ type: "custom", title: "", target_value: "", unit: "kg" });

  return (
    <>
      <TopBar
        title="Settings"
        right={
          <button
            onClick={() => switchTheme(theme === "dark" ? "light" : "dark")}
            aria-label="Toggle theme"
            className="rounded-xl border border-line bg-surface p-2.5 text-muted hover:text-ink"
          >
            {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
          </button>
        }
      />
      <main className="mx-auto max-w-3xl space-y-4 px-4 py-5 sm:px-6">
        <Card>
          <CardTitle>Profile</CardTitle>
          {me && profile && (
            <form
              className="grid grid-cols-2 gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                const fd = new FormData(e.currentTarget);
                saveMe.mutate({
                  name: String(fd.get("name") || ""),
                  timezone: String(fd.get("timezone") || "UTC"),
                  units: String(fd.get("units") || "metric") as "metric" | "imperial",
                });
                saveProfile.mutate({
                  height_cm: parseFloat(String(fd.get("height"))) || null,
                  activity_level: String(fd.get("activity") || "") || null,
                });
              }}
            >
              <Field label="Name"><Input name="name" defaultValue={me.name} /></Field>
              <Field label="Timezone" hint="Used for all daily totals">
                <Input name="timezone" defaultValue={me.timezone} placeholder="Asia/Kolkata" />
              </Field>
              <Field label="Height (cm)"><Input name="height" inputMode="decimal" defaultValue={profile.height_cm ?? ""} /></Field>
              <Field label="Activity level">
                <Select name="activity" defaultValue={profile.activity_level || "moderate"}>
                  {["sedentary", "light", "moderate", "active", "very_active"].map((a) => (
                    <option key={a} value={a}>{a.replace("_", " ")}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Units">
                <Select name="units" defaultValue={me.units}>
                  <option value="metric">Metric (kg, cm, ml)</option>
                  <option value="imperial">Imperial (lb, in, oz)</option>
                </Select>
              </Field>
              <div className="col-span-2">
                <Button type="submit" disabled={saveMe.isPending}>Save profile</Button>
              </div>
            </form>
          )}
        </Card>

        <Card>
          <CardTitle>Daily targets</CardTitle>
          <div className="space-y-2">
            {targets?.map((t) => (
              <div key={t.id} className="flex items-center justify-between rounded-xl border border-line px-3.5 py-2.5">
                <span className="text-sm font-medium capitalize">{t.key.replaceAll("_", " ")}</span>
                <span className="flex items-center gap-3 text-sm text-muted">
                  {t.value} {t.unit} / {t.period.replace("ly", "")}
                  <button onClick={() => removeTarget.mutate(t.id)} aria-label="Remove" className="text-faint hover:text-bad">
                    <Trash2 size={14} />
                  </button>
                </span>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {TARGET_DEFS.filter((d) => !targets?.find((t) => t.key === d.key)).map((d) => (
              <TargetAdder key={d.key} label={d.label} unit={d.unit} period={d.period} targetKey={d.key}
                           onAdd={(value) => addTarget.mutate({ key: d.key, value, unit: d.unit, period: d.period })} />
            ))}
          </div>
        </Card>

        <Card>
          <CardTitle>Goals</CardTitle>
          <div className="space-y-2">
            {goals?.map((g) => (
              <div key={g.id} className="flex items-center justify-between rounded-xl border border-line px-3.5 py-2.5">
                <div>
                  <span className="text-sm font-medium">{g.title}</span>
                  <span className="ml-2 rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] font-medium text-muted">
                    {g.type.replaceAll("_", " ")}
                  </span>
                </div>
                <span className="flex items-center gap-3 text-sm text-muted">
                  {g.target_value != null && `${g.target_value} ${g.unit || ""}`}
                  <button onClick={() => removeGoal.mutate(g.id)} aria-label="Archive" className="text-faint hover:text-bad">
                    <Trash2 size={14} />
                  </button>
                </span>
              </div>
            ))}
          </div>
          <form
            className="mt-3 grid grid-cols-[1fr_auto_auto_auto] items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!newGoal.title.trim()) return;
              addGoal.mutate({
                type: newGoal.type, title: newGoal.title,
                ...(newGoal.target_value ? { target_value: parseFloat(newGoal.target_value), unit: newGoal.unit } : {}),
              });
              setNewGoal({ ...newGoal, title: "", target_value: "" });
            }}
          >
            <Input placeholder="New goal…" value={newGoal.title} onChange={(e) => setNewGoal({ ...newGoal, title: e.target.value })} />
            <Select value={newGoal.type} onChange={(e) => setNewGoal({ ...newGoal, type: e.target.value })} className="w-auto">
              {GOAL_TYPES.map((t) => <option key={t} value={t}>{t.replaceAll("_", " ")}</option>)}
            </Select>
            <Input placeholder="Target" inputMode="decimal" className="w-24" value={newGoal.target_value}
                   onChange={(e) => setNewGoal({ ...newGoal, target_value: e.target.value })} />
            <Button type="submit" variant="outline">Add</Button>
          </form>
        </Card>

        <AISettingsCard />

        <Card>
          <CardTitle>What the AI remembers</CardTitle>
          {!memories?.length ? (
            <p className="text-sm text-faint">Nothing yet. Tell the assistant things like “I don&rsquo;t eat seafood” and they show up here.</p>
          ) : (
            <ul className="divide-y divide-line">
              {memories.map((m) => (
                <li key={m.id} className="flex items-center justify-between py-2.5 text-sm">
                  <span>
                    <span className="font-medium">{m.key.replaceAll("_", " ")}</span>
                    <span className="text-muted"> — {String(m.value?.value ?? "")}</span>
                    <span className="ml-2 text-[11px] text-faint">{m.type} · {Math.round(m.confidence * 100)}%</span>
                  </span>
                  <button onClick={() => removeMemory.mutate(m.id)} aria-label="Forget" className="text-faint hover:text-bad">
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </main>
    </>
  );
}

function AISettingsCard() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const providers = useAiProviders();
  const settings = useAiSettings();
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [testResult, setTestResult] = useState<{ ok: boolean; latency_ms?: number; error?: string; reply?: string } | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    if (settings.provider !== undefined && !provider) {
      setProvider(settings.provider || "mock");
      setModel(settings.model || "");
      setBaseUrl(settings.base_url || "");
    }
  }, [settings, provider]);

  const preset = providers.find((p) => p.id === (provider || "mock"));
  const showUrl = preset?.kind === "openai_compatible";

  const save = useMutation({
    mutationFn: () =>
      api.updateAiSettings({
        provider: provider || "mock",
        model: model || undefined,
        base_url: showUrl ? baseUrl || undefined : undefined,
        ...(apiKey ? { api_key: apiKey } : {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ai-settings"] });
      toast("AI settings saved");
      setApiKey("");
    },
    onError: (e) => toast(e.message, "err"),
  });

  async function test() {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.testAiProvider({
        provider: provider || "mock",
        model: model || undefined,
        base_url: showUrl ? baseUrl || undefined : undefined,
        ...(apiKey ? { api_key: apiKey } : {}),
      });
      setTestResult(res);
    } catch (e) {
      setTestResult({ ok: false, error: e instanceof Error ? e.message : "failed" });
    } finally {
      setTesting(false);
    }
  }

  return (
    <Card className="scroll-mt-20" id="ai">
      <CardTitle>AI provider</CardTitle>
      <div className="space-y-3">
        <Field label="Provider" hint="Local options keep your health data on this machine.">
          <Select
            value={provider || "mock"}
            onChange={(e) => {
              const p = providers.find((x) => x.id === e.target.value);
              setProvider(e.target.value);
              setModel(p?.default_model || "");
              setBaseUrl(p?.default_base_url || "");
              setTestResult(null);
            }}
          >
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}{p.detected ? "" : " (not detected)"}
              </option>
            ))}
          </Select>
        </Field>
        {preset?.hint && (
          <p className="-mt-1 text-xs leading-relaxed text-faint">{preset.hint}</p>
        )}
        {preset && preset.kind !== "mock" && (
          <Field label={preset.kind === "cli" ? "Model (optional — CLI default if empty)" : "Model"}>
            <Input value={model} onChange={(e) => setModel(e.target.value)}
                   placeholder={preset.default_model || "model name"} />
          </Field>
        )}
        {showUrl && (
          <Field label="Base URL">
            <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}
                   placeholder={preset?.default_base_url || "http://localhost:11434/v1"} />
          </Field>
        )}
        {preset?.needs_key && (
          <Field label="API key" hint={settings.has_api_key ? "A key is saved — leave empty to keep it" : "Stored server-side, never sent to the browser"}>
            <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                   placeholder={settings.has_api_key ? "••••••••" : "sk-…"} autoComplete="off" />
          </Field>
        )}
        <div className="flex items-center gap-2">
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
          <Button variant="outline" onClick={test} disabled={testing}>
            {testing ? "Testing…" : "Test connection"}
          </Button>
        </div>
        {testResult && (
          <div className={cx(
            "rounded-xl border px-3.5 py-2.5 text-sm",
            testResult.ok ? "border-good/40 bg-olive-soft text-good" : "border-bad/40 bg-berry-soft text-bad"
          )}>
            {testResult.ok
              ? `Connected${testResult.latency_ms != null ? ` in ${testResult.latency_ms}ms` : ""}${testResult.reply ? ` — “${testResult.reply}”` : ""}`
              : `Failed: ${testResult.error}`}
          </div>
        )}
      </div>
    </Card>
  );
}

function TargetAdder({ label, unit, period, targetKey, onAdd }: {
  label: string; unit: string; period: string; targetKey: string;
  onAdd: (value: number) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState("");
  if (!editing) {
    return (
      <button onClick={() => setEditing(true)}
              className="rounded-lg border border-dashed border-line px-3 py-1.5 text-[13px] font-medium text-muted hover:border-accent hover:text-accent">
        + {label}
      </button>
    );
  }
  return (
    <form
      className="flex items-center gap-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        const n = parseFloat(v);
        if (n > 0) onAdd(n);
        setEditing(false); setV("");
      }}
    >
      <Input autoFocus inputMode="decimal" className="h-9 w-28" placeholder={`${label} (${unit})`} value={v} onChange={(e) => setV(e.target.value)} />
      <Button size="sm" type="submit">Set</Button>
      <button type="button" onClick={() => setEditing(false)} className={cx("p-1 text-faint hover:text-ink")}>✕</button>
    </form>
  );
}
