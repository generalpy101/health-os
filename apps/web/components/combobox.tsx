"use client";

import { Check, ChevronDown, RefreshCw, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { cx } from "@/lib/utils";

/** Styled, searchable combobox: free text allowed, suggestion list, keyboard nav. */
export function ComboBox({
  value,
  onChange,
  options,
  placeholder,
  onRefresh,
  refreshing,
  note,
  defaultOption,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
  placeholder?: string;
  onRefresh?: () => void;
  refreshing?: boolean;
  note?: string;
  defaultOption?: string; // rendered as first row; picking it sets value to ""
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState<string | null>(null); // null = closed/committed value
  const [highlight, setHighlight] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    const q = (query ?? "").toLowerCase().trim();
    const base = !q ? options : options.filter((o) => o.toLowerCase().includes(q));
    if (defaultOption && (!q || defaultOption.toLowerCase().includes(q) || "default".includes(q))) {
      return [defaultOption, ...base];
    }
    return base;
  }, [options, query, defaultOption]);

  const displayValue = value === "" && defaultOption ? defaultOption : value;

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery(null);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  useEffect(() => {
    if (open) listRef.current?.children[highlight]?.scrollIntoView({ block: "nearest" });
  }, [highlight, open]);

  function pick(v: string) {
    onChange(v);
    setQuery(null);
    setOpen(false);
  }

  return (
    <div className="relative" ref={rootRef}>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search size={15} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-faint" />
          <input
            value={query ?? displayValue}
            onFocus={() => { setOpen(true); setQuery(""); setHighlight(0); }}
            onChange={(e) => {
              setQuery(e.target.value);
              onChange(e.target.value); // free text commits immediately
              setOpen(true);
              setHighlight(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setHighlight((h) => Math.min(h + 1, filtered.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setHighlight((h) => Math.max(h - 1, 0)); }
              if (e.key === "Enter") {
                e.preventDefault();
                if (open && filtered[highlight]) pick(filtered[highlight]);
                else setOpen(false);
              }
              if (e.key === "Escape") { setOpen(false); setQuery(null); }
            }}
            placeholder={placeholder}
            autoComplete="off"
            spellCheck={false}
            className="h-11 w-full rounded-xl border border-line bg-surface pl-10 pr-9 text-[15px] text-ink placeholder:text-faint focus:border-accent focus:outline-none"
            role="combobox" aria-expanded={open} aria-autocomplete="list"
          />
          <button
            type="button"
            aria-label={open ? "Close list" : "Open list"}
            onClick={() => { setOpen(!open); setQuery(open ? null : ""); setHighlight(0); }}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-faint hover:text-ink"
          >
            <ChevronDown size={15} className={cx("transition-transform", open && "rotate-180")} />
          </button>
        </div>
        {onRefresh && (
          <button
            type="button" onClick={onRefresh} disabled={refreshing}
            title="Re-discover models" aria-label="Re-discover models"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-line bg-surface text-muted transition-colors hover:text-ink disabled:opacity-50"
          >
            <RefreshCw size={15} className={refreshing ? "animate-spin" : ""} />
          </button>
        )}
      </div>

      {open && (
        <div className="absolute left-0 right-0 top-12 z-50 overflow-hidden rounded-xl border border-line bg-surface shadow-xl">
          {filtered.length === 0 ? (
            <p className="px-3.5 py-4 text-center text-[13px] text-faint">
              {options.length === 0 ? "No live model list — type a name and save" : `No matches for “${query}”`}
            </p>
          ) : (
            <div ref={listRef} className="max-h-64 overflow-y-auto p-1" role="listbox">
              {filtered.map((o, i) => {
                const isDefaultRow = o === defaultOption;
                const isSelected = isDefaultRow ? value === "" : o === value;
                return (
                  <button
                    key={o}
                    type="button"
                    role="option" aria-selected={isSelected}
                    onMouseEnter={() => setHighlight(i)}
                    onClick={() => pick(isDefaultRow ? "" : o)}
                    className={cx(
                      "flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left font-mono text-[13px]",
                      i === highlight ? "bg-surface-2 text-ink" : "text-muted",
                      isDefaultRow && "border-b border-line font-sans font-semibold"
                    )}
                  >
                    <span className="truncate">{o}</span>
                    {isSelected && <Check size={13} className="shrink-0 text-accent" />}
                  </button>
                );
              })}
            </div>
          )}
          <div className="border-t border-line px-3 py-1.5 text-[11px] text-faint">
            {note ?? (options.length > 0 ? `${options.length} models — type to filter, Enter to pick` : "free text allowed")}
          </div>
        </div>
      )}
    </div>
  );
}
