"use client";

import { useState, type ReactNode } from "react";

import CorpusTable from "@/components/dashboard/CorpusTable";
import EvalHistory from "@/components/dashboard/EvalHistory";
import RoutingSection from "@/components/dashboard/RoutingSection";
import StatTile from "@/components/dashboard/StatTile";
import StatusBadge from "@/components/dashboard/StatusBadge";
import { api } from "@/lib/api";
import { useCloud, type Cloud } from "@/lib/cloud";
import { formatPercent, latestRun, psiStatus } from "@/lib/dashboard";
import { formatScore } from "@/lib/format";
import { useDashboardData } from "@/lib/useDashboardData";

/** Eval history, routing and corpus of the selected cloud. Switching clouds starts fresh (keyed by its URL). */
export default function Dashboard() {
  const cloud = useCloud();
  const [attempt, setAttempt] = useState(0);
  if (!cloud) {
    return <p className="text-sm text-red-600">No backend URL configured.</p>;
  }
  return <CloudDashboard key={cloud.url} cloud={cloud} attempt={attempt} onRefresh={() => setAttempt((n) => n + 1)} />;
}

function CloudDashboard({ cloud, attempt, onRefresh }: { cloud: Cloud; attempt: number; onRefresh: () => void }) {
  const evals = useDashboardData(api.evalHistory, cloud.url, attempt);
  const routing = useDashboardData(api.routing, cloud.url, attempt);
  const corpus = useDashboardData(api.corpus, cloud.url, attempt);
  const refreshing = evals.refreshing || routing.refreshing || corpus.refreshing;

  const live = evals.data ? latestRun(evals.data.runs, "live") : undefined;
  const stats = routing.data;
  const routed = stats ? stats.queries - stats.cache_hits : 0;
  const psi = stats ? psiStatus(stats.psi_band) : null;

  return (
    <section className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Dashboard</h1>
          <p className="mt-1 text-sm opacity-70">
            {cloud.label}: eval runs, how questions were routed in the last 7 days, and the indexed corpus. The backend
            recomputes these at most once a minute.
          </p>
        </div>
        <button type="button" onClick={onRefresh} disabled={refreshing} className="text-sm underline underline-offset-4 disabled:opacity-40">
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <div className={`grid grid-cols-2 gap-3 transition-opacity lg:grid-cols-5 ${refreshing ? "opacity-50" : ""}`}>
        <StatTile label="Latest live eval" value={live ? `${live.precision_score.toFixed(0)}%` : "–"}>
          {live && <StatusBadge status={live.passed_threshold ? "good" : "critical"} label={live.passed_threshold ? "Passed" : "Failed"} />}
          {live?.revision && <span className="ml-2 font-mono opacity-70">{live.revision.slice(0, 7)}</span>}
        </StatTile>
        <StatTile label="User questions, 7 days" value={stats ? stats.queries.toLocaleString() : "–"}>
          {stats && <span className="opacity-70">plus {stats.live_eval_queries} from live-eval</span>}
        </StatTile>
        <StatTile label="Cache hit rate" value={stats && stats.queries ? formatPercent(stats.cache_hits / stats.queries) : "–"}>
          {stats && <span className="opacity-70">{stats.cache_hits} of {stats.queries} questions</span>}
        </StatTile>
        <StatTile label="Routing drift (PSI)" value={stats?.psi != null ? stats.psi.toFixed(2) : "–"}>
          {psi
            ? <StatusBadge status={psi.status} label={psi.label} />
            : stats && <span className="opacity-70">Needs {stats.min_queries_for_psi} routed questions (has {routed})</span>}
        </StatTile>
        <StatTile label="Answer-context similarity" value={formatScore(stats?.mean_groundedness)}>
          <span className="opacity-70">Mean; a topic match, not a fact check</span>
        </StatTile>
      </div>

      <Panel title="Eval runs" note="Precision of the stored live-eval runs: the benchmark gate after each deploy, and generated questions after each daily batch." load={evals}>
        {evals.data && <EvalHistory runs={evals.data.runs} />}
      </Panel>
      <Panel title="Routing" note="Where users' questions went, next to the classifier's training mix, which the drift score compares them with. Cache hits and live-eval traffic are left out." load={routing}>
        {stats && <RoutingSection stats={stats} />}
      </Panel>
      <Panel title="Corpus" note={corpus.data?.state_version ? `Snapshot ${corpus.data.state_version}` : "Local index (no snapshot)"} load={corpus}>
        {corpus.data && <CorpusTable corpus={corpus.data} />}
      </Panel>
    </section>
  );
}

function Panel({ title, note, load, children }: {
  title: string;
  note: string;
  load: { loading: boolean; refreshing: boolean; error?: string };
  children: ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="text-sm opacity-70">{note}</p>
      </div>
      {load.error && <p className="text-sm text-red-600">{load.error}</p>}
      {load.loading ? <p className="animate-pulse text-sm opacity-70">Loading…</p> : (
        <div className={`transition-opacity ${load.refreshing ? "opacity-50" : ""}`}>{children}</div>
      )}
    </section>
  );
}
