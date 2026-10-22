export const SERVICE_CATEGORIES = [
  "commercial_production", "documentary", "weddings", "corporate_video", "interviews", "podcasts", "music_videos",
  "real_estate", "drone_services", "product_photography", "social_media_content", "events", "sports",
  "hospitality", "news_editorial", "video_editing", "photo_editing", "animation", "motion_graphics",
  "short_films", "promotional_campaigns",
];

export const RIGHTS_LABEL: Record<string, string> = {
  exclusive: "Exclusive to the client",
  nonexclusive: "Nonexclusive",
  custom: "Custom agreement",
};

export type CreatorMini = {
  id: string; handle: string; display_name: string; avatar_url: string | null; verification_status: string;
  city: string | null; country_code: string | null;
};

export type ProjectRequest = {
  id: string; kind: "custom_project" | "shot_request"; title: string; category: string; description: string;
  location_city: string | null; location_region: string | null; location_country: string | null; remote_ok: boolean;
  budget_min_cents: number | null; budget_max_cents: number | null; currency: string; deadline: string | null;
  rights_preference: string; visibility: string; status: string; proposal_count: number; created_at: string;
  deliverables?: string; reference_urls?: string[]; client_name?: string; is_owner?: boolean;
  my_proposal?: Proposal | null; is_invited?: boolean; has_storefront?: boolean; project_id?: string | null;
};

export type ProposalMilestone = { title: string; description?: string; amount_cents: number; due_in_days?: number | null };

export type Proposal = {
  id: string; request_id: string; creator: CreatorMini; cover_letter: string; total_cents: number; currency: string;
  milestones: ProposalMilestone[]; delivery_days: number; revisions_included: number; rights_type: string;
  rights_terms: string; status: string; updated_at: string;
  rating: { average: number; count: number; completed_projects: number };
};

export type Package = {
  id: string; creator_id: string; title: string; description: string; category: string; deliverables: string;
  price_cents: number; currency: string; delivery_days: number; revisions_included: number; rights_type: string;
  rights_terms: string; is_active: boolean;
};

export type Deliverable = { id: string; filename: string; size_bytes: number; content_type: string; note: string; created_at: string };

export type ProjectMilestone = {
  id: string; position: number; title: string; description: string; amount_cents: number; due_date: string | null;
  status: string; funded_at: string | null; submitted_at: string | null; auto_approve_at: string | null;
  approved_at: string | null; revisions_used: number; released_cents: number; refunded_cents: number;
  deliverables: Deliverable[]; revision_requests: { note: string; created_at: string }[];
};

export type Project = {
  id: string; title: string; description: string; status: string; currency: string; total_cents: number;
  revisions_included: number; rights_type: string; rights_terms: string; acceptance_evidence: Record<string, unknown>;
  commission_percent: number; role: "client" | "creator" | "staff"; creator: CreatorMini; client_name: string;
  request_id: string | null; package_id: string | null; conversation_id: string | null; created_at: string;
  completed_at: string | null; milestones: ProjectMilestone[];
  disputes: { id: string; milestone_id: string; reason: string; description: string; status: string; opened_by_me: boolean; resolution_note: string | null; created_at: string }[];
  reviews: { direction: string; rating: number; body: string; created_at: string }[];
  auto_approve_days: number;
};

export function budgetText(r: { budget_min_cents: number | null; budget_max_cents: number | null; currency: string }, fmt: (c: number, cur: string) => string) {
  if (r.budget_min_cents && r.budget_max_cents) return `${fmt(r.budget_min_cents, r.currency)} – ${fmt(r.budget_max_cents, r.currency)}`;
  if (r.budget_max_cents) return `Up to ${fmt(r.budget_max_cents, r.currency)}`;
  if (r.budget_min_cents) return `From ${fmt(r.budget_min_cents, r.currency)}`;
  return "Budget open";
}

export const fileSize = (n: number) => (n > 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.ceil(n / 1e3)} KB`);
