"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { brand } from "@/config/brand";
import { useCart } from "@/lib/cart";
import { hasRole, useSession } from "@/lib/session";

const NAV = [
  { href: "/search?type=photo", label: "Photos" },
  { href: "/search?type=video", label: "Video" },
  { href: "/search?free=true", label: "Free" },
  { href: "/creators", label: "Hire creators" },
  { href: "/request-this-shot", label: "Request This Shot" },
];

export function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2" aria-label={`${brand.name} home`}>
      {brand.logoUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={brand.logoUrl} alt="" className="h-8 w-auto" />
      ) : (
        <span aria-hidden className="grid h-8 w-8 place-items-center rounded-full border border-gold-500 text-gold-400 font-display text-lg">
          {brand.name.charAt(0)}
        </span>
      )}
      <span className="font-display text-xl text-white">{brand.name}</span>
    </Link>
  );
}

export function Header() {
  const { user, logout } = useSession();
  const { items } = useCart();
  const [open, setOpen] = useState(false);
  const router = useRouter();

  return (
    <header className="sticky top-0 z-40 border-b border-ink-800/80 bg-ink-950/85 backdrop-blur">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 btn-gold">
        Skip to content
      </a>
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4">
        <Logo />
        <nav aria-label="Primary" className="hidden lg:block">
          <ul className="flex items-center gap-6 text-sm text-ink-200">
            {NAV.map((n) => (
              <li key={n.href}>
                <Link className="hover:text-gold-300" href={n.href}>{n.label}</Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="hidden items-center gap-3 lg:flex">
          {items.length > 0 && (
            <Link href="/cart" className="text-sm text-gold-300 hover:text-gold-400">Cart ({items.length})</Link>
          )}
          {user ? (
            <>
              {hasRole(user, "moderator", "finance_admin") && <Link href="/admin" className="text-sm text-ink-200 hover:text-gold-300">Admin</Link>}
              <Link href="/dashboard" className="text-sm text-ink-200 hover:text-gold-300">Dashboard</Link>
              <button
                className="btn-ghost text-sm"
                onClick={async () => { await logout(); router.push("/"); }}
              >
                Sign out
              </button>
            </>
          ) : (
            <>
              <Link href="/login" className="text-sm text-ink-200 hover:text-gold-300">Sign in</Link>
              <Link href="/register?sell=1" className="btn-gold text-sm">Start selling</Link>
            </>
          )}
        </div>
        <button
          className="lg:hidden btn-ghost px-3 py-2 text-sm"
          aria-expanded={open}
          aria-controls="mobile-nav"
          onClick={() => setOpen((o) => !o)}
        >
          {open ? "Close" : "Menu"}
        </button>
      </div>
      {open && (
        <nav id="mobile-nav" aria-label="Mobile" className="border-t border-ink-800 px-4 py-4 lg:hidden">
          <ul className="flex flex-col gap-3 text-ink-200">
            {NAV.map((n) => (
              <li key={n.href}><Link href={n.href} onClick={() => setOpen(false)}>{n.label}</Link></li>
            ))}
            {items.length > 0 && <li><Link href="/cart" onClick={() => setOpen(false)}>Cart ({items.length})</Link></li>}
            {user ? (
              <>
                <li><Link href="/dashboard" onClick={() => setOpen(false)}>Dashboard</Link></li>
                {hasRole(user, "moderator", "finance_admin") && <li><Link href="/admin" onClick={() => setOpen(false)}>Admin</Link></li>}
                <li><button onClick={async () => { await logout(); setOpen(false); router.push("/"); }}>Sign out</button></li>
              </>
            ) : (
              <>
                <li><Link href="/login" onClick={() => setOpen(false)}>Sign in</Link></li>
                <li><Link href="/register?sell=1" onClick={() => setOpen(false)}>Start selling</Link></li>
              </>
            )}
          </ul>
        </nav>
      )}
    </header>
  );
}
