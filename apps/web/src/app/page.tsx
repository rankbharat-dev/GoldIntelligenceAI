"use client";

import { OverviewPage } from "@/components/overview";
import { SimpleHome } from "@/components/simple/home";
import { useMode } from "@/lib/mode";

// "/" is the Simple-mode Home, or the chart-first Overview in Expert mode (also at /chart).
export default function HomePage() {
  return useMode() === "expert" ? <OverviewPage /> : <SimpleHome />;
}
