"use client";

import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatPercent, reasonLabel, shareRows } from "@/lib/dashboard";
import type { RoutingStats } from "@/lib/types";

const AXIS_TICK = { fill: "var(--viz-muted)", fontSize: 12 };
const TRAFFIC = { label: "Users' questions", color: "var(--viz-series-1)" };
const BASELINE = { label: "Training mix", color: "var(--viz-context)" };

function truncate(label: string) {
  return label.length > 24 ? `${label.slice(0, 23)}…` : label;
}

/**
 * Where users' questions were routed, next to the mix the classifier was trained on (the drift baseline), and
 * which rule decided. Emphasis form: users' traffic is the subject, the training mix is gray context.
 */
export default function RoutingSection({ stats }: { stats: RoutingStats }) {
  const routed = stats.queries - stats.cache_hits;
  if (routed === 0) {
    return (
      <p className="text-sm opacity-70">
        No routed user questions in the last {stats.days} days yet{stats.cache_hits ? ` (${stats.cache_hits} cache hits)` : ""}.
      </p>
    );
  }
  const rows = shareRows(stats);
  const reasons = Object.entries(stats.by_reason);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {[TRAFFIC, BASELINE].map((series) => (
          <span key={series.label} className="inline-flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: series.color }} />
            {series.label}
          </span>
        ))}
      </div>
      <div style={{ height: rows.length * 44 + 32 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" barGap={2} barCategoryGap={10} margin={{ top: 0, right: 48, bottom: 0, left: 0 }}>
            <CartesianGrid horizontal={false} stroke="var(--viz-grid)" />
            <XAxis type="number" domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tickFormatter={formatPercent} tick={AXIS_TICK}
                   stroke="var(--viz-axis)" />
            <YAxis type="category" dataKey="label" width={170} tickFormatter={truncate} tick={AXIS_TICK} stroke="var(--viz-axis)" />
            <Tooltip
              cursor={{ fill: "var(--viz-grid)", opacity: 0.5 }}
              content={({ active, payload }) => {
                const row = active ? payload?.[0]?.payload : undefined;
                return row ? (
                  <div className="rounded-md border border-black/10 bg-background px-3 py-2 text-xs shadow-sm dark:border-white/15">
                    <p className="opacity-70">{row.source}</p>
                    <p className="mt-1"><span className="font-semibold">{formatPercent(row.trafficShare)}</span> <span className="opacity-70">({row.traffic}) {TRAFFIC.label}</span></p>
                    <p><span className="font-semibold">{formatPercent(row.baselineShare)}</span> <span className="opacity-70">({row.baseline}) {BASELINE.label}</span></p>
                  </div>
                ) : null;
              }}
            />
            <Bar dataKey="trafficShare" name={TRAFFIC.label} fill={TRAFFIC.color} barSize={12} radius={[0, 4, 4, 0]} isAnimationActive={false}>
              <LabelList dataKey="trafficShare" position="right" formatter={(value) => formatPercent(Number(value))} fill="currentColor" fontSize={12} />
            </Bar>
            <Bar dataKey="baselineShare" name={BASELINE.label} fill={BASELINE.color} barSize={12} radius={[0, 4, 4, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <details className="text-sm">
        <summary className="cursor-pointer opacity-70 hover:opacity-100">Table view</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full">
            <thead className="text-left text-xs opacity-70">
              <tr>
                <th className="py-1 pr-3 font-normal">Source</th>
                <th className="py-1 pr-3 text-right font-normal">{TRAFFIC.label}</th>
                <th className="py-1 text-right font-normal">{BASELINE.label}</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {rows.map((row) => (
                <tr key={row.source} className="border-t border-black/10 dark:border-white/15">
                  <td className="py-1 pr-3 break-all" title={row.source}>{row.label}</td>
                  <td className="py-1 pr-3 text-right">{row.traffic} ({formatPercent(row.trafficShare)})</td>
                  <td className="py-1 text-right">{row.baseline} ({formatPercent(row.baselineShare)})</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <div>
        <h3 className="text-sm font-medium">What decided the route</h3>
        <table className="mt-1 text-sm">
          <tbody className="tabular-nums">
            {reasons.map(([reason, count]) => (
              <tr key={reason}>
                <td className="py-0.5 pr-6">{reasonLabel(reason)}</td>
                <td className="py-0.5 text-right">{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
