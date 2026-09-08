"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Input, Field } from "@/components/ui";
import { api } from "@/lib/api";
import { AuthShell } from "@/components/auth-shell";

export default function SignupPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.signup({ email, password, name });
      router.replace("/onboarding");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
      setBusy(false);
    }
  }

  return (
    <AuthShell
      aside={
        <div className="max-w-md space-y-8">
          <p className="font-display text-4xl font-medium leading-[1.15] tracking-tight">
            “An AI that knows your goals, your schedule, and what you actually did.”
          </p>
          <ul className="space-y-3 text-sm text-bg/70">
            <li>— Describe your life in one sentence; get a full plan.</li>
            <li>— Log food, water, workouts and sleep in seconds.</li>
            <li>— Watch trends, not noise.</li>
          </ul>
        </div>
      }
    >
      <h1 className="font-display text-3xl font-semibold tracking-tight">Create your account</h1>
      <p className="mt-1 text-sm text-muted">Self-hosted. Your data stays yours.</p>
      <form onSubmit={submit} className="mt-8 space-y-4">
        <Field label="Name">
          <Input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" />
        </Field>
        <Field label="Email">
          <Input type="email" required autoComplete="email" value={email}
                 onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </Field>
        <Field label="Password" hint="At least 8 characters">
          <Input type="password" required minLength={8} autoComplete="new-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
        </Field>
        {error && <p className="text-sm font-medium text-bad">{error}</p>}
        <Button type="submit" size="lg" className="w-full" disabled={busy}>
          {busy ? "Creating…" : "Create account"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        Already have an account?{" "}
        <Link href="/login" className="font-semibold text-accent hover:underline">
          Log in
        </Link>
      </p>
    </AuthShell>
  );
}
