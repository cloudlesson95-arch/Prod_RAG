import { shortSource } from "./format";
import type { EvalRun, RoutingStats } from "./types";

/** A share as a whole percent: 0.8333 -> "83%". */
export function formatPercent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

/** File sizes the way people read them: 523 B, 22.1 KB, 4.1 MB. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** A timestamp in the reader's locale and time zone, e.g. "8 Oct 2026, 14:15". */
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** The newest run of one type (the API lists runs newest first). */
export function latestRun(runs: EvalRun[], type: EvalRun["run_type"]): EvalRun | undefined {
  return runs.find((run) => run.run_type === type);
}

/** One point per eval run, oldest first, for the score-over-time chart. */
export function scorePoints(runs: EvalRun[]): { time: number; live?: number; synthetic?: number }[] {
  return [...runs].reverse().map((run) => ({ time: Date.parse(run.ts), [run.run_type]: run.precision_score }));
}

/**
 * The score chart's time axis: whole local days around the runs, with one tick per day (or per few days, so there
 * are at most about 8). Several runs a day would otherwise repeat the same date under every point.
 */
export function dayAxis(times: number[]): { domain: [number, number]; ticks: number[] } {
  const start = new Date(Math.min(...times));
  start.setHours(0, 0, 0, 0);
  const end = new Date(Math.max(...times));
  end.setHours(24, 0, 0, 0); // the next local midnight
  const days = Math.round((end.getTime() - start.getTime()) / 86_400_000);
  const step = Math.max(1, Math.ceil(days / 8));
  const ticks: number[] = [];
  for (const day = new Date(start); day < end; day.setDate(day.getDate() + step)) {
    ticks.push(day.getTime());
  }
  return { domain: [start.getTime(), end.getTime()], ticks };
}

/** A routing source as people read it: "none" means the question was answered without retrieval. */
export function sourceLabel(source: string): string {
  return source === "none" ? "No retrieval" : shortSource(source);
}

export interface ShareRow {
  source: string;
  label: string;
  traffic: number;
  trafficShare: number;
  baseline: number;
  baselineShare: number;
}

/** Users' routed questions and the classifier's training mix as shares per source, largest first. */
export function shareRows(stats: Pick<RoutingStats, "by_source" | "baseline">): ShareRow[] {
  const sum = (counts: Record<string, number>) => Object.values(counts).reduce((total, n) => total + n, 0);
  const trafficTotal = sum(stats.by_source);
  const baselineTotal = sum(stats.baseline);
  const sources = new Set([...Object.keys(stats.baseline), ...Object.keys(stats.by_source)]);
  return [...sources]
    .map((source) => {
      const traffic = stats.by_source[source] ?? 0;
      const baseline = stats.baseline[source] ?? 0;
      return {
        source,
        label: sourceLabel(source),
        traffic,
        trafficShare: trafficTotal ? traffic / trafficTotal : 0,
        baseline,
        baselineShare: baselineTotal ? baseline / baselineTotal : 0,
      };
    })
    .sort((a, b) => Math.max(b.trafficShare, b.baselineShare) - Math.max(a.trafficShare, a.baselineShare)
      || a.label.localeCompare(b.label));
}

const REASON_LABELS: Record<string, string> = {
  classifier: "Classifier said retrieve",
  probe: "Close chunk overruled a no",
  version: "Question named a release",
  floor: "Unsure vote, no close chunk",
  no_retrieval: "General question",
  llm: "LLM router",
};

/** A short name for a routing reason (the chat page explains each one in a sentence). */
export function reasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? reason;
}

export type Status = "good" | "warning" | "serious" | "critical";

/** The status a PSI band stands for, or null when there's no PSI yet. */
export function psiStatus(band: RoutingStats["psi_band"]): { status: Status; label: string } | null {
  if (band === "stable") return { status: "good", label: "Stable" };
  if (band === "moderate") return { status: "warning", label: "Moderate drift" };
  if (band === "significant") return { status: "serious", label: "Significant drift" };
  return null;
}
