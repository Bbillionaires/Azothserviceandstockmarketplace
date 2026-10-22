"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Alert } from "@/components/Alert";
import { AuthShell } from "@/components/AuthShell";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { refresh } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const next = params.get("next")?.startsWith("/") ? params.get("next")! : "/dashboard";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mfaToken) {
        await api("/auth/mfa/verify", { method: "POST", json: { code }, headers: { Authorization: `Bearer ${mfaToken}` } });
      } else {
        const r = await api<{ access_token: string; mfa_required: boolean }>("/auth/login", { method: "POST", json: { email, password } });
        if (r.mfa_required) {
          setMfaToken(r.access_token);
          return;
        }
      }
      await refresh();
      router.push(next);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      {error && <Alert>{error}</Alert>}
      {mfaToken ? (
        <div>
          <label htmlFor="code" className="label">Authenticator code</label>
          <input id="code" className="input" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} required autoFocus />
        </div>
      ) : (
        <>
          <div>
            <label htmlFor="email" className="label">Email</label>
            <input id="email" type="email" className="input" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div>
            <label htmlFor="password" className="label">Password</label>
            <input id="password" type="password" className="input" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
        </>
      )}
      <button className="btn-gold w-full" disabled={busy}>{busy ? "Signing in…" : mfaToken ? "Verify" : "Sign in"}</button>
      <p className="flex justify-between text-sm text-ink-300">
        <Link href="/forgot-password" className="hover:text-gold-300">Forgot password?</Link>
        <Link href="/register" className="hover:text-gold-300">Create an account</Link>
      </p>
    </form>
  );
}

export default function LoginPage() {
  return (
    <AuthShell title="Welcome back" subtitle="Sign in to download, license and manage your storefront.">
      <Suspense><LoginForm /></Suspense>
    </AuthShell>
  );
}
