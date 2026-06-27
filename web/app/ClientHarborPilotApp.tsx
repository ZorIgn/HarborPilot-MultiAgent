"use client";

import dynamic from "next/dynamic";

const DynamicHarborPilotApp = dynamic(
  () => import("./HarborPilotApp").then((module) => module.HarborPilotApp),
  {
    ssr: false,
    loading: () => (
      <main className="island-shell loading-shell">
        <section className="loading-card">正在打开 HarborPilot 留学助手...</section>
      </main>
    ),
  }
);

export function ClientHarborPilotApp({ view }: { view: "home" | "assessment" | "programs" | "timeline" | "writing" | "agent" | "settings" }) {
  return <DynamicHarborPilotApp view={view} />;
}
