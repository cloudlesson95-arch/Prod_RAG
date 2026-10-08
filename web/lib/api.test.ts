import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, toApiError } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

describe("toApiError", () => {
  it("uses FastAPI's detail message and the Retry-After seconds", async () => {
    const error = await toApiError(jsonResponse(429, { detail: "Too many demo uploads" }, { "Retry-After": "12" }));

    expect(error).toBeInstanceOf(ApiError);
    expect([error.status, error.detail, error.retryAfter]).toEqual([429, "Too many demo uploads", 12]);
  });

  it("joins the messages of a 422 validation error", async () => {
    const error = await toApiError(jsonResponse(422, { detail: [{ msg: "too long" }, { msg: "required" }] }));

    expect(error.detail).toBe("too long; required");
    expect(error.retryAfter).toBeNull();
  });

  it("falls back to the status text when the body isn't JSON", async () => {
    const error = await toApiError(new Response("<html>Bad Gateway</html>", { status: 502, statusText: "Bad Gateway" }));

    expect([error.status, error.detail]).toEqual([502, "Bad Gateway"]);
  });
});

describe("api", () => {
  it("posts the question as JSON to the cloud's /query", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { answer: "A clowder." }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await api.query("https://rag.example.io", "What is a group of cats called?");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://rag.example.io/query");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ question: "What is a group of cats called?" });
    expect(result.answer).toBe("A clowder.");
  });

  it("turns an HTTP error into an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(404, { detail: "Demo document not found or expired" })));

    await expect(api.queryDemo("https://rag.example.io", "abc", "Hi?")).rejects.toMatchObject({ status: 404 });
  });

  it("reports a network failure as status 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(api.health("https://rag.example.io")).rejects.toMatchObject({ status: 0 });
  });
});
