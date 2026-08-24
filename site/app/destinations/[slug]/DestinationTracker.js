"use client";

import { useEffect } from "react";

export default function DestinationTracker({ slug }) {
  useEffect(() => {
    if (typeof window !== "undefined" && window.posthog && slug) {
      window.posthog.capture("destination_page_viewed", {
        destination_slug: slug,
      });
    }
  }, [slug]);

  return null;
}
