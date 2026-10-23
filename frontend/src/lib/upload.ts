import { api } from "./api";

/**
 * Direct-to-storage uploads. The API hands out an upload session; the browser
 * PUTs the file straight to object storage (a presigned URL in production, a
 * same-origin endpoint in development) with progress; the caller then
 * completes the upload with the purpose-specific endpoint and the session id.
 * Large videos never pass through the API server.
 */
export type UploadPurpose = "media" | "deliverable" | "gallery_item";

type UploadSession = { id: string; upload_url: string; method: string; headers: Record<string, string> };

export async function uploadFile(
  file: File,
  purpose: UploadPurpose,
  targetId?: string,
  onProgress?: (percent: number) => void,
): Promise<string> {
  const session = await api<UploadSession>("/uploads", {
    method: "POST",
    json: {
      purpose,
      target_id: targetId ?? null,
      filename: file.name,
      size_bytes: file.size,
      content_type: file.type || "application/octet-stream",
    },
  });
  const sameOrigin = session.upload_url.startsWith("/");
  await new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(session.method, session.upload_url);
    for (const [k, v] of Object.entries(session.headers)) xhr.setRequestHeader(k, v);
    if (sameOrigin) {
      xhr.withCredentials = true;
      xhr.setRequestHeader("X-Requested-With", "fetch");
    }
    xhr.upload.onprogress = (ev) => ev.lengthComputable && onProgress?.(Math.round((ev.loaded / ev.total) * 100));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve();
      let msg = `Upload failed (${xhr.status})`;
      try {
        const body = JSON.parse(xhr.responseText);
        if (typeof body.detail === "string") msg = body.detail;
      } catch {}
      reject(new Error(msg));
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(file);
  });
  return session.id;
}
