import { describe, expect, it } from "vitest";

import { dayAxis, formatBytes, formatPercent, latestRun, psiStatus, reasonLabel, scorePoints, shareRows, sourceLabel } from "./dashboard";
import type { EvalRun } from "./types";

function run(ts: string, run_type: EvalRun["run_type"], precision_score: number): EvalRun {
  return { ts, run_type, precision_score, revision: null, target_url: "", eval_model: "groq", total_questions: 10,
           successful_questions: 9, passed_threshold: precision_score >= 80, results: [] };
}

const RUNS = [  // newest first, as the API sends them
  run("2026-10-08T10:00:00+00:00", "synthetic", 40),
  run("2026-10-08T09:00:00+00:00", "live", 90),
  run("2026-10-07T09:00:00+00:00", "live", 80),
];

describe("eval runs", () => {
  it("finds the newest run of a type and plots runs oldest first", () => {
    expect(latestRun(RUNS, "live")?.precision_score).toBe(90);
    expect(latestRun([], "live")).toBeUndefined();
    expect(scorePoints(RUNS)).toEqual([
      { time: Date.parse("2026-10-07T09:00:00+00:00"), live: 80 },
      { time: Date.parse("2026-10-08T09:00:00+00:00"), live: 90 },
      { time: Date.parse("2026-10-08T10:00:00+00:00"), synthetic: 40 },
    ]);
  });
});

describe("dayAxis", () => {
  // Local-time dates, so the test passes in any time zone
  const at = (day: number, hour = 0, minute = 0) => new Date(2026, 9, day, hour, minute).getTime();

  it("spans whole days with one tick per day, however many runs a day has", () => {
    expect(dayAxis([at(6, 6, 20), at(7, 6, 20), at(7, 18), at(8, 6, 30)])).toEqual({
      domain: [at(6), at(9)],
      ticks: [at(6), at(7), at(8)],
    });
  });

  it("keeps a single run on a one-day axis and thins long ranges to about 8 ticks", () => {
    expect(dayAxis([at(8, 12)])).toEqual({ domain: [at(8), at(9)], ticks: [at(8)] });
    expect(dayAxis([at(1), at(30, 12)]).ticks.length).toBeLessThanOrEqual(8);
  });
});

describe("shareRows", () => {
  it("turns counts into shares per source, including sources only one side has, largest first", () => {
    const rows = shareRows({ by_source: { "cat-facts.txt": 3, none: 1 }, baseline: { none: 38, "cat-facts.txt": 2 } });

    expect(rows.map((row) => [row.label, row.traffic, row.trafficShare, row.baseline])).toEqual([
      ["No retrieval", 1, 0.25, 38],
      ["cat-facts.txt", 3, 0.75, 2],
    ]);
    expect(rows[0].baselineShare).toBeCloseTo(0.95);
  });

  it("gives zero shares when there's no traffic yet", () => {
    expect(shareRows({ by_source: {}, baseline: { none: 1 } })[0].trafficShare).toBe(0);
  });
});

describe("labels", () => {
  it("formats percents, sizes, sources, reasons and PSI bands", () => {
    expect([formatPercent(0.8333), formatPercent(1)]).toEqual(["83%", "100%"]);
    expect([formatBytes(523), formatBytes(22657), formatBytes(4294418)]).toEqual(["523 B", "22.1 KB", "4.1 MB"]);
    expect([sourceLabel("none"), sourceLabel("ingested/batch/notes.md")]).toEqual(["No retrieval", "notes.md"]);
    expect([reasonLabel("probe"), reasonLabel("unknown")]).toEqual(["Close chunk overruled a no", "unknown"]);
    expect(psiStatus("significant")).toEqual({ status: "serious", label: "Significant drift" });
    expect(psiStatus(null)).toBeNull();
  });
});
