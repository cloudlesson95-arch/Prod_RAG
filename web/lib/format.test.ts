import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import { bestPassage, errorMessage, formatScore, reasonText, routeLabel, shortSource } from "./format";

describe("routeLabel", () => {
  it("names the cache, general knowledge or the searched file", () => {
    expect(routeLabel({ cache_hit: true, source: null })).toBe("Semantic cache");
    expect(routeLabel({ cache_hit: false, source: "none" })).toBe("General knowledge");
    expect(routeLabel({ cache_hit: false, source: "ingested/batch/github-releases.md" }))
      .toBe("Retrieved from github-releases.md");
  });

  it("keeps the original route on a cache hit with stored details", () => {
    expect(routeLabel({ cache_hit: true, source: "cat-facts.txt" })).toBe("Semantic cache · Retrieved from cat-facts.txt");
    expect(routeLabel({ cache_hit: true, source: "none" })).toBe("Semantic cache · General knowledge");
  });
});

describe("reasonText", () => {
  it("explains cache hits and each routing reason", () => {
    expect(reasonText({ cache_hit: true, route_reason: null })).toContain("answered before");
    expect(reasonText({ cache_hit: false, route_reason: "probe" })).toContain("close enough");
    expect(reasonText({ cache_hit: false, route_reason: null })).toBe("");
  });

  it("adds the original reason to a cache hit", () => {
    expect(reasonText({ cache_hit: true, route_reason: "classifier" })).toBe(
      "A very similar question was answered before; this is the stored answer. " +
      "How it was routed then: The classifier judged this a question about the documents.");
  });
});

describe("bestPassage", () => {
  it("picks the most similar scored passage", () => {
    const passages = [0.4, null, 0.7, 0.6].map((similarity) => ({ source: "a.txt", text: "", similarity }));
    expect(bestPassage(passages)).toBe(2);
  });

  it("returns -1 when nothing was scored", () => {
    expect(bestPassage([{ source: "a.txt", text: "", similarity: null }])).toBe(-1);
    expect(bestPassage([])).toBe(-1);
  });
});

describe("formatScore and shortSource", () => {
  it("formats scores to two decimals and strips folders", () => {
    expect([formatScore(0.6789), formatScore(null)]).toEqual(["0.68", "–"]);
    expect(shortSource("ingested/batch/quokkas.md")).toBe("quokkas.md");
  });
});

describe("errorMessage", () => {
  it("gives server errors a plain message and passes other details through", () => {
    expect(errorMessage(new ApiError(500, "Internal server error processing query")))
      .toBe("The backend couldn't answer (500). Try again in a moment.");
    expect(errorMessage(new ApiError(400, "Question cannot be empty"))).toBe("Question cannot be empty");
    expect(errorMessage(new ApiError(0, "Can't reach the backend"))).toBe("Can't reach the backend");
  });

  it("names the rate limit's wait and an empty answer", () => {
    expect(errorMessage(new ApiError(503, "The language model's rate limit was reached; try again in 7 s", 7)))
      .toBe("The language model's free-tier rate limit was reached. Try again in 7 s.");
    expect(errorMessage(new ApiError(503, "Stats are unavailable right now; try again shortly")))
      .toBe("The backend couldn't answer (503). Try again in a moment.");
    expect(errorMessage(new ApiError(502, "The model returned an empty answer; ask again")))
      .toBe("The model returned an empty answer. Ask again.");
  });
});
