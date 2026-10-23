"use client";

import { useEffect, useRef } from "react";

/**
 * Cloudflare Turnstile CAPTCHA. Renders nothing unless
 * NEXT_PUBLIC_TURNSTILE_SITE_KEY is set (the API skips verification when its
 * secret is unset, so development works without either). Reports the token
 * through ``onToken``; tokens are single-use, so call ``reset`` after a
 * failed submit by changing ``resetKey``.
 */
const SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "";
const SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

type TurnstileApi = {
  render: (el: HTMLElement, opts: Record<string, unknown>) => string;
  remove: (id: string) => void;
};

declare global {
  interface Window { turnstile?: TurnstileApi }
}

let loading: Promise<void> | null = null;

function loadScript(): Promise<void> {
  loading ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = SCRIPT;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => { loading = null; reject(new Error("CAPTCHA failed to load")); };
    document.head.appendChild(s);
  });
  return loading;
}

export const captchaEnabled = Boolean(SITE_KEY);

export function Turnstile({ onToken, resetKey = 0 }: { onToken: (token: string | null) => void; resetKey?: number }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!SITE_KEY || !ref.current) return;
    let id: string | null = null;
    let cancelled = false;
    onToken(null);
    loadScript().then(() => {
      if (cancelled || !ref.current || !window.turnstile) return;
      id = window.turnstile.render(ref.current, {
        sitekey: SITE_KEY,
        theme: "dark",
        callback: (t: string) => onToken(t),
        "expired-callback": () => onToken(null),
        "error-callback": () => onToken(null),
      });
    }).catch(() => onToken(null));
    return () => {
      cancelled = true;
      if (id && window.turnstile) window.turnstile.remove(id);
    };
    // onToken is a state setter at every call site; re-render only on reset.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  if (!SITE_KEY) return null;
  return <div ref={ref} className="min-h-[65px]" />;
}
