"use client";

import { useEffect, useState } from "react";

import { ApiError } from "./api";

/**
 * Load one dashboard section from the selected cloud. A refresh (a new `attempt`) keeps the previous data on
 * screen, flagged as `refreshing` so it can be dimmed, instead of flashing an empty state.
 */
export function useDashboardData<T>(fetcher: (baseUrl: string) => Promise<T>, baseUrl: string, attempt: number) {
  const [state, setState] = useState<{ attempt: number; data?: T; error?: string } | null>(null);

  useEffect(() => {
    let active = true;
    fetcher(baseUrl).then(
      (data) => active && setState({ attempt, data }),
      (error) => active && setState((previous) => ({
        attempt,
        data: previous?.data,
        error: error instanceof ApiError ? error.detail : String(error),
      })),
    );
    return () => {
      active = false;
    };
  }, [fetcher, baseUrl, attempt]);

  return {
    data: state?.data,
    error: state?.error,
    loading: state === null,
    refreshing: state !== null && state.attempt !== attempt,
  };
}
