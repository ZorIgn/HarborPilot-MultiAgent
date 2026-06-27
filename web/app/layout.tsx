import type { Metadata } from "next";
import "animal-island-ui/style";
import "./globals.css";

export const metadata: Metadata = {
  title: "HarborPilot AI",
  description: "Multi-agent admissions planning console for Hong Kong and Singapore."
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
