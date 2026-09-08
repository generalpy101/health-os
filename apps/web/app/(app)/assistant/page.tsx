"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, CheckCircle2, Sparkles, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Empty, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import type { ChatAction, ChatMessage } from "@/lib/types";
import { cx } from "@/lib/utils";

const SUGGESTIONS = [
  "Log two eggs and 200g rice for lunch",
  "Drank 750ml water",
  "Weighed 81.3 this morning",
  "I slept 6.5 hours",
  "How am I doing today?",
  "Set my protein target to 140g",
];

export default function AssistantPage() {
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const queryClient = useQueryClient();
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const send = useMutation({
    mutationFn: (text: string) => api.chat(text, conversationId),
    onSuccess: (res) => {
      setConversationId(res.conversation_id);
      setMessages((m) => [...m, { role: "assistant", content: res.reply, actions: res.actions }]);
      queryClient.invalidateQueries(); // AI actions may have changed anything
    },
    onError: (e) => {
      setMessages((m) => [...m, { role: "assistant", content: `Something went wrong: ${e.message}` }]);
    },
  });

  function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || send.isPending) return;
    setMessages((m) => [...m, { role: "user", content: trimmed }]);
    setInput("");
    send.mutate(trimmed);
  }

  return (
    <div className="mx-auto flex h-[calc(100dvh-6rem)] max-w-3xl flex-col md:h-[calc(100dvh-2rem)]">
      <header className="flex items-center gap-2 border-b border-line px-4 py-3.5 sm:px-6">
        <Sparkles size={17} className="text-accent" />
        <h1 className="font-display text-lg font-semibold tracking-tight">Assistant</h1>
        <span className="ml-auto text-[11px] font-medium text-faint">Not medical advice</span>
      </header>

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
              <div className="whitespace-pre-wrap">{m.content}</div>
              {m.actions && m.actions.length > 0 && (
                <div className="mt-2 space-y-1 border-t border-line pt-2">
                  {m.actions.map((a) => (
                    <ActionChip key={a.id} action={a} />
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {send.isPending && (
          <div className="flex items-center gap-2 text-sm text-muted">
            <Spinner className="h-4 w-4" /> Thinking…
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
            disabled={!input.trim() || send.isPending}
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
