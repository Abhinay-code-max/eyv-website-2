import { ImageResponse } from "next/og";
import { getAllDestinations, getDestinationBySlug } from "../../../lib/destinations";

// No real destination photography exists anywhere in this app's data (see
// the original content inventory) - rather than omit og:image or fake a
// stock photo, this generates a real branded card per destination at build
// time. Same static-generation model as the page itself.
//
// Deliberately no generateImageMetadata() here - that's for generating
// MULTIPLE image variants for the SAME page. One was added by mistake
// during testing and it returned all 65 destinations' worth of image
// metadata for every single page (confirmed: mumbai's page emitted 65
// og:image tags, one per destination, not just its own). A single
// colocated opengraph-image file already gets exactly one image per
// generated [slug] automatically, keyed off that route's own params.
export const dynamicParams = false;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Without its own generateStaticParams, this image route rendered as a
// single dynamic (on-demand) function ignoring the parent [slug] page's
// static params entirely (confirmed via the build output showing
// "ƒ /destinations/-/opengraph-image ... Dynamic" instead of one static
// image per slug) - it needs the same static param list as the page route.
export function generateStaticParams() {
  return getAllDestinations().map((d) => ({ slug: d.slug }));
}

export default async function OgImage({ params }) {
  const { slug } = await params;
  const dest = getDestinationBySlug(slug);
  const name = dest?.name ?? "EYV Travel";
  const subtitle = dest ? [dest.country, dest.type].filter(Boolean).join(" · ") : "";

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "linear-gradient(135deg, #17322D 0%, #2B6E64 100%)",
          padding: "72px",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", fontSize: 30, color: "#BFE3DA", letterSpacing: 2, textTransform: "uppercase" }}>
          EYV Travel
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", fontSize: 76, fontWeight: 700, color: "#FFFFFF", lineHeight: 1.1 }}>
            {name}
          </div>
          {subtitle && (
            <div style={{ display: "flex", fontSize: 32, color: "#D8ECE7", marginTop: 18 }}>{subtitle}</div>
          )}
        </div>
      </div>
    ),
    { ...size }
  );
}
