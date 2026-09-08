"use client";

import { X } from "lucide-react";
import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
  type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import { cx } from "@/lib/utils";

// ---------- Button ----------

type ButtonVariant = "primary" | "ghost" | "outline" | "danger" | "soft";

export function Button({
  variant = "primary",
  size = "md",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: "sm" | "md" | "lg" }) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 font-medium transition-colors select-none",
        "disabled:opacity-45 disabled:pointer-events-none active:scale-[0.98]",
        size === "sm" && "h-8 px-3 text-[13px] rounded-lg",
        size === "md" && "h-10 px-4 text-sm rounded-xl",
        size === "lg" && "h-12 px-5 text-[15px] rounded-xl",
        variant === "primary" && "bg-accent text-accent-ink hover:brightness-105",
        variant === "ghost" && "text-ink hover:bg-surface-2",
        variant === "outline" && "border border-line bg-surface text-ink hover:bg-surface-2",
        variant === "soft" && "bg-accent-soft text-accent hover:brightness-97",
        variant === "danger" && "text-bad hover:bg-berry-soft",
        className
      )}
      {...props}
    />
  );
}

// ---------- Card ----------

export function Card({ className, children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("card p-4 sm:p-5", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-2">
      <h3 className="text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">{children}</h3>
      {right}
    </div>
  );
}

// ---------- Inputs ----------

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cx(
        "h-11 w-full rounded-xl border border-line bg-surface px-3.5 text-[15px] text-ink",
        "placeholder:text-faint focus:border-accent focus:outline-none transition-colors",
        className
      )}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cx(
        "w-full rounded-xl border border-line bg-surface px-3.5 py-3 text-[15px] text-ink",
        "placeholder:text-faint focus:border-accent focus:outline-none transition-colors min-h-24",
        className
      )}
      {...props}
    />
  );
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cx(
        "h-11 w-full appearance-none rounded-xl border border-line bg-surface px-3.5 text-[15px] text-ink",
        "focus:border-accent focus:outline-none transition-colors",
        className
      )}
      {...props}
    >
      {children}
    </select>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-faint">{hint}</span>}
    </label>
  );
}

// ---------- Sheet (bottom sheet on mobile, centered on desktop) ----------

export function Sheet({
  open, onClose, title, children, wide,
}: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);
  if (!mounted || !open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div
        className={cx(
          "relative w-full bg-surface border border-line shadow-2xl max-h-[88dvh] overflow-y-auto",
          "rounded-t-2xl sm:rounded-2xl p-5 sm:p-6",
          wide ? "sm:max-w-2xl" : "sm:max-w-md"
        )}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-xl font-semibold tracking-tight">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-muted hover:bg-surface-2">
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body
  );
}

// ---------- Progress ring ----------

export function ProgressRing({
  value, size = 92, stroke = 8, color = "var(--accent)", label, sub,
}: {
  value: number; size?: number; stroke?: number; color?: string; label: ReactNode; sub?: ReactNode;
}) {
  const pct = Math.max(0, Math.min(1, value));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-2)" strokeWidth={stroke} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke}
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - pct)}
          style={{ transition: "stroke-dashoffset 0.6s cubic-bezier(0.22, 1, 0.36, 1)" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
        <div className="font-display font-semibold leading-none" style={{ fontSize: size / 4.2 }}>{label}</div>
        {sub && <div className="mt-0.5 text-[10px] font-medium uppercase tracking-wide text-faint">{sub}</div>}
      </div>
    </div>
  );
}

// ---------- Progress bar ----------

export function ProgressBar({ value, color = "var(--accent)", className }: { value: number; color?: string; className?: string }) {
  return (
    <div className={cx("h-1.5 w-full overflow-hidden rounded-full bg-surface-2", className)}>
      <div
        className="h-full rounded-full transition-[width] duration-500"
        style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: color }}
      />
    </div>
  );
}

// ---------- Segmented control ----------

export function Segmented<T extends string | number>({
  options, value, onChange,
}: {
  options: { value: T; label: string }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded-xl border border-line bg-surface-2 p-1">
      {options.map((o) => (
        <button
          key={String(o.value)}
          onClick={() => onChange(o.value)}
          className={cx(
            "rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors",
            o.value === value ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ---------- Stat ----------

export function Stat({ label, value, unit, tone }: { label: string; value: ReactNode; unit?: string; tone?: string }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">{label}</div>
      <div className="mt-0.5 font-display text-2xl font-semibold tracking-tight" style={tone ? { color: tone } : undefined}>
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-muted">{unit}</span>}
      </div>
    </div>
  );
}

// ---------- Empty state ----------

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center py-10 text-center">
      <div className="font-display text-lg font-medium text-muted">{title}</div>
      {hint && <p className="mt-1 max-w-xs text-sm text-faint">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// ---------- Spinner ----------

export function Spinner({ className }: { className?: string }) {
  return (
    <div
      className={cx("h-5 w-5 animate-spin rounded-full border-2 border-line border-t-accent", className)}
      role="status" aria-label="Loading"
    />
  );
}

export function PageLoading() {
  return (
    <div className="flex h-[60dvh] items-center justify-center">
      <Spinner className="h-7 w-7" />
    </div>
  );
}

// ---------- Toast ----------

interface ToastItem { id: number; message: string; tone: "ok" | "err" }
const ToastCtx = createContext<(message: string, tone?: "ok" | "err") => void>(() => {});

export function useToast() {
  return useContext(ToastCtx);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const idRef = useRef(0);
  const push = useCallback((message: string, tone: "ok" | "err" = "ok") => {
    const id = ++idRef.current;
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 sm:bottom-6">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cx(
              "pointer-events-auto rounded-xl border px-4 py-2.5 text-sm font-medium shadow-lg",
              t.tone === "ok" ? "border-line bg-ink text-bg" : "border-bad/30 bg-bad text-white"
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
