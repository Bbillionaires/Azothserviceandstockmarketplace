export const metadata = { title: "Verify a license" };

export default function VerifyIndex() {
  return (
    <div className="mx-auto max-w-xl px-4 py-16">
      <h1 className="font-display text-3xl">Verify a license certificate</h1>
      <p className="mt-2 text-ink-300">Enter the certificate number printed on a license (for example LC-202610-ABCDEFGHJK).</p>
      <form className="mt-6 flex gap-2" action="/licenses/verify/lookup" method="get">
        <label htmlFor="cert" className="sr-only">Certificate number</label>
        <input id="cert" name="cert" className="input" required pattern="LC-[0-9]{6}-[A-Z0-9]{10}" />
        <button className="btn-gold">Verify</button>
      </form>
    </div>
  );
}
