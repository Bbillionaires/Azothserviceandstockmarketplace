"use client";

import { useEffect } from "react";
import { rememberReferral } from "@/lib/cart";

export function RefCapture() {
  useEffect(() => rememberReferral(), []);
  return null;
}
