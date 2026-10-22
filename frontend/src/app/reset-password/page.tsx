"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Alert } from "@/components/Alert";
import { AuthShell } from "@/components/AuthShell";
import { api } from "@/lib/api";

function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);
  return (
    <form
      className="space-y-4"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          const r = await api<{ detail: string }>("/auth/password-reset/confirm", { method: "POST", json: { token, new_password: password } });
          setResult({ ok: true, msg: r.detail });
        } catch (err) {
          setResult({ ok: false, msg: (err as Error).message });
        }
      }}
    >
      {result && <Alert kind={result.ok ? "success" : "error"}>{result.msg} {result.ok && <Link className="underline" href="/login">Sign in</Link>}</Alert>}
      <div>
        <label htmlFor="pw" className="label">New password (10+ characters)</label>
        <input id="pw" type="password" minLength={10} className="input" value={password} onChange={(e) => setPassword(e.target.value)} required />
      </div>
      <button className="btn-gold w-full">Update password</button>
    </form>
  );
}

export default function ResetPassword() {
  return <AuthShell title="Choose a new password"><Suspense><ResetForm /></Suspense></AuthShell>;
}
