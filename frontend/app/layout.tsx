import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { AuthProvider } from "../lib/auth";
import { AuthNavSlot } from "../components/AuthNavSlot";

export const metadata: Metadata = {
  title: "Agent Orchestrator",
  description: "Factory-style multi-agent coding orchestrator",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <div className="min-h-screen">
            <header className="border-b border-line bg-white">
              <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
                <Link href="/missions" className="text-base font-semibold tracking-normal text-ink">
                  Agent Orchestrator
                </Link>
                <nav className="flex items-center gap-3 text-sm">
                  <Link className="text-slate-700 hover:text-ink" href="/missions">
                    Missions
                  </Link>
                  <Link
                    className="rounded-md bg-accent px-3 py-2 font-medium text-white hover:bg-[#17616f]"
                    href="/missions/new"
                  >
                    New mission
                  </Link>
                  <AuthNavSlot />
                </nav>
              </div>
            </header>
            <main className="mx-auto max-w-6xl px-6 py-6">{children}</main>
          </div>
        </AuthProvider>
      </body>
    </html>
  );
}
