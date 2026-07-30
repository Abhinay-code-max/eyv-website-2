import { getAllDestinations, getSiteUrl } from "../lib/destinations";

export default function sitemap() {
  const siteUrl = getSiteUrl();
  const destinations = getAllDestinations();

  return [
    { url: `${siteUrl}/`, changeFrequency: "weekly", priority: 1 },
    ...destinations.map((d) => ({
      url: `${siteUrl}/destinations/${d.slug}`,
      changeFrequency: "monthly",
      priority: 0.7,
    })),
  ];
}
