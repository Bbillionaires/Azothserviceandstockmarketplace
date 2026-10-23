"use client";

import { useState } from "react";
import { Alert } from "@/components/Alert";
import { AuthShell } from "@/components/AuthShell";
import { Turnstile, captchaEnabled } from "@/components/Turnstile";
import { api } from "@/lib/api";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState("");
  const [captcha, setCaptcha] = useState<string | null>(null);
  const [captchaReset, setCaptchaReset] = useState(0);
  return (
    <AuthShell title="Reset your password">
      <form
        className="space-y-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await api<{ detail: string }>("/auth/password-reset/request", { method: "POST", json: { email, captcha_token: captcha } }).catch((err) => ({ detail: err.message }));
          setMsg(r.detail);
          setCaptchaReset((n) => n + 1);
        }}
      >
        {msg && <Alert kind="info">{msg}</Alert>}
        <div>
          <label htmlFor="email" className="label">Email</label>
          <input id="email" type="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <Turnstile onToken={setCaptcha} resetKey={captchaReset} />
        <button className="btn-gold w-full" disabled={captchaEnabled && !captcha}>Send reset link</button>
      </form>
    </AuthShell>
  );
}
