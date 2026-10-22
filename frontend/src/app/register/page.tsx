"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Alert } from "@/components/Alert";
import { AuthShell } from "@/components/AuthShell";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { refresh } = useSession();
  const [form, setForm] = useState({ email: "", password: "", display_name: "", wants_to_sell: params.get("sell") === "1", accept_terms: false });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/auth/register", { method: "POST", json: { ...form, referral_code: params.get("ref") || undefined } });
      await refresh();
      router.push("/dashboard?welcome=1");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      {error && <Alert>{error}</Alert>}
      <div>
        <label htmlFor="name" className="label">Name or business name</label>
        <input id="name" className="input" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} required minLength={2} />
      </div>
      <div>
        <label htmlFor="email" className="label">Email</label>
        <input id="email" type="email" className="input" autoComplete="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
      </div>
      <div>
        <label htmlFor="password" className="label">Password (10+ characters)</label>
        <input id="password" type="password" className="input" autoComplete="new-password" minLength={10} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
      </div>
      <fieldset className="space-y-2 text-sm">
        <legend className="label">I want to</legend>
        <label className="flex items-center gap-2"><input type="radio" name="intent" checked={!form.wants_to_sell} onChange={() => setForm({ ...form, wants_to_sell: false })} /> Find and license media or hire creators</label>
        <label className="flex items-center gap-2"><input type="radio" name="intent" checked={form.wants_to_sell} onChange={() => setForm({ ...form, wants_to_sell: true })} /> Sell my photos, footage or services</label>
      </fieldset>
      <label className="flex items-start gap-2 text-sm text-ink-200">
        <input type="checkbox" className="mt-1" checked={form.accept_terms} onChange={(e) => setForm({ ...form, accept_terms: e.target.checked })} required />
        <span>I agree to the <Link className="underline" href="/legal/terms">Terms of Service</Link> and <Link className="underline" href="/legal/privacy">Privacy Policy</Link>.</span>
      </label>
      <button className="btn-gold w-full" disabled={busy}>{busy ? "Creating account…" : "Create account"}</button>
      <p className="text-center text-sm text-ink-300">Already have an account? <Link href="/login" className="text-gold-300">Sign in</Link></p>
    </form>
  );
}

export default function RegisterPage() {
  return (
    <AuthShell title="Create your account" subtitle="Free for buyers and creators. You can add a storefront any time.">
      <Suspense><RegisterForm /></Suspense>
    </AuthShell>
  );
}
