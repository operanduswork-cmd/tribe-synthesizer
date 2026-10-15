import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";

import "./globals.css";

import { AppShell } from "@/components/shell/app-shell";
import { Providers } from "@/components/shell/providers";
import { copy } from "@/lib/copy";

// Geist and Geist Mono are self-hosted through next/font (the geist package): no external loads.

export const metadata: Metadata = {
  title: { default: copy.app.title, template: `%s · ${copy.app.name}` },
  description: copy.app.description,
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fafafa" },
    { media: "(prefers-color-scheme: dark)", color: "#0b0b0c" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" suppressHydrationWarning className={`${GeistSans.variable} ${GeistMono.variable} h-full`}>
      <body className="min-h-full">
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
