"use client";

import { useEffect, useState } from "react";
import { api } from "./api";

export type PublicConfig = {
  features: { paid_licensing: boolean; exclusive_licensing: boolean; payment_provider: string };
};

let cached: Promise<PublicConfig> | null = null;

export function usePublicConfig() {
  const [config, setConfig] = useState<PublicConfig | null>(null);
  useEffect(() => {
    cached ??= api<PublicConfig>("/config/public");
    cached.then(setConfig).catch(() => setConfig(null));
  }, []);
  return config;
}
