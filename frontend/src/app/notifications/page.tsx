"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Note = { id: string; kind: string; title: string; body: string; link: string; read: boolean; created_at: string };

export default function NotificationsPage() {
  const [notes, setNotes] = useState<Note[] | null>(null);
  useEffect(() => {
    api<Note[]>("/notifications").then((n) => { setNotes(n); api("/notifications/read", { method: "POST" }); }).catch(() => setNotes([]));
  }, []);
  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="font-display text-4xl">Notifications</h1>
      <ul className="mt-6 space-y-2">
        {notes?.length === 0 && <li className="text-ink-300">Nothing yet.</li>}
        {notes?.map((n) => (
          <li key={n.id} className={`card p-4 ${n.read ? "" : "border-gold-600"}`}>
            {n.link ? <Link href={n.link} className="font-medium hover:text-gold-300">{n.title}</Link> : <p className="font-medium">{n.title}</p>}
            {n.body && <p className="mt-1 text-sm text-ink-300">{n.body}</p>}
            <p className="mt-1 text-xs text-ink-400">{new Date(n.created_at).toLocaleString()}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
