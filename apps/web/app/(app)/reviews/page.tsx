"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { TopBar } from "@/components/nav";
import { Button, Card, CardTitle, Empty, PageLoading, Segmented, Stat, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { Review } from "@/lib/types";
import { fmtDate, fmtDuration, fmtNumber } from "@/lib/utils";

const KINDS = [
  { value: "weekly" as const, label: "Weekly" },
  { value: "monthly" as const, label: "Monthly" },
];

export default function ReviewsPage() {
  const [kind, setKind] = useState<"weekly" | "monthly">("weekly");
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["review", kind],
    queryFn: () => (kind === "weekly" ? api.reviewWeekly() : api.reviewMonthly()),
  });

  const regen = useMutation({
    mutationFn: () => api.regenerateReview(kind),
    onSuccess: () => {
      toast("Regenerating — the fresh review lands in a few seconds.");
      // the endpoint returns the cached copy; the worker writes the new one shortly
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ["review", kind] }), 4_000);
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ["review", kind] }), 10_000);
    },
    onError: (e) => toast(e.message, "err"),
  });

  return (
    <>
      <TopBar title="Reviews" right={<Segmented options={KINDS} value={kind} onChange={setKind} />} />
      <main className="mx-auto max-w-5xl space-y-4 px-4 py-5 sm:px-6">
        {isLoading || !data ? (
          <PageLoading />
        ) : (
          <ReviewBody review={data} />
        )}

        {data && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-faint">
              {fmtDate(data.start)} – {fmtDate(data.end)} · generated {new Date(data.generated_at).toLocaleString()}
            </span>
            <Button variant="outline" size="sm" onClick={() => regen.mutate()} disabled={regen.isPending || isFetching}>
              <RefreshCw size={13} className={regen.isPending || isFetching ? "animate-spin" : ""} />
              Regenerate
            </Button>
          </div>
        )}

        <PushCard />
      </main>
    </>
  );
}

function ReviewBody({ review }: { review: Review }) {
  const d = review.data;
  const adherence = [
    { l: "Calories", v: d.calorie_adherence },
    { l: "Protein", v: d.protein_adherence },
    { l: "Habits", v: d.habit_adherence },
  ].filter((a) => a.v != null);

  return (
    <>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card className="p-4">
          <Stat label="Avg calories" value={fmtNumber(d.avg_calories)} unit="kcal/d" tone="var(--accent)" />
        </Card>
        <Card className="p-4">
          <Stat label="Avg protein" value={fmtNumber(d.avg_protein)} unit="g/d" tone="var(--olive)" />
        </Card>
        <Card className="p-4">
          <Stat label="Avg sleep" value={fmtDuration(d.avg_sleep_minutes)} tone="var(--berry)" />
        </Card>
        <Card className="p-4">
          <Stat label="Workouts" value={d.workout_count} unit={`/ ${d.days}d`} tone="var(--lake)" />
        </Card>
      </div>

      {adherence.length > 0 && (
        <Card>
          <CardTitle>Adherence</CardTitle>
          <div className="grid grid-cols-3 gap-3 text-center">
            {adherence.map((a) => (
              <div key={a.l}>
                <div className="font-display text-3xl font-semibold">{Math.round((a.v ?? 0) * 100)}%</div>
                <div className="mt-0.5 text-[11px] font-semibold uppercase tracking-wide text-faint">{a.l}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card>
        <CardTitle>AI review</CardTitle>
        {review.narrative ? (
          <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-ink">{review.narrative}</p>
        ) : (
          <Empty title="No narrative yet" hint="Regenerate to write a review with your selected AI provider." />
        )}
      </Card>
    </>
  );
}

// ---------- push notifications ----------

function b64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function PushCard() {
  const toast = useToast();
  const [supported] = useState(
    () => typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window
  );
  const [subscribed, setSubscribed] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!supported) return;
    navigator.serviceWorker
      .getRegistration()
      .then(async (reg) => setSubscribed(!!(await reg?.pushManager.getSubscription())))
      .catch(() => setSubscribed(false));
  }, [supported]);

  async function enable() {
    setBusy(true);
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") throw new Error("Notification permission was not granted.");
      let reg = await navigator.serviceWorker.getRegistration();
      if (!reg) reg = await navigator.serviceWorker.register("/sw.js");
      const { publicKey } = await api.pushVapidKey();
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: b64ToUint8Array(publicKey),
      });
      const keys = sub.toJSON().keys as { p256dh: string; auth: string };
      await api.pushSubscribe({ endpoint: sub.endpoint, keys: { p256dh: keys.p256dh, auth: keys.auth } });
      setSubscribed(true);
      toast("Push reminders enabled on this device.");
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setBusy(true);
    try {
      const reg = await navigator.serviceWorker.getRegistration();
      const sub = await reg?.pushManager.getSubscription();
      if (sub) {
        await api.pushUnsubscribe(sub.endpoint).catch(() => {});
        await sub.unsubscribe().catch(() => {});
      }
      setSubscribed(false);
      toast("Push reminders disabled.");
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    try {
      const { sent } = await api.pushTest();
      toast(sent ? `Test notification sent to ${sent} device(s).` : "Nothing delivered — re-enable push and retry.",
            sent ? "ok" : "err");
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardTitle
        right={
          subscribed ? (
            <span className="flex items-center gap-1 text-[11px] font-semibold normal-case tracking-normal text-good">
              <BellRing size={12} /> on
            </span>
          ) : undefined
        }
      >
        Push
      </CardTitle>
      <p className="text-sm text-muted">
        Get a heads-up on this device when a scheduled event is about to start.
      </p>
      <div className="mt-3 flex items-center gap-2">
        {!supported ? (
          <span className="text-sm text-faint">This browser doesn&apos;t support web push.</span>
        ) : subscribed === null ? (
          <span className="text-sm text-faint">Checking…</span>
        ) : subscribed ? (
          <>
            <Button variant="outline" size="sm" onClick={test} disabled={busy}>
              Send test
            </Button>
            <Button variant="ghost" size="sm" onClick={disable} disabled={busy}>
              Disable
            </Button>
          </>
        ) : (
          <Button size="sm" onClick={enable} disabled={busy}>
            Enable push
          </Button>
        )}
      </div>
    </Card>
  );
}
