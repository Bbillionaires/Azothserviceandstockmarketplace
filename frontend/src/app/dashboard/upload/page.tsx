"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label } from "@/lib/api";
import { uploadFile } from "@/lib/upload";

const CATEGORIES = [
  "aerial_drone", "architecture", "b_roll", "business_finance", "commercial", "documentary", "editorial",
  "entertainment", "food", "historical", "lifestyle", "motion_graphics", "nature_wildlife", "product",
  "real_estate", "sports", "technology", "transportation", "travel",
];

const DECLARATION =
  "I declare that I am the author of this media or am authorized by its copyright owner to license it; that it does not " +
  "infringe anyone's copyright, trademark, privacy or publicity rights; that I hold any model and property releases " +
  "required for the licenses I offer; and that I have disclosed every existing license, including any exclusive license, " +
  "that affects this media.";

export default function UploadPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!file) return;
    const data = new FormData(e.currentTarget);
    const text = (k: string) => String(data.get(k) ?? "").trim();
    const flag = (k: string) => data.get(k) !== null;
    setError("");
    setProgress(0);
    try {
      // The file goes straight to storage; the API never buffers large video.
      const uploadId = await uploadFile(file, "media", undefined, setProgress);
      setProgress(100);
      const asset = await api<{ id: string }>("/media/from-upload", { method: "POST", json: {
        upload_id: uploadId, title: text("title"), description: text("description"), category: text("category"),
        keywords: text("keywords").split(",").map((k) => k.trim()).filter(Boolean),
        location_city: text("location_city") || null, location_country: text("location_country") || null,
        distribution: text("distribution") || "nonexclusive", rights_owner_name: text("rights_owner_name"),
        existing_licenses_disclosure: text("existing_licenses_disclosure"),
        is_original_author: flag("is_original_author"), is_editorial_only: flag("is_editorial_only"),
        is_ai_generated: flag("is_ai_generated"), is_materially_altered: flag("is_materially_altered"),
        has_model_release: flag("has_model_release"), has_property_release: flag("has_property_release"),
        accept_declaration: flag("accept_declaration"),
      } });
      router.push(`/dashboard/media/${asset.id}?uploaded=1`);
    } catch (err) {
      setError((err as Error).message);
      setProgress(null);
    }
  };

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <Link href="/dashboard" className="text-sm text-ink-300 hover:text-gold-300">← Dashboard</Link>
      <h1 className="font-display mt-2 text-4xl">Upload media</h1>
      <p className="mt-2 text-ink-300">JPEG, PNG, TIFF, WebP up to 100 MB · MP4 or MOV up to 4 GB. Originals are stored privately; buyers see a watermarked preview.</p>
      <form onSubmit={submit} className="card mt-8 space-y-5 p-6">
        {error && <Alert>{error}</Alert>}
        <div>
          <label htmlFor="file" className="label">File</label>
          <input id="file" type="file" required accept="image/jpeg,image/png,image/tiff,image/webp,video/mp4,video/quicktime"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm file:mr-4 file:rounded-full file:border-0 file:bg-gold-500 file:px-4 file:py-2 file:text-ink-950" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2"><label htmlFor="title" className="label">Title</label><input id="title" name="title" className="input" required minLength={3} maxLength={200} /></div>
          <div className="sm:col-span-2"><label htmlFor="description" className="label">Description</label><textarea id="description" name="description" className="input min-h-24" /></div>
          <div>
            <label htmlFor="category" className="label">Category</label>
            <select id="category" name="category" className="input" required>{CATEGORIES.map((c) => <option key={c} value={c}>{label(c)}</option>)}</select>
          </div>
          <div><label htmlFor="keywords" className="label">Keywords (comma-separated)</label><input id="keywords" name="keywords" className="input" placeholder="skyline, sunset, aerial" /></div>
          <div><label htmlFor="city" className="label">City</label><input id="city" name="location_city" className="input" /></div>
          <div><label htmlFor="country" className="label">Country code</label><input id="country" name="location_country" maxLength={2} className="input" placeholder="US" /></div>
          <div className="sm:col-span-2">
            <label htmlFor="distribution" className="label">Distribution</label>
            <select id="distribution" name="distribution" className="input">
              <option value="nonexclusive">Nonexclusive licensing (Model A agreement)</option>
              <option value="free">Free distribution (Model C authorization)</option>
            </select>
          </div>
        </div>
        <fieldset className="grid gap-2 text-sm sm:grid-cols-2">
          <legend className="label">Content details</legend>
          <label className="flex items-center gap-2"><input type="checkbox" name="has_model_release" /> Model release on file</label>
          <label className="flex items-center gap-2"><input type="checkbox" name="has_property_release" /> Property release on file</label>
          <label className="flex items-center gap-2"><input type="checkbox" name="is_editorial_only" /> Editorial use only</label>
          <label className="flex items-center gap-2"><input type="checkbox" name="is_ai_generated" /> AI-generated</label>
          <label className="flex items-center gap-2"><input type="checkbox" name="is_materially_altered" /> Materially altered</label>
        </fieldset>
        <fieldset className="space-y-3 rounded-lg border border-ink-700 p-4">
          <legend className="px-1 text-sm font-semibold text-gold-300">Copyright declaration</legend>
          <div><label htmlFor="owner" className="label">Copyright owner</label><input id="owner" name="rights_owner_name" className="input" required minLength={2} /></div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="is_original_author" defaultChecked /> I am the original author</label>
          <div><label htmlFor="existing" className="label">Existing licenses affecting this media (if any)</label><textarea id="existing" name="existing_licenses_disclosure" className="input" /></div>
          <label className="flex items-start gap-2 text-sm text-ink-200"><input type="checkbox" name="accept_declaration" required className="mt-1" /> {DECLARATION}</label>
        </fieldset>
        {progress !== null && (
          <div aria-live="polite">
            <div className="h-2 overflow-hidden rounded-full bg-ink-700"><div className="h-full bg-gold-500 transition-all" style={{ width: `${progress}%` }} /></div>
            <p className="mt-1 text-xs text-ink-300">{progress < 100 ? `Uploading ${progress}%` : "Processing…"}</p>
          </div>
        )}
        <button className="btn-gold w-full" disabled={!file || progress !== null}>Upload and submit for review</button>
      </form>
    </div>
  );
}
