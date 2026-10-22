"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Alert } from "@/components/Alert";
import { AuthShell } from "@/components/AuthShell";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

function Verify() {
  const token = useSearchParams().get("token");
  const { refresh } = useSession();
  const [state, setState] = useState<{ ok: boolean; msg: string } | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (!token || ran.current) return;
    ran.current = true;
    api("/auth/verify-email", { method: "POST", json: { token } })
      .then(() => { setState({ ok: true, msg: "Your email is verified." }); refresh(); })
      .catch((e) => setState({ ok: false, msg: e.message }));
  }, [token, refresh]);

  if (!token) return <Alert>Missing verification token.</Alert>;
  if (!state) return <p className="text-ink-300">Verifying…</p>;
  return (
    <div className="space-y-4">
      <Alert kind={state.ok ? "success" : "error"}>{state.msg}</Alert>
      <Link href="/dashboard" className="btn-gold">Continue to dashboard</Link>
    </div>
  );
}

export default function VerifyEmailPage() {
  return <AuthShell title="Email verification"><Suspense><Verify /></Suspense></AuthShell>;
}
