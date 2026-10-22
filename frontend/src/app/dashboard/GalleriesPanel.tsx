"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label } from "@/lib/api";

type Row = { id: string; title: string; client_name: string; status: string; item_count: number; created_at: string; client_approved_at: string | null };

export function GalleriesPanel() {
  const router = useRouter();
  const [rows, setRows] = useState<Row[]>([]);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { api<Row[]>("/galleries").then(setRows).catch(() => {}); }, []);
  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-300">Private proofing galleries for clients: watermarked previews, favorites and selections, comments, approval and optional downloads. Separate from your public stock listings.</p>
      {error && <Alert>{error}</Alert>}
      <form className="flex gap-2" onSubmit={async (e) => {
        e.preventDefault();
        try { const g = await api<{ id: string }>("/galleries", { method: "POST", json: { title } }); router.push(`/dashboard/galleries/${g.id}`); }
        catch (err) { setError((err as Error).message); }
      }}>
        <label htmlFor="g-title" className="sr-only">Gallery title</label>
        <input id="g-title" className="input" placeholder="e.g. Smith wedding proofs" value={title} onChange={(e) => setTitle(e.target.value)} required minLength={2} />
        <button className="btn-gold shrink-0">New gallery</button>
      </form>
      <ul className="space-y-2">
        {rows.map((g) => (
          <li key={g.id}><Link href={`/dashboard/galleries/${g.id}`} className="card flex justify-between p-4 hover:border-gold-600">
            <span>{g.title} <span className="text-xs text-ink-400">· {g.client_name || "no client yet"} · {g.item_count} items</span></span>
            <span className="text-sm">{label(g.status)}</span>
          </Link></li>
        ))}
      </ul>
    </div>
  );
}
