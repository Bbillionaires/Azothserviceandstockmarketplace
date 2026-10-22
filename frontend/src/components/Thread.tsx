"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

type Msg = { id: string; body: string; is_system: boolean; mine: boolean; sender: string; created_at: string };

export function Thread({ conversationId, compact = false }: { conversationId: string; compact?: boolean }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [body, setBody] = useState("");
  const [error, setError] = useState("");
  const end = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const r = await api<{ messages: Msg[] }>(`/conversations/${conversationId}`);
    setMessages(r.messages);
  }, [conversationId]);

  useEffect(() => {
    load().catch((e) => setError(e.message));
    const t = setInterval(() => load().catch(() => {}), 10_000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [messages.length]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!body.trim()) return;
    try {
      await api(`/conversations/${conversationId}/messages`, { method: "POST", json: { body } });
      setBody("");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="flex flex-col">
      <div className={`space-y-2 overflow-y-auto pr-1 ${compact ? "max-h-80" : "max-h-[60vh]"}`} aria-live="polite">
        {messages.map((m) => m.is_system ? (
          <p key={m.id} className="text-center text-xs text-ink-400">{m.body} · {new Date(m.created_at).toLocaleString()}</p>
        ) : (
          <div key={m.id} className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm ${m.mine ? "ml-auto bg-gold-500/20" : "bg-ink-800"}`}>
            <p className="whitespace-pre-line">{m.body}</p>
            <p className="mt-1 text-[11px] text-ink-400">{m.mine ? "You" : m.sender} · {new Date(m.created_at).toLocaleString()}</p>
          </div>
        ))}
        <div ref={end} />
      </div>
      {error && <p className="mt-2 text-xs text-red-300">{error}</p>}
      <form onSubmit={send} className="mt-3 flex gap-2">
        <label htmlFor={`msg-${conversationId}`} className="sr-only">Message</label>
        <input id={`msg-${conversationId}`} className="input" value={body} onChange={(e) => setBody(e.target.value)} placeholder="Write a message…" maxLength={5000} />
        <button className="btn-gold px-4">Send</button>
      </form>
    </div>
  );
}
