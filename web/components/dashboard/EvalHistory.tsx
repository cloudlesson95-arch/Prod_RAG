"use client";

import { Fragment, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, type LabelProps } from "recharts";

import StatusBadge from "@/components/dashboard/StatusBadge";
import { dayAxis, formatTime, scorePoints } from "@/lib/dashboard";
import type { EvalRun } from "@/lib/types";

const GATE = 80; // live-eval fails a deploy below this precision
const SERIES = [
  { key: "live", label: "Live (benchmark)", short: "Live", color: "var(--viz-series-1)" },
  { key: "synthetic", label: "Synthetic (generated)", short: "Synthetic", color: "var(--viz-series-2)" },
] as const;
const AXIS_TICK = { fill: "var(--viz-muted)", fontSize: 12 };

function formatDay(time: number) {
  return new Date(time).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Precision of each stored eval run over time, and the runs as a table with their per-question results. */
export default function EvalHistory({ runs }: { runs: EvalRun[] }) {
  const [openRun, setOpenRun] = useState<string | null>(null);
  if (runs.length === 0) {
    return <p className="text-sm opacity-70">No eval runs stored yet. The deploy gates and the daily collect-data job add them.</p>;
  }
  const points = scorePoints(runs);
  const axis = dayAxis(points.map((point) => point.time));
  const lastIndex = (key: "live" | "synthetic") =>
    points.reduce((last, point, index) => (point[key] != null ? index : last), -1);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {SERIES.map((series) => (
          <span key={series.key} className="inline-flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-0.5 w-4 rounded" style={{ background: series.color }} />
            {series.label}
          </span>
        ))}
      </div>
      <div className="h-60">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 72, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
            <XAxis
              dataKey="time"
              type="number"
              scale="time"
              domain={axis.domain}
              ticks={axis.ticks}
              tickFormatter={formatDay}
              tick={AXIS_TICK}
              stroke="var(--viz-axis)"
            />
            <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(value) => `${value}%`} tick={AXIS_TICK}
                   stroke="var(--viz-axis)" width={44} />
            <ReferenceLine y={GATE} stroke="var(--viz-muted)" strokeDasharray="4 4"
                           label={{ value: `${GATE}% gate`, position: "insideTopLeft", fill: "var(--viz-muted)", fontSize: 12 }} />
            <Tooltip
              cursor={{ stroke: "var(--viz-axis)" }}
              content={({ active, payload, label }) => active && payload?.length ? (
                <div className="rounded-md border border-black/10 bg-background px-3 py-2 text-xs shadow-sm dark:border-white/15">
                  <p className="opacity-70">{formatTime(new Date(Number(label)).toISOString())}</p>
                  {payload.map((item) => (
                    <p key={String(item.dataKey)} className="mt-1 flex items-center gap-1.5">
                      <span aria-hidden className="inline-block h-0.5 w-3 rounded" style={{ background: item.color }} />
                      <span className="font-semibold">{item.value}%</span>
                      <span className="opacity-70">{item.name}</span>
                    </p>
                  ))}
                </div>
              ) : null}
            />
            {SERIES.map((series) => (
              <Line
                key={series.key}
                dataKey={series.key}
                name={series.label}
                stroke={series.color}
                strokeWidth={2}
                dot={{ r: 4, fill: series.color, stroke: "var(--background)", strokeWidth: 2 }}
                activeDot={{ r: 5, stroke: "var(--background)", strokeWidth: 2 }}
                connectNulls
                isAnimationActive={false}
                label={(props: LabelProps) => props.index === lastIndex(series.key) ? (
                  <text x={Number(props.x) + 10} y={Number(props.y)} dy={4} fontSize={12} fill="currentColor">{series.short}</text>
                ) : <g />}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Stored eval runs, newest first</caption>
          <thead className="text-left text-xs opacity-70">
            <tr>
              <th className="py-1 pr-3 font-normal">When</th>
              <th className="py-1 pr-3 font-normal">Type</th>
              <th className="py-1 pr-3 font-normal">Revision</th>
              <th className="py-1 pr-3 text-right font-normal">Score</th>
              <th className="py-1 pr-3 font-normal">Result</th>
              <th className="py-1 font-normal">Questions</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const id = `${run.ts}-${run.run_type}`;
              const open = openRun === id;
              return (
                <Fragment key={id}>
                  <tr className="border-t border-black/10 dark:border-white/15" title={run.target_url}>
                    <td className="py-1.5 pr-3 whitespace-nowrap">{formatTime(run.ts)}</td>
                    <td className="py-1.5 pr-3">{run.run_type === "live" ? "Live" : "Synthetic"}</td>
                    <td className="py-1.5 pr-3 font-mono text-xs">{run.revision ? run.revision.slice(0, 7) : "–"}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{run.precision_score.toFixed(0)}%</td>
                    <td className="py-1.5 pr-3 whitespace-nowrap">
                      {run.passed_threshold
                        ? <StatusBadge status="good" label="Passed" />
                        : <StatusBadge status="critical" label="Failed" />}
                    </td>
                    <td className="py-1.5">
                      <button
                        type="button"
                        aria-expanded={open}
                        onClick={() => setOpenRun(open ? null : id)}
                        className="whitespace-nowrap tabular-nums underline underline-offset-4"
                      >
                        {run.successful_questions}/{run.total_questions} {open ? "▴" : "▾"}
                      </button>
                    </td>
                  </tr>
                  {open && (
                    <tr>
                      <td colSpan={6} className="pb-3">
                        <ol className="space-y-2 text-xs">
                          {run.results.map((result, index) => (
                            <li key={index} className="rounded-md border border-black/10 p-2 dark:border-white/15">
                              <StatusBadge status={result.passed ? "good" : "critical"} label={result.query} />
                              <p className="mt-1 whitespace-pre-wrap break-words opacity-80">{result.llm_answer}</p>
                            </li>
                          ))}
                        </ol>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
