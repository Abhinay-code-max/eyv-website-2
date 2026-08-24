"use client";

/**
 * Outbound link component for all links pointing from site/ (SEO app) to frontend/ (CRA app).
 * Automatically decorates the destination URL with the active PostHog distinct ID (ph_distinct_id)
 * to ensure cross-domain identity stitching and funnel continuity across separate domains or localhost ports.
 */
export default function PlanTripLink({ className, href, children, ...rest }) {
  const handleClick = (e) => {
    if (typeof window !== "undefined" && window.posthog && href) {
      try {
        const distinctId = window.posthog.get_distinct_id?.();
        if (distinctId) {
          e.preventDefault();
          const url = new URL(href, window.location.origin);
          url.searchParams.set("ph_distinct_id", distinctId);
          window.location.href = url.toString();
        }
      } catch (err) {
        // Fallback to default browser navigation if URL parsing fails
      }
    }
  };

  return (
    <a className={className} href={href} onClick={handleClick} {...rest}>
      {children}
    </a>
  );
}
