"use client";

import { useEffect, useState } from "react";
import { Card, CardTitle } from "@/components/ui";
import { cx } from "@/lib/utils";

const FONTS = [
  {
    id: "editorial",
    label: "Editorial",
    desc: "Fraunces serif display + Inter",
    sample: "font-display",
  },
  {
    id: "athletic",
    label: "Athletic",
    desc: "Space Grotesk everywhere",
    sample: "font-[var(--font-space-grotesk)]",
  },
  {
    id: "system",
    label: "System",
    desc: "Native — fastest, zero download",
    sample: "font-sans",
  },
  {
    id: "readable",
    label: "Readable",
    desc: "Atkinson Hyperlegible — max legibility",
    sample: "font-[var(--font-atkinson)]",
  },
] as const;

export function FontPicker() {
  const [font, setFont] = useState<string>("editorial");
  useEffect(() => {
    setFont(document.documentElement.dataset.font || "editorial");
  }, []);

  return (
    <div className="grid grid-cols-2 gap-2">
      {FONTS.map((f) => (
        <button
          key={f.id}
          type="button"
          onClick={() => {
            document.documentElement.dataset.font = f.id === "editorial" ? "" : f.id;
            if (f.id === "editorial") delete document.documentElement.dataset.font;
            localStorage.setItem("healthos-font", f.id === "editorial" ? "" : f.id);
            setFont(f.id);
          }}
          className={cx(
            "rounded-xl border p-3.5 text-left transition-colors",
            font === f.id ? "border-accent bg-accent-soft" : "border-line hover:bg-surface-2"
          )}
        >
          <div className={cx("font-display text-2xl font-semibold leading-none", f.id !== "editorial" && f.sample)}
               style={f.id === "athletic" ? { fontFamily: "var(--font-space-grotesk)" }
                    : f.id === "readable" ? { fontFamily: "var(--font-atkinson)" }
                    : f.id === "system" ? { fontFamily: "ui-serif, Georgia, serif" } : undefined}>
            Ag 84.2
          </div>
          <div className={cx("mt-1.5 text-[13px] font-semibold", font === f.id ? "text-accent" : "text-ink")}>
            {f.label}
          </div>
          <div className="text-[11px] leading-snug text-faint">{f.desc}</div>
        </button>
      ))}
    </div>
  );
}

export function AppearanceCard({ right }: { right?: React.ReactNode }) {
  return (
    <Card>
      <CardTitle right={right}>Appearance</CardTitle>
      <div className="mb-2 text-[13px] font-medium text-muted">Typeface</div>
      <FontPicker />
    </Card>
  );
}
