"use client";

import { useEffect, useState } from "react";

import Markdown from "@/components/Markdown";
import PassageList from "@/components/PassageList";
import { api, ApiError, timed } from "@/lib/api";
import { useCloud } from "@/lib/cloud";
import { askWithReupload, checkDemoFile, SAMPLE_DOCUMENT } from "@/lib/demo";
import { errorMessage, formatScore } from "@/lib/format";
import type { DemoQueryResponse, DemoUpload } from "@/lib/types";

const EXAMPLES = ["What is this document about?", "Summarize it in three bullet points.", "What are the key numbers in it?"];

type Exchange = { id: string; question: string } & (
  | { state: "pending" }
  | { state: "done"; response: DemoQueryResponse; seconds: number; reuploaded: boolean }
  | { state: "error"; message: string }
);

/** Upload one document and ask about it. The file stays in this tab, so it can be sent again if the backend drops it. */
export default function DemoSandbox() {
  const cloud = useCloud();
  const [file, setFile] = useState<File | null>(null);
  const [doc, setDoc] = useState<DemoUpload | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0); // seconds until uploads are accepted again, after a 429
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [draft, setDraft] = useState("");
  const busy = uploading || exchanges.some((exchange) => exchange.state === "pending");

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((seconds) => seconds - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  function noteRateLimit(error: unknown) {
    if (error instanceof ApiError && error.status === 429) setCooldown(error.retryAfter ?? 60);
  }

  async function upload(picked: File) {
    if (!cloud) return;
    const problem = checkDemoFile(picked);
    if (problem) {
      setUploadError(problem);
      return;
    }
    setUploading(true);
    setUploadError(null);
    try {
      const uploaded = await api.uploadDemo(cloud.url, picked);
      setFile(picked);
      setDoc(uploaded);
      setExchanges([]); // a new document starts a new conversation
    } catch (error) {
      noteRateLimit(error);
      setUploadError(uploadMessage(error));
    } finally {
      setUploading(false);
    }
  }

  async function ask(question: string) {
    const text = question.trim();
    if (!text || !cloud || !file || !doc || busy) return;
    const id = crypto.randomUUID();
    const settle = (result: Exchange) => setExchanges((list) => list.map((item) => (item.id === id ? result : item)));

    setExchanges((list) => [{ id, question: text, state: "pending" }, ...list]);
    setDraft("");
    try {
      const { result, seconds } = await timed(() => askWithReupload(
        doc,
        (docId) => api.queryDemo(cloud.url, docId, text),
        () => api.uploadDemo(cloud.url, file),
      ));
      setDoc(result.doc);
      settle({ id, question: text, state: "done", response: result.response, seconds, reuploaded: result.reuploaded });
    } catch (error) {
      noteRateLimit(error);
      settle({ id, question: text, state: "error", message: errorMessage(error) });
    }
  }

  const canUpload = Boolean(cloud) && !busy && cooldown <= 0;
  const canAsk = Boolean(cloud && doc) && !busy;

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Demo sandbox</h1>
        <p className="mt-1 text-sm opacity-70">
          Upload a .txt, .md or .pdf (up to 2 MB) and ask about it. The document stays in the backend&apos;s memory for
          30 idle minutes and is never added to the shared corpus.
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label
            className={`rounded-md bg-foreground px-4 py-2 text-background ${canUpload ? "cursor-pointer" : "pointer-events-none opacity-40"}`}
          >
            {uploading ? "Uploading and indexing…" : doc ? "Replace document" : "Choose a file"}
            <input
              type="file"
              accept=".txt,.md,.pdf"
              className="sr-only"
              disabled={!canUpload}
              onChange={(event) => {
                const picked = event.target.files?.[0];
                event.target.value = ""; // choosing the same file again still triggers a change
                if (picked) void upload(picked);
              }}
            />
          </label>
          <button
            type="button"
            disabled={!canUpload}
            onClick={() => void upload(new File([SAMPLE_DOCUMENT.text], SAMPLE_DOCUMENT.name, { type: "text/plain" }))}
            className="underline underline-offset-4 disabled:opacity-40"
          >
            Try a sample document
          </button>
        </div>
        {uploadError && <p className="text-sm text-red-600">{uploadError}</p>}
        {cooldown > 0 && <p className="text-sm opacity-70">You can upload again in {cooldown} s.</p>}
        {doc && file && (
          <p className="text-sm">
            <span className="font-medium">{file.name}</span>
            <span className="opacity-70"> · {doc.chunks} {doc.chunks === 1 ? "chunk" : "chunks"} · kept for {Math.round(doc.expires_in / 60)} idle minutes</span>
          </p>
        )}
      </div>

      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(event) => {
          event.preventDefault();
          void ask(draft);
        }}
      >
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          maxLength={2000}
          disabled={!doc}
          placeholder={doc ? "Ask about the document…" : "Upload a document first"}
          aria-label="Question about the document"
          className="flex-1 rounded-md border border-black/15 bg-transparent px-3 py-2 disabled:opacity-40 dark:border-white/20"
        />
        <button
          type="submit"
          disabled={!draft.trim() || !canAsk}
          className="rounded-md bg-foreground px-4 py-2 text-background disabled:opacity-40"
        >
          Ask
        </button>
      </form>

      {doc && (
        <div className="flex flex-wrap gap-2 text-sm">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              disabled={!canAsk}
              onClick={() => void ask(example)}
              className="rounded-full border border-black/15 px-3 py-1 hover:bg-black/5 disabled:opacity-40 dark:border-white/20 dark:hover:bg-white/10"
            >
              {example}
            </button>
          ))}
        </div>
      )}

      <ol className="space-y-4" aria-live="polite">
        {exchanges.map((exchange) => (
          <li key={exchange.id} className="rounded-lg border border-black/10 p-4 dark:border-white/15">
            <p className="font-medium">{exchange.question}</p>
            {exchange.state === "pending" && <p className="mt-2 animate-pulse text-sm opacity-70">Thinking…</p>}
            {exchange.state === "error" && <p className="mt-2 text-sm text-red-600">{exchange.message}</p>}
            {exchange.state === "done" && (
              <>
                <div className="mt-2">
                  {exchange.response.answer.trim()
                    ? <Markdown text={exchange.response.answer} />
                    : <p className="text-sm opacity-70">The model returned an empty answer. Ask again.</p>}
                </div>
                <p className="mt-3 flex flex-wrap gap-x-3 text-xs opacity-80">
                  {exchange.response.groundedness_score != null && (
                    <span>
                      answer-context similarity <span className="font-mono">{formatScore(exchange.response.groundedness_score)}</span>
                    </span>
                  )}
                  <span className="opacity-70">{exchange.seconds.toFixed(1)} s</span>
                  {exchange.reuploaded && (
                    <span className="opacity-70">The backend had dropped the document, so it was uploaded again.</span>
                  )}
                </p>
                <PassageList passages={exchange.response.passages} />
              </>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

function uploadMessage(error: unknown): string {
  if (error instanceof ApiError && error.status >= 500) {
    return `The backend couldn't index the document (${error.status}). Try again in a moment.`;
  }
  return errorMessage(error);
}
