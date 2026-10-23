"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Alert } from "@/components/Alert";
import { Turnstile, captchaEnabled } from "@/components/Turnstile";
import { api } from "@/lib/api";

export function ComplaintForm() {
  const assetId = useSearchParams().get("asset") ?? "";
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [captcha, setCaptcha] = useState<string | null>(null);
  const [captchaReset, setCaptchaReset] = useState(0);
  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      const r = await api<{ detail: string }>("/copyright-complaints", {
        method: "POST",
        json: {
          asset_id: String(f.get("asset_id")).trim(),
          complainant_name: f.get("name"), complainant_email: f.get("email"), complainant_address: f.get("address"),
          copyrighted_work_description: f.get("work"), good_faith_statement: f.get("good_faith") === "on",
          accuracy_statement: f.get("accuracy") === "on", electronic_signature: f.get("signature"), captcha_token: captcha,
        },
      });
      setMsg({ ok: true, text: r.detail });
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
      setCaptchaReset((n) => n + 1);
    }
  };
  return (
    <form onSubmit={submit} className="card mt-10 space-y-4 p-6">
      <h2 className="font-display text-2xl">Submit a copyright notice</h2>
      {msg && <Alert kind={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
      <div><label className="label" htmlFor="asset_id">Media ID (from the media page URL)</label><input className="input" id="asset_id" name="asset_id" defaultValue={assetId} required /></div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div><label className="label" htmlFor="name">Your name</label><input className="input" id="name" name="name" required /></div>
        <div><label className="label" htmlFor="email">Email</label><input className="input" id="email" name="email" type="email" required /></div>
      </div>
      <div><label className="label" htmlFor="address">Postal address</label><textarea className="input" id="address" name="address" required /></div>
      <div><label className="label" htmlFor="work">Describe the copyrighted work and how it is infringed</label><textarea className="input min-h-24" id="work" name="work" required minLength={10} /></div>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" name="good_faith" className="mt-1" required /> I have a good-faith belief that the use is not authorized by the copyright owner, its agent, or the law.</label>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" name="accuracy" className="mt-1" required /> The information in this notice is accurate and, under penalty of perjury, I am the owner or authorized to act on the owner&apos;s behalf.</label>
      <div><label className="label" htmlFor="signature">Electronic signature (type your full name)</label><input className="input" id="signature" name="signature" required /></div>
      <Turnstile onToken={setCaptcha} resetKey={captchaReset} />
      <button className="btn-gold" disabled={captchaEnabled && !captcha}>Submit notice</button>
    </form>
  );
}
