import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AurionProviders } from "./providers";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Aurion Clinical AI — Admin Portal",
  description:
    "Administration and compliance portal for Aurion Clinical AI pilot.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // `suppressHydrationWarning` is the standard next-themes pattern
    // — the provider sets `<html class="dark">` on mount, which
    // technically diverges from the server-rendered (theme-less)
    // HTML. The warning suppression is scoped to <html> and doesn't
    // affect any child component's hydration checks.
    <html lang="en" suppressHydrationWarning>
      <body className={inter.className}>
        <AurionProviders>{children}</AurionProviders>
      </body>
    </html>
  );
}
