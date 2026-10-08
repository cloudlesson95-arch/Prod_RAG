"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { CLOUDS, selectCloud, selectCloudFromUrl, useCloud, type Cloud } from "@/lib/cloud";
import type { Health } from "@/lib/types";

const PAGES = [
  { href: "/", label: "Chat" },
  { href: "/demo", label: "Demo" },
  { href: "/dashboard", label: "Dashboard" },
];

export default function Header() {
  const pathname = usePathname();
  const cloud = useCloud();

  useEffect(() => selectCloudFromUrl(), []);

  return (
    <header className="border-b border-black/10 dark:border-white/15">
      <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <Link href="/" className="font-semibold">
          Prod RAG
        </Link>
        <nav className="flex gap-4 text-sm">
          {PAGES.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              aria-current={pathname === href ? "page" : undefined}
              className={pathname === href ? "font-medium underline underline-offset-4" : "opacity-70 hover:opacity-100"}
            >
              {label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm">
          <CloudSwitcher selected={cloud} />
          {cloud && <BackendStatus key={cloud.url} cloud={cloud} />}
        </div>
      </div>
    </header>
  );
}

function CloudSwitcher({ selected }: { selected: Cloud | undefined }) {
  if (CLOUDS.length === 0) {
    return <span className="text-red-600">No backend URL configured</span>;
  }
  return (
    <div role="group" aria-label="Backend cloud" className="flex overflow-hidden rounded-md border border-black/15 dark:border-white/20">
      {CLOUDS.map((cloud) => (
        <button
          key={cloud.id}
          type="button"
          aria-pressed={cloud.id === selected?.id}
          onClick={() => selectCloud(cloud.id)}
          className={`px-3 py-1 ${cloud.id === selected?.id ? "bg-foreground text-background" : "hover:bg-black/5 dark:hover:bg-white/10"}`}
        >
          {cloud.label}
        </button>
      ))}
    </div>
  );
}

type Status =
  | { state: "checking"; slow: boolean }
  | { state: "online"; health: Health }
  | { state: "offline"; message: string };

// After this long without an answer, the backend is most likely scaling up from zero
const SLOW_AFTER_MS = 3_000;

/** Keyed by the cloud's URL, so switching clouds starts a fresh check. */
function BackendStatus({ cloud }: { cloud: Cloud }) {
  const [status, setStatus] = useState<Status>({ state: "checking", slow: false });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    const slowTimer = setTimeout(() => {
      if (active) setStatus((current) => (current.state === "checking" ? { state: "checking", slow: true } : current));
    }, SLOW_AFTER_MS);
    api.health(cloud.url).then(
      (health) => active && setStatus({ state: "online", health }),
      (error) => active && setStatus({ state: "offline", message: error instanceof ApiError ? error.detail : String(error) }),
    );
    return () => {
      active = false;
      clearTimeout(slowTimer);
    };
  }, [cloud.url, attempt]);

  if (status.state === "checking") {
    return (
      <span className="flex items-center gap-2">
        <Dot color="bg-amber-400 animate-pulse" />
        {status.slow ? "Waking up the backend (about a minute)…" : "Checking…"}
      </span>
    );
  }
  if (status.state === "offline") {
    return (
      <span className="flex items-center gap-2" title={status.message}>
        <Dot color="bg-red-500" />
        Unreachable
        <button
          type="button"
          className="underline underline-offset-4"
          onClick={() => {
            setStatus({ state: "checking", slow: false });
            setAttempt((n) => n + 1);
          }}
        >
          Retry
        </button>
      </span>
    );
  }
  const { revision, state_version: stateVersion } = status.health;
  return (
    <span className="flex items-center gap-2" title={`Snapshot ${stateVersion ?? "local"}`}>
      <Dot color="bg-emerald-500" />
      Online{revision ? ` · ${revision.slice(0, 7)}` : ""}
    </span>
  );
}

function Dot({ color }: { color: string }) {
  return <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}
