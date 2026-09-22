"use client";

import { useSyncExternalStore } from "react";

// Simple / Expert mode (requirement 2026-09-22_simple-mode-ui.md). Simple is the default:
// goal-first pages in plain Hinglish. Expert shows every research page as before.
// Stored per browser only — a viewing preference, never research state.

export type Mode = "simple" | "expert";
const KEY = "ci-mode";
const listeners = new Set<() => void>();

function read(): Mode {
  try {
    return window.localStorage.getItem(KEY) === "expert" ? "expert" : "simple";
  } catch {
    return "simple";
  }
}

export function setMode(m: Mode) {
  try {
    window.localStorage.setItem(KEY, m);
  } catch {
    /* storage blocked: the switch still works for this page view */
  }
  current = m;
  listeners.forEach((l) => l());
}

let current: Mode | null = null;

function subscribe(l: () => void) {
  listeners.add(l);
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) {
      current = read();
      l();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(l);
    window.removeEventListener("storage", onStorage);
  };
}

export function useMode(): Mode {
  return useSyncExternalStore(
    subscribe,
    () => (current ??= read()),
    () => "simple",
  );
}
