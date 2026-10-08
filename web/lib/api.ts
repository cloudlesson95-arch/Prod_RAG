import type {
  Corpus,
  DemoQueryResponse,
  DemoUpload,
  EvalHistory,
  Health,
  QueryResponse,
  RoutingStats,
} from "./types";

// Matches the Lambda timeout: a cold start plus multi-hop answering can take minutes
export const REQUEST_TIMEOUT_MS = 300_000;

/** A failed API call: the HTTP status, or 0 when no response arrived (network, CORS or timeout). */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly retryAfter: number | null; // seconds, from a 429's Retry-After header

  constructor(status: number, detail: string, retryAfter: number | null = null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.retryAfter = retryAfter;
  }
}

/** Turn a non-2xx response into an ApiError with FastAPI's detail message and any Retry-After seconds. */
export async function toApiError(response: Response): Promise<ApiError> {
  let detail = response.statusText || `HTTP ${response.status}`;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body?.detail)) {
      // FastAPI's 422: a list of validation errors
      detail = body.detail.map((error: { msg?: string }) => error.msg).filter(Boolean).join("; ");
    }
  } catch {
    // Not JSON: keep the status text
  }
  const retryAfter = Number(response.headers.get("Retry-After"));
  return new ApiError(response.status, detail, retryAfter > 0 ? retryAfter : null);
}

async function request<T>(baseUrl: string, path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, { ...init, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === "TimeoutError";
    throw new ApiError(0, timedOut
      ? "The backend didn't answer within 5 minutes"
      : "Can't reach the backend (offline, still starting, or blocked by CORS)");
  }
  if (!response.ok) {
    throw await toApiError(response);
  }
  return (await response.json()) as T;
}

/** Run a request and measure how long it took, for the "x.x s" shown next to answers. */
export async function timed<T>(call: () => Promise<T>): Promise<{ result: T; seconds: number }> {
  const started = performance.now();
  const result = await call();
  return { result, seconds: (performance.now() - started) / 1000 };
}

function postJson(body: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

/** One function per endpoint; baseUrl is the selected cloud's API URL. */
export const api = {
  health: (baseUrl: string) => request<Health>(baseUrl, "/health"),

  query: (baseUrl: string, question: string) => request<QueryResponse>(baseUrl, "/query", postJson({ question })),

  uploadDemo: (baseUrl: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DemoUpload>(baseUrl, "/demo/documents", { method: "POST", body: form });
  },

  queryDemo: (baseUrl: string, docId: string, question: string) =>
    request<DemoQueryResponse>(baseUrl, `/demo/documents/${encodeURIComponent(docId)}/query`, postJson({ question })),

  evalHistory: (baseUrl: string, limit = 30) => request<EvalHistory>(baseUrl, `/stats/eval-history?limit=${limit}`),

  corpus: (baseUrl: string) => request<Corpus>(baseUrl, "/stats/corpus"),

  routing: (baseUrl: string, days = 7) => request<RoutingStats>(baseUrl, `/stats/routing?days=${days}`),
};
