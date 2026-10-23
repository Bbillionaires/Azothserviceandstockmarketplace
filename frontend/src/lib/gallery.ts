export type GalleryItem = {
  id: string; filename: string; media_type: string; status: string; preview_url: string | null; thumbnail_url: string | null;
  width: number | null; height: number | null; is_favorite: boolean; is_selected: boolean; processing_error: string | null; download_unlocked?: boolean;
};
export type GalleryComment = { id: string; item_id: string | null; author: string; body: string; is_revision_request: boolean; created_at: string };
export type Gallery = {
  id: string | null; title: string; message: string; client_name: string; status: string; allow_downloads: boolean;
  selection_limit: number | null; client_approved_at: string | null; expires_at: string | null; items: GalleryItem[];
  comments: GalleryComment[]; selected_count: number; creator_name: string;
  download_price_cents: number | null; currency: string; print_options: PrintOption[]; payments_enabled: boolean;
  client_email?: string | null; has_password?: boolean; share_url?: string; project_id?: string | null; last_viewed_at?: string | null;
};
export type PrintOption = { id: string; name: string; price_cents: number };
export type GalleryOrderLine = { item_id: string; kind: "digital" | "print"; description: string; quantity: number; unit_price_cents: number };
export type GalleryOrder = {
  id: string; order_id: string; client_name: string; client_email?: string; status: string; currency: string;
  subtotal_cents: number; tax_cents: number; total_cents: number; carrier: string | null; tracking_number: string | null;
  shipped_at: string | null; created_at: string; paid_at: string | null; items: GalleryOrderLine[];
  shipping_address?: Record<string, string> | null;
};
