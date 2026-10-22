import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-xl px-4 py-24 text-center">
      <p className="text-xs uppercase tracking-[0.25em] text-gold-400">404</p>
      <h1 className="font-display mt-2 text-4xl">This frame is missing</h1>
      <p className="mt-3 text-ink-300">The page or media you&apos;re looking for isn&apos;t available.</p>
      <Link href="/search" className="btn-gold mt-8">Search the catalog</Link>
    </div>
  );
}
