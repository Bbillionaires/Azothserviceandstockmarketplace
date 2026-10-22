import { Suspense } from "react";
import { SearchClient } from "./SearchClient";

export const metadata = { title: "Search media" };

export default function SearchPage() {
  return (
    <Suspense fallback={<p className="p-10 text-center text-ink-300">Loading…</p>}>
      <SearchClient />
    </Suspense>
  );
}
