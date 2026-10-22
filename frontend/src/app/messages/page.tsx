"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Thread } from "@/components/Thread";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

type Conv = { id: string; kind: string; title: string; link: string | null; other_party: string; last_message_at: string; preview: string; unread: number };

function Inbox() {
  const { user, loading } = useSession();
  const router = useRouter();
  const selected = useSearchParams().get("c");
  const [convs, setConvs] = useState<Conv[]>([]);

  useEffect(() => {
    if (!loading && !user) router.push("/login?next=/messages");
    if (user) api<Conv[]>("/conversations").then(setConvs).catch(() => {});
  }, [user, loading, router, selected]);

  const current = convs.find((c) => c.id === selected);
  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="font-display text-4xl">Messages</h1>
      <div className="mt-6 grid gap-6 md:grid-cols-[300px_1fr]">
        <ul className="space-y-2">
          {convs.length === 0 && <li className="text-sm text-ink-300">No conversations yet.</li>}
          {convs.map((c) => (
            <li key={c.id}>
              <Link href={`/messages?c=${c.id}`} className={`card block p-3 text-sm ${c.id === selected ? "border-gold-600" : ""}`}>
                <p className="flex justify-between gap-2 font-medium"><span className="truncate">{c.other_party}</span>{c.unread > 0 && <span className="rounded-full bg-gold-500 px-2 text-xs text-ink-950">{c.unread}</span>}</p>
                <p className="truncate text-xs text-ink-400">{c.title}</p>
                <p className="truncate text-xs text-ink-300">{c.preview}</p>
              </Link>
            </li>
          ))}
        </ul>
        <section className="card p-4">
          {current ? (
            <>
              <div className="mb-3 flex justify-between gap-2">
                <h2 className="font-display text-lg">{current.title}</h2>
                {current.link && <Link href={current.link} className="text-sm text-gold-300 underline">Open {current.kind}</Link>}
              </div>
              <Thread conversationId={current.id} />
            </>
          ) : <p className="text-ink-300">Select a conversation.</p>}
        </section>
      </div>
    </div>
  );
}

export default function MessagesPage() {
  return <Suspense><Inbox /></Suspense>;
}
