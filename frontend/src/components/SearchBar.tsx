"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function SearchBar({ initial = "", large = false }: { initial?: string; large?: boolean }) {
  const [q, setQ] = useState(initial);
  const router = useRouter();
  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        router.push(`/search?q=${encodeURIComponent(q.trim())}`);
      }}
      className={`flex w-full items-center gap-2 rounded-full border border-ink-600 bg-ink-900/80 backdrop-blur ${large ? "p-2 pl-6" : "p-1.5 pl-4"}`}
    >
      <label htmlFor="site-search" className="sr-only">Search photos and footage</label>
      <input
        id="site-search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder='Try "4K aerial footage of downtown Jacksonville at sunset"'
        className={`min-w-0 flex-1 bg-transparent text-white placeholder:text-ink-400 focus:outline-none ${large ? "text-lg" : "text-sm"}`}
      />
      <button type="submit" className={`btn-gold ${large ? "" : "px-4 py-1.5 text-sm"}`}>Search</button>
    </form>
  );
}
