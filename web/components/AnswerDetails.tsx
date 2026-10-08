import { formatScore, reasonText, routeLabel } from "@/lib/format";
import type { QueryResponse } from "@/lib/types";

/** How an answer was produced: the route and why, the router's scores, which cloud answered and how fast. */
export default function AnswerDetails({ response, cloud, seconds }: {
  response: QueryResponse;
  cloud: string;
  seconds: number;
}) {
  return (
    <div className="mt-3 space-y-1 text-xs">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="rounded-full border border-black/15 px-2 py-0.5 font-medium dark:border-white/20" title={response.source ?? ""}>
          {routeLabel(response)}
        </span>
        {!response.cache_hit && (
          <>
            <Metric label="router confidence" value={response.router_confidence} />
            <Metric label="closest chunk" value={response.probe_similarity} />
            <Metric label="answer-context similarity" value={response.groundedness_score} />
          </>
        )}
        <span className="opacity-70">
          {cloud} · {seconds.toFixed(1)} s
        </span>
      </div>
      <p className="opacity-70">{reasonText(response)}</p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | null }) {
  if (value == null) return null;
  return (
    <span className="opacity-80">
      {label} <span className="font-mono">{formatScore(value)}</span>
    </span>
  );
}
