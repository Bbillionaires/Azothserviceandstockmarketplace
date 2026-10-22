"use client";

import { useState } from "react";
import { Alert } from "@/components/Alert";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

export function SecurityPanel() {
  const { user, refresh } = useSession();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      setMsg({ ok: true, text: ok });
      setSetup(null);
      setCode("");
      await refresh();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };

  return (
    <div className="card max-w-xl space-y-4 p-6">
      <h2 className="font-display text-xl">Two-step verification</h2>
      {msg && <Alert kind={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
      {user?.mfa_enabled ? (
        <>
          <p className="text-sm text-emerald-300">Enabled. You will be asked for an authenticator code when signing in.</p>
          <label htmlFor="dcode" className="label">Enter a current code to disable</label>
          <input id="dcode" className="input" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />
          <button className="btn-ghost" onClick={() => run(() => api("/auth/mfa/disable", { method: "POST", json: { code } }), "Two-step verification disabled.")}>Disable</button>
        </>
      ) : setup ? (
        <>
          <p className="text-sm text-ink-300">Add this key to your authenticator app (Google Authenticator, 1Password, Authy…), then enter the 6-digit code.</p>
          <code className="block break-all rounded bg-ink-950 p-3 text-gold-300">{setup.secret}</code>
          <a className="text-xs text-ink-400 underline" href={setup.otpauth_uri}>Open in authenticator app</a>
          <label htmlFor="ecode" className="label">Code</label>
          <input id="ecode" className="input" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />
          <button className="btn-gold" onClick={() => run(() => api("/auth/mfa/enable", { method: "POST", json: { code } }), "Two-step verification enabled.")}>Enable</button>
        </>
      ) : (
        <button className="btn-gold" onClick={async () => setSetup(await api("/auth/mfa/setup", { method: "POST" }))}>Set up authenticator app</button>
      )}
      <hr className="border-ink-700" />
      <button className="btn-ghost text-sm" onClick={() => run(() => api("/auth/logout-all", { method: "POST" }), "Signed out on all devices.")}>Sign out of all devices</button>
    </div>
  );
}
