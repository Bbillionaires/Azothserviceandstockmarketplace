export type GalleryItem = {
  id: string; filename: string; media_type: string; status: string; preview_url: string | null; thumbnail_url: string | null;
  width: number | null; height: number | null; is_favorite: boolean; is_selected: boolean; processing_error: string | null;
};
export type GalleryComment = { id: string; item_id: string | null; author: string; body: string; is_revision_request: boolean; created_at: string };
export type Gallery = {
  id: string | null; title: string; message: string; client_name: string; status: string; allow_downloads: boolean;
  selection_limit: number | null; client_approved_at: string | null; expires_at: string | null; items: GalleryItem[];
  comments: GalleryComment[]; selected_count: number; creator_name: string;
  client_email?: string | null; has_password?: boolean; share_url?: string; project_id?: string | null; last_viewed_at?: string | null;
};
