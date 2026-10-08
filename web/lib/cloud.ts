"use client";

import { useSyncExternalStore } from "react";

export type CloudId = "azure" | "aws";

export interface Cloud {
  id: CloudId;
  label: string;
  url: string;
}

// Literal process.env references: Next.js inlines NEXT_PUBLIC_ values at build time, and only in this form
const CONFIGURED: { id: CloudId; label: string; url: string | undefined }[] = [
  { id: "azure", label: "Azure", url: process.env.NEXT_PUBLIC_AZURE_API_URL },
  { id: "aws", label: "AWS", url: process.env.NEXT_PUBLIC_AWS_API_URL },
];

/** The clouds this build can talk to; one without a URL is left out. */
export const CLOUDS: Cloud[] = CONFIGURED.flatMap(({ id, label, url }) =>
  url ? [{ id, label, url: url.replace(/\/+$/, "") }] : [],
);

const STORAGE_KEY = "rag-cloud";
const CHANGE_EVENT = "rag-cloud-change";
let memoryChoice: string | null = null; // used when localStorage is blocked (private mode, disabled site data)

function readChoice(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return memoryChoice;
  }
}

function subscribe(onChange: () => void) {
  window.addEventListener("storage", onChange); // another tab switched
  window.addEventListener(CHANGE_EVENT, onChange); // this tab switched
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(CHANGE_EVENT, onChange);
  };
}

/** Remember the cloud the pages talk to, in this tab and the next visit. */
export function selectCloud(id: CloudId) {
  memoryChoice = id;
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Blocked storage: the choice lasts until the page is reloaded
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** A ?cloud=aws link selects that cloud, so a page can be shared for one cloud. */
export function selectCloudFromUrl() {
  const requested = new URLSearchParams(window.location.search).get("cloud");
  const match = CLOUDS.find((cloud) => cloud.id === requested);
  if (match) {
    selectCloud(match.id);
  }
}

/**
 * The selected cloud, or undefined when the build has no API URL.
 * Prerendering and the first browser render use the first configured cloud, then the remembered choice applies.
 */
export function useCloud(): Cloud | undefined {
  const choice = useSyncExternalStore(subscribe, readChoice, () => null);
  return CLOUDS.find((cloud) => cloud.id === choice) ?? CLOUDS[0];
}
