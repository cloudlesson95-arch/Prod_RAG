import { ApiError } from "./api";
import type { Passage, QueryResponse, RouteReason } from "./types";

/** Two decimals, or a dash when the API sent no value. */
export function formatScore(value: number | null | undefined): string {
  return value == null ? "–" : value.toFixed(2);
}

/** A source's file name without its folders (ingested/batch/notes.md -> notes.md). */
export function shortSource(source: string): string {
  return source.split("/").pop() || source;
}

function sourceRoute(source: string | null): string {
  if (!source || source === "none") return "General knowledge";
  return `Retrieved from ${shortSource(source)}`;
}

/** What an answer was based on, in a few words; a cache hit also names its original route when it was stored. */
export function routeLabel(response: Pick<QueryResponse, "cache_hit" | "source">): string {
  if (!response.cache_hit) return sourceRoute(response.source);
  return response.source ? `Semantic cache · ${sourceRoute(response.source)}` : "Semantic cache";
}

const REASONS: Record<RouteReason, string> = {
  classifier: "The classifier judged this a question about the documents.",
  probe: "The classifier said no, but a document chunk was close enough to search anyway.",
  version: "The question names a release, so that release's notes were searched.",
  floor: "An unsure retrieval vote and no close chunk, so it was answered without searching.",
  no_retrieval: "A general question, answered without searching the documents.",
  llm: "The LLM router chose the source.",
};

/** Why the router decided what it did, in plain language. */
export function reasonText(response: Pick<QueryResponse, "cache_hit" | "route_reason">): string {
  const reason = response.route_reason ? REASONS[response.route_reason] : "";
  if (!response.cache_hit) return reason;
  const cached = "A very similar question was answered before; this is the stored answer.";
  return reason ? `${cached} How it was routed then: ${reason}` : cached;
}

/** Index of the passage most similar to the answer, or -1 when none was scored. */
export function bestPassage(passages: Passage[]): number {
  let best = -1;
  passages.forEach((passage, index) => {
    if (passage.similarity != null && (best < 0 || passage.similarity > (passages[best].similarity ?? -Infinity))) {
      best = index;
    }
  });
  return best;
}

/** A message for a failed request that tells the user what to do. */
export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return String(error);
  if (error.status === 503 && error.retryAfter != null) {
    return `The language model's free-tier rate limit was reached. Try again in ${error.retryAfter} s.`;
  }
  if (error.status === 502) return "The model returned an empty answer. Ask again.";
  if (error.status >= 500) {
    return `The backend couldn't answer (${error.status}). Try again in a moment.`;
  }
  return error.detail;
}
