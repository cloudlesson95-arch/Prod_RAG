import { describe, expect, it, vi } from "vitest";

import { ApiError } from "./api";
import { askWithReupload, checkDemoFile, DEMO_MAX_BYTES } from "./demo";

const DOC = { doc_id: "old", filename: "notes.txt", chunks: 3, expires_in: 1800 };
const FRESH = { ...DOC, doc_id: "new" };
const ANSWER = { question: "Q?", answer: "A.", groundedness_score: 0.7, passages: [] };

describe("askWithReupload", () => {
  it("asks once when the backend still has the document", async () => {
    const ask = vi.fn().mockResolvedValue(ANSWER);
    const reupload = vi.fn();

    expect(await askWithReupload(DOC, ask, reupload)).toEqual({ response: ANSWER, doc: DOC, reuploaded: false });
    expect(reupload).not.toHaveBeenCalled();
  });

  it("uploads the file again after a 404 and retries once with the new document", async () => {
    const ask = vi.fn().mockRejectedValueOnce(new ApiError(404, "Demo document not found or expired")).mockResolvedValueOnce(ANSWER);
    const reupload = vi.fn().mockResolvedValue(FRESH);

    const result = await askWithReupload(DOC, ask, reupload);

    expect(ask.mock.calls).toEqual([["old"], ["new"]]);
    expect(result).toEqual({ response: ANSWER, doc: FRESH, reuploaded: true });
  });

  it("gives up when the retry fails too", async () => {
    const ask = vi.fn().mockRejectedValue(new ApiError(404, "gone"));
    const reupload = vi.fn().mockResolvedValue(FRESH);

    await expect(askWithReupload(DOC, ask, reupload)).rejects.toMatchObject({ status: 404 });
    expect(reupload).toHaveBeenCalledTimes(1);
  });

  it("doesn't upload again for other errors", async () => {
    const ask = vi.fn().mockRejectedValue(new ApiError(500, "Internal server error processing query"));
    const reupload = vi.fn();

    await expect(askWithReupload(DOC, ask, reupload)).rejects.toMatchObject({ status: 500 });
    expect(reupload).not.toHaveBeenCalled();
  });
});

describe("checkDemoFile", () => {
  it("accepts the backend's file types up to 2 MB, whatever the case of the extension", () => {
    expect(checkDemoFile({ name: "Notes.PDF", size: 1000 })).toBeNull();
    expect(checkDemoFile({ name: "notes.md", size: DEMO_MAX_BYTES })).toBeNull();
  });

  it("names the problem otherwise", () => {
    expect(checkDemoFile({ name: "tool.exe", size: 10 })).toContain("Unsupported");
    expect(checkDemoFile({ name: "big.txt", size: DEMO_MAX_BYTES + 1 })).toContain("2 MB");
    expect(checkDemoFile({ name: "empty.txt", size: 0 })).toContain("empty");
  });
});
