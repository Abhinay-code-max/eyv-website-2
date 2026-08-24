import { getAllDestinations, getSiteUrl } from "../lib/destinations";

export default function sitemap() {
  const siteUrl = getSiteUrl();
  const destinations = getAllDestinations();

  return [
    { url: `${siteUrl}/`, changeFrequency: "weekly", priority: 1 },
    { url: `${siteUrl}/privacy`, changeFrequency: "monthly", priority: 0.3 },
    { url: `${siteUrl}/terms`, changeFrequency: "monthly", priority: 0.3 },
    { url: `${siteUrl}/refund-policy`, changeFrequency: "monthly", priority: 0.3 },
    ...destinations.map((d) => ({
      url: `${siteUrl}/destinations/${d.slug}`,
      changeFrequency: "monthly",
      priority: 0.7,
    })),
  ];
}
