export type OrderLine = {
  id: string;
  asset_id: string;
  asset_title: string;
  thumbnail_url: string | null;
  license_name: string;
  size_tier: string;
  licensee_name: string;
  unit_price_cents: number;
  tax_cents: number;
  status: string;
  certificate_number: string | null;
  refunded_cents?: number;
  price_listing_id?: string;
};

export type Order = {
  id: string;
  status: string;
  currency: string;
  subtotal_cents: number;
  tax_cents: number;
  total_cents: number;
  checkout_url: string | null;
  created_at: string;
  paid_at: string | null;
  lines: OrderLine[];
  purpose?: string;
  project_id?: string | null;
};
