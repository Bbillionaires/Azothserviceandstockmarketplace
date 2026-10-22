"use client";

import { useState } from "react";
import { Alert } from "@/components/Alert";
import { AuthShell } from "@/components/AuthShell";
import { api } from "@/lib/api";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState("");
  return (
    <AuthShell title="Reset your password">
      <form
        className="space-y-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await api<{ detail: string }>("/auth/password-reset/request", { method: "POST", json: { email } }).catch((err) => ({ detail: err.message }));
          setMsg(r.detail);
        }}
      >
        {msg && <Alert kind="info">{msg}</Alert>}
        <div>
          <label htmlFor="email" className="label">Email</label>
          <input id="email" type="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <button className="btn-gold w-full">Send reset link</button>
      </form>
    </AuthShell>
  );
}
