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

/** What an answer was based on, in a few words. */
export function routeLabel(response: Pick<QueryResponse, "cache_hit" | "source">): string {
  if (response.cache_hit) return "Semantic cache";
  if (!response.source || response.source === "none") return "General knowledge";
  return `Retrieved from ${shortSource(response.source)}`;
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
  if (response.cache_hit) return "A very similar question was answered before; this is the stored answer.";
  return response.route_reason ? REASONS[response.route_reason] : "";
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
  if (error.status >= 500) {
    return `The backend couldn't answer (${error.status}). The usual cause is the LLM's free-tier rate limit: try again in a few seconds.`;
  }
  return error.detail;
}
