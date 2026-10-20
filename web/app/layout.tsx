import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Nav } from "@/components/nav";
import "./globals.css";

const sans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Who's reviewing together? — 41M Amazon reviews",
  description:
    "An analysis of 41,135,700 Amazon reviews looking for accounts that appear to be reviewing as a group rather than independently.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${sans.variable} ${mono.variable} antialiased`}>
        <TooltipProvider>
          <div className="min-h-screen">
            <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur">
              <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-6 gap-y-2 px-6 py-3">
                <Link href="/" className="shrink-0">
                  <span className="block text-sm font-semibold tracking-tight">
                    Who&rsquo;s reviewing together?
                  </span>
                  <span className="block text-xs text-muted-foreground tabular">
                    41,135,700 Amazon reviews &middot; 3,035,045 accounts &middot; 1996&ndash;2014
                  </span>
                </Link>
                <Nav />
              </div>
            </header>
            <main className="mx-auto max-w-[1600px] px-6 py-8">{children}</main>
            <footer className="mx-auto max-w-[1600px] px-6 pb-10 pt-4 text-xs text-muted-foreground">
              Built from the McAuley/UCSD Amazon review dataset (2014 release), analysed
              entirely on one laptop. This tool surfaces accounts whose behaviour is
              statistically unusual. It is not proof that anyone was paid, and the data
              contains no answer key to check against.
            </footer>
          </div>
          <Toaster />
        </TooltipProvider>
      </body>
    </html>
  );
}
