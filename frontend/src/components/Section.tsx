import Link from "next/link";

export function Section({
  id, eyebrow, title, intro, action, children,
}: {
  id?: string;
  eyebrow?: string;
  title: string;
  intro?: string;
  action?: { href: string; label: string };
  children?: React.ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={id ? `${id}-title` : undefined} className="mx-auto max-w-7xl px-4 py-14 sm:py-20">
      <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="max-w-2xl">
          {eyebrow && <p className="text-xs font-semibold uppercase tracking-[0.2em] text-gold-400">{eyebrow}</p>}
          <h2 id={id ? `${id}-title` : undefined} className="font-display mt-2 text-3xl sm:text-4xl">{title}</h2>
          {intro && <p className="mt-3 text-ink-300">{intro}</p>}
        </div>
        {action && <Link href={action.href} className="btn-ghost shrink-0 text-sm">{action.label} →</Link>}
      </div>
      {children}
    </section>
  );
}
