"use client";

import { HarborPilotApp } from "./HarborPilotApp";

export function ClientHarborPilotApp({ view }: { view: "home" | "assessment" | "programs" | "timeline" | "writing" | "agent" | "settings" }) {
  return <HarborPilotApp view={view} />;
}
