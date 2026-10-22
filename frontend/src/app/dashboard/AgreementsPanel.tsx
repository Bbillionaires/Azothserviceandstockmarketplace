"use client";

import { useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label } from "@/lib/api";
import type { AgreementTemplate } from "@/lib/types";

export function AgreementsPanel({ templates, active, onSigned }: { templates: AgreementTemplate[]; active: Set<string>; onSigned: () => void }) {
  const [open, setOpen] = useState<AgreementTemplate | null>(null);
  const [legalName, setLegalName] = useState("");
  const [owner, setOwner] = useState("");
  const [agree, setAgree] = useState(false);
  const [error, setError] = useState("");

  const sign = async () => {
    if (!open) return;
    setError("");
    try {
      await api("/agreements/accept", {
        method: "POST",
        json: { template_code: open.code, template_version: open.version, body_sha256: open.body_sha256,
                signer_legal_name: legalName, rights_owner_name: owner || legalName, i_agree: agree },
      });
      setOpen(null);
      onSigned();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {templates.map((t) => (
        <div key={t.id} className="card flex flex-col p-6">
          <p className="text-xs uppercase tracking-widest text-gold-400">{label(t.revenue_model)}</p>
          <h3 className="font-display mt-1 text-xl">{t.title}</h3>
          <p className="mt-2 text-sm text-ink-300">
            {t.revenue_model === "free" ? "No royalty on zero-revenue downloads." :
              t.initial_exclusive_share_percent ? `${t.initial_exclusive_share_percent}% to you on the initial exclusive sale; ${t.creator_share_percent}% on qualifying later sales.` :
              `${t.creator_share_percent}% of net licensing revenue to you.`}
          </p>
          <p className="mt-2 text-xs text-ink-400">Version {t.version} · {label(t.legal_review_status)}</p>
          <div className="mt-auto pt-5">
            {active.has(t.code) ? <p className="text-sm text-emerald-300">✓ Accepted</p> :
              t.available_to_sign ? <button className="btn-gold w-full" onClick={() => { setOpen(t); setAgree(false); }}>Review & accept</button> :
              <p className="text-sm text-ink-400">{t.revenue_model === "exclusive" ? "Exclusive deals are signed individually by e-signature." : "Not yet available."}</p>}
          </div>
        </div>
      ))}

      {open && (
        <div role="dialog" aria-modal="true" aria-labelledby="agreement-title" className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4">
          <div className="card max-h-[90vh] w-full max-w-2xl overflow-y-auto p-6">
            <h2 id="agreement-title" className="font-display text-2xl">{open.title} · v{open.version}</h2>
            <pre className="mt-4 whitespace-pre-wrap rounded-lg bg-ink-950 p-4 text-sm text-ink-200">{open.body_markdown}</pre>
            <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
              <dt className="text-ink-400">Territory</dt><dd>{open.territory.join(", ")}</dd>
              <dt className="text-ink-400">Permitted uses</dt><dd>{open.permitted_uses.map(label).join(", ")}</dd>
              <dt className="text-ink-400">Duration</dt><dd>{label(open.duration)}</dd>
              <dt className="text-ink-400">Withdrawal</dt><dd>{open.withdrawal_terms}</dd>
            </dl>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <div><label htmlFor="ln" className="label">Your full legal name</label><input id="ln" className="input" value={legalName} onChange={(e) => setLegalName(e.target.value)} /></div>
              <div><label htmlFor="ro" className="label">Rights owner (if different)</label><input id="ro" className="input" value={owner} onChange={(e) => setOwner(e.target.value)} /></div>
            </div>
            <label className="mt-4 flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
              I have read this agreement and accept it electronically. I understand a record of this acceptance (time, IP address and document fingerprint) is kept.
            </label>
            {error && <div className="mt-3"><Alert>{error}</Alert></div>}
            <div className="mt-5 flex justify-end gap-2">
              <button className="btn-ghost" onClick={() => setOpen(null)}>Cancel</button>
              <button className="btn-gold" disabled={!agree || legalName.trim().length < 2} onClick={sign}>Accept agreement</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
