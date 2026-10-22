export type CreatorSummary = {
  id: string;
  handle: string;
  display_name: string;
  avatar_url: string | null;
  verification_status: string;
};

export type MediaCard = {
  id: string;
  title: string;
  media_type: "photo" | "video";
  category: string;
  orientation: string | null;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  resolution_label: string | null;
  is_free: boolean;
  thumbnail_url: string | null;
  preview_url: string | null;
  creator: CreatorSummary;
  starting_price_cents: number | null;
  currency: string;
};

export type Price = {
  id: string;
  license_code: string;
  license_name: string;
  size_tier: string;
  price_cents: number;
  currency: string;
  subscription_credit_eligible: boolean;
};

export type MediaDetail = MediaCard & {
  description: string;
  keywords: string[];
  status: string;
  file_format: string | null;
  file_size_bytes: number | null;
  frame_rate: number | null;
  location_city: string | null;
  location_region: string | null;
  location_country: string | null;
  is_editorial_only: boolean;
  is_ai_generated: boolean;
  is_materially_altered: boolean;
  has_model_release: boolean;
  has_property_release: boolean;
  view_count: number;
  download_count: number;
  published_at: string | null;
  created_at: string;
  prices: Price[];
  free_license_codes: string[];
  files: { kind: string; url: string; content_type: string; width: number | null; height: number | null }[];
  processing_error: string | null;
  rejection_reason: string | null;
};

export type Creator = {
  id: string;
  handle: string;
  display_name: string;
  headline: string;
  bio: string;
  avatar_url: string | null;
  banner_url: string | null;
  categories: string[];
  specialties: string[];
  city: string | null;
  region: string | null;
  country_code: string | null;
  service_radius_km: number | null;
  remote_available: boolean;
  travel_available: boolean;
  website: string | null;
  verification_status: string;
  is_emerging_talent: boolean;
  is_featured: boolean;
  follower_count: number;
};

export type User = {
  id: string;
  email: string;
  display_name: string;
  status: string;
  email_verified: boolean;
  mfa_enabled: boolean;
  roles: string[];
  creator_handle: string | null;
};

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

export type LicenseType = {
  code: string;
  name: string;
  summary: string;
  is_free: boolean;
  is_exclusive: boolean;
  allows_commercial_use: boolean;
  requires_attribution: boolean;
  permitted_uses: string[];
  terms_version: string;
};

export type AgreementTemplate = {
  id: string;
  code: string;
  version: number;
  title: string;
  revenue_model: string;
  body_markdown: string;
  body_sha256: string;
  territory: string[];
  permitted_uses: string[];
  duration: string;
  withdrawal_terms: string;
  legal_review_status: string;
  creator_share_percent: number;
  initial_exclusive_share_percent: number | null;
  available_to_sign: boolean;
};

export type RightsGrant = {
  certificate_number: string;
  asset_id: string;
  asset_title: string;
  license_code: string;
  license_name: string;
  licensee_name: string;
  is_exclusive: boolean;
  territory: string[];
  permitted_uses: string[];
  starts_at: string;
  ends_at: string | null;
  price_cents: number;
  currency: string;
  terms_version: string;
  status: string;
  issued_at: string;
  creator_display_name: string;
  requires_attribution: boolean;
};
