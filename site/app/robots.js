import { getSiteUrl } from "../lib/destinations";

export default function robots() {
  const siteUrl = getSiteUrl();
  return {
    rules: [{ userAgent: "*", allow: "/" }],
    sitemap: `${siteUrl}/sitemap.xml`,
  };
}
