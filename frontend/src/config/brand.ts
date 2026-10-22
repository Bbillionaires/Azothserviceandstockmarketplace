/**
 * Central branding. Every user-visible brand string comes from here so the
 * final marketplace name, domain, logo and colors can change via environment
 * variables (and the CSS tokens in globals.css) without code changes.
 */
export const brand = {
  name: process.env.NEXT_PUBLIC_BRAND_NAME || "Lumen & Reel",
  tagline:
    process.env.NEXT_PUBLIC_BRAND_TAGLINE ||
    "Licensed photography, footage and production talent worldwide.",
  logoUrl: process.env.NEXT_PUBLIC_BRAND_LOGO_URL || "",
  supportEmail: process.env.NEXT_PUBLIC_SUPPORT_EMAIL || "support@example.com",
  heroVideoUrl: process.env.NEXT_PUBLIC_HERO_VIDEO_URL || "",
  parentCompany: "One United Enterprise LLC",
  poweredBy: "Azoth Digital",
};
