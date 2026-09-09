"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, CheckCircle2, History, Plus, Sparkles, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Empty, Sheet, Spinner } from "@/components/ui";
import { ProviderPicker } from "@/components/ai-picker";
import { api } from "@/lib/api";
import type { ChatAction, ChatMessage, TraceEvent } from "@/lib/types";
import { cx, fmtDate, fmtTime } from "@/lib/utils";

const SUGGESTIONS = [
  "How am I doing today?",
  "What should I eat for dinner?",
  "Log two eggs and 200g rice for lunch",
  "Drank 750ml water",
  "I slept 6.5 hours",
  "Make me a high-protein Indian dinner recipe under 30 min",
];

export default function AssistantPage() {
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [liveTrace, setLiveTrace] = useState<TraceEvent[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const queryClient = useQueryClient();
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const traceRef = useRef<TraceEvent[]>([]);
  const startRef = useRef(0);

  // ticking "thought for Ns" timer while busy
  useEffect(() => {
    if (!busy) return;
    setElapsed(0);
    const t0 = Date.now();
    const iv = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 500);
    return () => clearInterval(iv);
  }, [busy]);

  const { data: conversations } = useQuery({ queryKey: ["conversations"], queryFn: api.conversations });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  // resume the most recent conversation from today automatically
  useEffect(() => {
    if (!conversations?.length || conversationId || messages.length) return;
    const latest = conversations[0];
    const today = new Date().toDateString();
    if (new Date(latest.updated_at).toDateString() === today) {
      openConversation(latest.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversations]);

  // command palette hands a message over via sessionStorage
  useEffect(() => {
    const pending = sessionStorage.getItem("healthos-pending-chat");
    if (pending) {
      sessionStorage.removeItem("healthos-pending-chat");
      submit(pending);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openConversation(id: string) {
    try {
      const msgs = await api.conversationMessages(id);
      setConversationId(id);
      setMessages(
        msgs.filter((m) => m.role === "user" || m.role === "assistant")
            .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }))
      );
      setHistoryOpen(false);
    } catch {
      // conversation gone — just start fresh
    }
  }

  function newChat() {
    setConversationId(undefined);
    setMessages([]);
    setHistoryOpen(false);
    inputRef.current?.focus();
  }

  // both helpers lazily open the assistant bubble on first server output
  function patchLast(patch: Partial<ChatMessage>) {
    setMessages((m) => {
      const copy = m[m.length - 1]?.role === "assistant"
        ? [...m]
        : [...m, { role: "assistant" as const, content: "" }];
      copy[copy.length - 1] = { ...copy[copy.length - 1], ...patch };
      return copy;
    });
  }

  function appendDelta(text: string) {
    setMessages((m) => {
      const copy = m[m.length - 1]?.role === "assistant"
        ? [...m]
        : [...m, { role: "assistant" as const, content: "" }];
      const last = copy[copy.length - 1];
      copy[copy.length - 1] = { ...last, content: last.content + text };
      return copy;
    });
  }

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setMessages((m) => [...m, { role: "user", content: trimmed }]);
    setInput("");
    setBusy(true);
    traceRef.current = [];
    setLiveTrace([]);
    startRef.current = Date.now();
    let arrived = false; // any server output (delta/actions/done/trace) — used to gate the fallback
    try {
      await api.chatStream(trimmed, conversationId, {
        onDelta: (t) => { arrived = true; appendDelta(t); },
        onTrace: (ev) => {
          arrived = true;
          traceRef.current = [...traceRef.current, ev];
          setLiveTrace(traceRef.current);
        },
        onActions: (actions) => { arrived = true; patchLast({ actions }); },
        onDone: (cid, reply, elapsedS) => {
          arrived = true;
          setConversationId(cid);
          patchLast({
            content: reply,
            elapsedS: elapsedS ?? Math.round((Date.now() - startRef.current) / 1000),
            trace: traceRef.current,
          });
        },
      });
      queryClient.invalidateQueries(); // AI actions may have changed anything
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    } catch (e) {
      if (!arrived) {
        // stream never got going (offline, proxy, old server) — one-shot plain fallback
        try {
          const res = await api.chat(trimmed, conversationId);
          setConversationId(res.conversation_id);
          patchLast({ content: res.reply, actions: res.actions });
          queryClient.invalidateQueries();
        } catch (e2) {
          patchLast({ content: `Something went wrong: ${(e2 as Error).message}` });
        }
      } else {
        // partial stream — never re-send (tools may already have executed)
        appendDelta("\n\n*(connection lost — partial reply)*");
      }
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100dvh-6rem)] max-w-3xl flex-col md:h-[calc(100dvh-2rem)]">
      <header className="flex items-center gap-2 border-b border-line px-4 py-3.5 sm:px-6">
        <Sparkles size={17} className="text-accent" />
        <h1 className="font-display text-lg font-semibold tracking-tight">Coach</h1>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setHistoryOpen(true)}
            aria-label="Chat history"
            className="rounded-xl border border-line bg-surface p-2 text-muted transition-colors hover:text-ink"
          >
            <History size={16} />
          </button>
          <button
            onClick={newChat}
            aria-label="New chat"
            className="rounded-xl border border-line bg-surface p-2 text-muted transition-colors hover:text-ink"
          >
            <Plus size={16} />
          </button>
          <ProviderPicker />
        </div>
      </header>

      <Sheet open={historyOpen} onClose={() => setHistoryOpen(false)} title="Conversations">
        {!conversations?.length ? (
          <p className="py-6 text-center text-sm text-faint">No past conversations.</p>
        ) : (
          <div className="space-y-0.5">
            {conversations.map((c) => (
              <button
                key={c.id}
                onClick={() => openConversation(c.id)}
                className={cx(
                  "flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-surface-2",
                  c.id === conversationId && "bg-surface-2"
                )}
              >
                <span className="min-w-0 truncate text-sm font-medium">{c.title || "Conversation"}</span>
                <span className="shrink-0 text-[11px] text-faint">
                  {fmtDate(c.updated_at.slice(0, 10))} {fmtTime(c.updated_at)}
                </span>
              </button>
            ))}
          </div>
        )}
      </Sheet>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-5 sm:px-6">
        {messages.length === 0 && (
          <div className="pt-6">
            <Empty
              title="What can I do for you?"
              hint="Log things in plain language, ask about your progress, or change your plan — I operate the app for you."
            />
            <div className="mx-auto mt-2 grid max-w-md gap-2 sm:grid-cols-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => submit(s)}
                  className="rounded-xl border border-line bg-surface px-3.5 py-3 text-left text-[13px] font-medium text-muted transition-colors hover:border-accent/40 hover:text-ink"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={cx("flex", m.role === "user" ? "justify-end" : "justify-start")}>
            <div
              className={cx(
                "max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed",
                m.role === "user"
                  ? "rounded-br-md bg-ink text-bg"
                  : "rounded-bl-md border border-line bg-surface"
              )}
            >
              <div className="whitespace-pre-wrap">
                {m.content}
                {busy && i === messages.length - 1 && m.role === "assistant" && (
                  <span className="ml-0.5 inline-block h-4 w-[7px] animate-pulse rounded-sm bg-accent/70 align-text-bottom" />
                )}
              </div>
              {m.actions && m.actions.length > 0 && (
                <div className="mt-2 space-y-1 border-t border-line pt-2">
                  {m.actions.map((a) => (
                    <ActionChip key={a.id} action={a} />
                  ))}
                </div>
              )}
              {m.role === "assistant" && m.elapsedS != null && (
                <details className="mt-1.5 group">
                  <summary className="cursor-pointer list-none text-[11px] text-faint hover:text-muted">
                    Thought for {m.elapsedS >= 60 ? `${Math.floor(m.elapsedS / 60)}m ${Math.round(m.elapsedS % 60)}s` : `${Math.round(m.elapsedS)}s`}
                    {(m.trace?.filter((t) => t.kind === "tool_end").length ?? 0) > 0 &&
                      ` · ${m.trace!.filter((t) => t.kind === "tool_end").length} tool${m.trace!.filter((t) => t.kind === "tool_end").length > 1 ? "s" : ""}`}
                  </summary>
                  <div className="mt-1 space-y-0.5 border-l-2 border-line pl-2.5">
                    {(m.trace || []).filter((t) => t.kind !== "heartbeat").map((t, i) => (
                      <div key={i} className="font-mono text-[10px] text-faint">
                        {t.kind === "thinking" && `→ thinking (round ${t.round})`}
                        {t.kind === "thought" && `✓ reply drafted in ${(t.ms ?? 0) / 1000}s`}
                        {t.kind === "tool_start" && `→ ${t.tool?.replaceAll("_", " ")}…`}
                        {t.kind === "tool_end" && `${t.status === "executed" ? "✓" : "✗"} ${t.tool?.replaceAll("_", " ")} · ${t.ms}ms`}
                        {t.kind === "error" && `✗ ${t.detail}`}
                        {t.elapsed_s != null && <span className="text-faint/60"> [{t.elapsed_s}s]</span>}
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </div>
          </div>
        ))}
        {busy && messages[messages.length - 1]?.role === "user" && (
          <div className="max-w-[85%] rounded-2xl rounded-bl-md border border-line bg-surface px-4 py-3">
            <div className="flex items-center gap-2 text-sm text-muted">
              <Spinner className="h-4 w-4" />
              <span>Thinking{elapsed > 2 ? ` — ${elapsed}s` : "…"}</span>
            </div>
            {liveTrace.filter((t) => t.kind.startsWith("tool")).length > 0 && (
              <div className="mt-2 space-y-1 border-t border-line pt-2">
                {liveTrace.filter((t) => t.kind === "tool_end").map((t, i) => (
                  <div key={i} className="flex items-center gap-1.5 font-mono text-[11px] text-faint">
                    {t.status === "executed"
                      ? <CheckCircle2 size={11} className="text-good" />
                      : <XCircle size={11} className="text-bad" />}
                    {t.tool?.replaceAll("_", " ")} · {t.ms}ms
                  </div>
                ))}
              </div>
            )}
            {elapsed >= 10 && (
              <p className="mt-1.5 text-[11px] text-faint">
                Still working — CLI providers can take a minute. The request is alive.
              </p>
            )}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form
        className="border-t border-line bg-bg p-3 sm:p-4"
        onSubmit={(e) => { e.preventDefault(); submit(input); }}
      >
        <div className="mx-auto flex max-w-3xl items-center gap-2">
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Log it, ask it, change it…"
            className="h-12 flex-1 rounded-full border border-line bg-surface px-5 text-[15px] placeholder:text-faint focus:border-accent focus:outline-none"
          />
          <button
            type="submit"
            disabled={!input.trim() || busy}
            aria-label="Send"
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-accent text-accent-ink transition-opacity disabled:opacity-40"
          >
            <ArrowUp size={20} strokeWidth={2.5} />
          </button>
        </div>
      </form>
    </div>
  );
}

function ActionChip({ action }: { action: ChatAction }) {
  const ok = action.status === "executed";
  const label = action.tool.replaceAll("_", " ");
  return (
    <div className="flex items-center gap-1.5 text-xs">
      {ok ? <CheckCircle2 size={13} className="text-good" /> : <XCircle size={13} className="text-bad" />}
      <span className="font-semibold">{label}</span>
      {ok && action.result && (
        <span className="truncate text-faint">
          {summarize(action.result)}
        </span>
      )}
    </div>
  );
}

function summarize(result: Record<string, unknown>): string {
  const r = result as Record<string, Record<string, unknown> | unknown>;
  const inner = (r.logged || r.created || r.recorded || r.updated) as Record<string, unknown> | undefined;
  const src = inner || r;
  const bits: string[] = [];
  for (const k of ["title", "name", "value", "calories", "amount_ml", "duration_min", "total_volume", "today_total_ml", "date"]) {
    if (src[k] != null && typeof src[k] !== "object") bits.push(String(src[k]));
  }
  return bits.slice(0, 4).join(" · ");
}
