import type { Metadata } from "next";
import "animal-island-ui/style";
import "./globals.css";

export const metadata: Metadata = {
  title: "HarborPilot 港新硕士申请辅助平台",
  description: "用于背景评估、港新项目分档、逐项目时间线和文书素材整理。"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
