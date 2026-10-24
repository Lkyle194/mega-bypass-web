import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Mega Bypass",
  description: "Chaîne bypass → MEGA pilotée par votre Mac",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body>{children}</body>
    </html>
  );
}
