import Link from "next/link";
import { getSiteUrl } from "../lib/destinations";
import "./globals.css";

export const metadata = {
  metadataBase: new URL(getSiteUrl()),
  title: {
    default: "EYV Travel - Destination Guides",
    template: "%s | EYV Travel",
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <header className="site-header">
          <div className="wrap" style={{ paddingBottom: 0 }}>
            <Link href="/">EYV Travel</Link>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
