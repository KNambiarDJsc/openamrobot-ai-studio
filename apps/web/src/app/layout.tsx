import type { Metadata } from "next";

import { Shell } from "@/components/Shell";

import "./globals.css";

export const metadata: Metadata = {
  title: "OpenAMRobot AI Studio",
  description: "Read-only, evidence-backed diagnostics for the OpenAMRobot ROS 2 digital twin",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
