export function AuthShell({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto flex min-h-[70vh] max-w-md flex-col justify-center px-4 py-16">
      <h1 className="font-display text-3xl">{title}</h1>
      {subtitle && <p className="mt-2 text-ink-300">{subtitle}</p>}
      <div className="mt-8">{children}</div>
    </div>
  );
}
