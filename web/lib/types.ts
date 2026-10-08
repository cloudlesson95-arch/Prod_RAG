// Response shapes of the RAG API (src/core/api.py and src/monitoring/stats.py)

export interface Health {
  status: string;
  model: string;
  revision: string | null;
  state_version: string | null;
  read_only: boolean;
}

export type RouteReason = "classifier" | "probe" | "version" | "floor" | "no_retrieval" | "llm";

export interface Passage {
  source: string;
  text: string;
  similarity: number | null;
}

export interface QueryResponse {
  question: string;
  answer: string;
  source: string | null; // "none" when answered without retrieval; null on a cache hit
  route_reason: RouteReason | null;
  router_confidence: number | null;
  probe_similarity: number | null;
  groundedness_score: number | null; // shown as "answer-context similarity"
  cache_hit: boolean;
  passages: Passage[];
}

export interface DemoUpload {
  doc_id: string;
  filename: string;
  chunks: number;
  expires_in: number; // seconds without use before the document is dropped
}

export interface DemoQueryResponse {
  question: string;
  answer: string;
  groundedness_score: number | null;
  passages: Passage[];
}

export interface EvalResult {
  id: number | null;
  query: string;
  passed: boolean;
  llm_answer: string;
}

export interface EvalRun {
  ts: string;
  run_type: "live" | "synthetic";
  revision: string | null;
  target_url: string;
  eval_model: string;
  precision_score: number;
  total_questions: number;
  successful_questions: number;
  passed_threshold: boolean;
  results: EvalResult[];
}

export interface EvalHistory {
  runs: EvalRun[];
}

export interface CorpusDocument {
  filename: string;
  chunk_count: number;
  file_size: number;
  ingested_at: string;
  questions: number;
}

export interface Corpus {
  state_version: string | null;
  total_chunks: number;
  documents: CorpusDocument[];
}

export interface RoutingStats {
  days: number;
  queries: number;
  cache_hits: number;
  live_eval_queries: number;
  by_source: Record<string, number>;
  by_reason: Record<string, number>;
  mean_groundedness: number | null;
  baseline: Record<string, number>;
  psi: number | null;
  psi_band: "stable" | "moderate" | "significant" | null;
  min_queries_for_psi: number;
}
