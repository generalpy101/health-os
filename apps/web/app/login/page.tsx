"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Input, Field } from "@/components/ui";
import { AuthShell } from "@/components/auth-shell";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.login({ email, password });
      router.replace("/today");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
      setBusy(false);
    }
  }

  return (
    <AuthShell
      aside={
        <blockquote className="max-w-md">
          <p className="font-display text-4xl font-medium leading-[1.15] tracking-tight">
            “Know what to do today. See how far you&rsquo;ve come.”
          </p>
          <footer className="mt-6 text-sm text-bg/60">
            Goals, nutrition, training, sleep and habits — one system that learns your life.
          </footer>
        </blockquote>
      }
    >
      <h1 className="font-display text-3xl font-semibold tracking-tight">Welcome back</h1>
      <p className="mt-1 text-sm text-muted">Log in to your health system.</p>
      <form onSubmit={submit} className="mt-8 space-y-4">
        <Field label="Email">
          <Input type="email" required autoComplete="email" value={email}
                 onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </Field>
        <Field label="Password">
          <Input type="password" required autoComplete="current-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
        </Field>
        {error && <p className="text-sm font-medium text-bad">{error}</p>}
        <Button type="submit" size="lg" className="w-full" disabled={busy}>
          {busy ? "Logging in…" : "Log in"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        No account?{" "}
        <Link href="/signup" className="font-semibold text-accent hover:underline">
          Create one
        </Link>
      </p>
    </AuthShell>
  );
}
