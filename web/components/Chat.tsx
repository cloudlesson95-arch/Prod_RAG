"use client";

import { useState } from "react";

import AnswerDetails from "@/components/AnswerDetails";
import Markdown from "@/components/Markdown";
import PassageList from "@/components/PassageList";
import { api, timed } from "@/lib/api";
import { useCloud } from "@/lib/cloud";
import { errorMessage } from "@/lib/format";
import type { QueryResponse } from "@/lib/types";

// One question per document type, plus one that needs no retrieval
const EXAMPLES = [
  "What is a group of cats called?",
  "How many people visited the Oakhaven Pumpkin Festival in 2025?",
  "What does ALLOW_MODEL_REQUESTS default to?",
  "What changed in the latest Pydantic AI release?",
  "What is 2345 * 849?",
];

type Exchange = { id: string; question: string; cloud: string } & (
  | { state: "pending" }
  | { state: "done"; response: QueryResponse; seconds: number }
  | { state: "error"; message: string }
);

/** Questions to the shared corpus, newest first. Kept while you visit other pages; gone on reload. */
export default function Chat() {
  const cloud = useCloud();
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [draft, setDraft] = useState("");
  const busy = exchanges.some((exchange) => exchange.state === "pending");

  async function ask(question: string) {
    const text = question.trim();
    if (!text || !cloud || busy) return;
    const id = crypto.randomUUID();
    const settle = (result: Exchange) => setExchanges((list) => list.map((item) => (item.id === id ? result : item)));

    setExchanges((list) => [{ id, question: text, cloud: cloud.label, state: "pending" }, ...list]);
    setDraft("");
    try {
      const { result: response, seconds } = await timed(() => api.query(cloud.url, text));
      settle({ id, question: text, cloud: cloud.label, state: "done", response, seconds });
    } catch (error) {
      settle({ id, question: text, cloud: cloud.label, state: "error", message: errorMessage(error) });
    }
  }

  function retry(failed: Exchange) {
    setExchanges((list) => list.filter((item) => item.id !== failed.id));
    void ask(failed.question);
  }

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Chat</h1>
        <p className="mt-1 text-sm opacity-70">
          Ask the shared corpus: cat facts, a fictional town&apos;s records, the Pydantic AI docs and its latest release notes.
        </p>
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
          placeholder="Ask a question…"
          aria-label="Question"
          className="flex-1 rounded-md border border-black/15 bg-transparent px-3 py-2 dark:border-white/20"
        />
        <button
          type="submit"
          disabled={!draft.trim() || !cloud || busy}
          className="rounded-md bg-foreground px-4 py-2 text-background disabled:opacity-40"
        >
          Ask
        </button>
      </form>

      <div className="flex flex-wrap gap-2 text-sm">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            disabled={!cloud || busy}
            onClick={() => void ask(example)}
            className="rounded-full border border-black/15 px-3 py-1 hover:bg-black/5 disabled:opacity-40 dark:border-white/20 dark:hover:bg-white/10"
          >
            {example}
          </button>
        ))}
      </div>

      <details className="text-sm">
        <summary className="cursor-pointer opacity-70 hover:opacity-100">What do the numbers mean?</summary>
        <dl className="mt-2 space-y-2 opacity-80">
          <div>
            <dt className="font-medium">router confidence</dt>
            <dd>The classifier&apos;s probability for its own vote. Uncalibrated: a rough signal, not a true probability.</dd>
          </div>
          <div>
            <dt className="font-medium">closest chunk</dt>
            <dd>Cosine similarity of the corpus chunk closest to the question. It decides which document is searched.</dd>
          </div>
          <div>
            <dt className="font-medium">answer-context similarity</dt>
            <dd>
              Cosine similarity between the answer and its best passage: a topic match, not a fact check.
              Short factual answers (a number, a name) score low even when correct.
            </dd>
          </div>
        </dl>
      </details>

      <ol className="space-y-4" aria-live="polite">
        {exchanges.map((exchange) => (
          <li key={exchange.id} className="rounded-lg border border-black/10 p-4 dark:border-white/15">
            <p className="font-medium">{exchange.question}</p>
            {exchange.state === "pending" && (
              <p className="mt-2 animate-pulse text-sm opacity-70">
                Thinking… Multi-hop retrieval can take 10-30 s, and the first question after a quiet spell also wakes
                the backend.
              </p>
            )}
            {exchange.state === "error" && (
              <div className="mt-2 text-sm">
                <p className="text-red-600">{exchange.message}</p>
                <button type="button" disabled={busy} onClick={() => retry(exchange)} className="mt-1 underline underline-offset-4 disabled:opacity-40">
                  Ask again
                </button>
              </div>
            )}
            {exchange.state === "done" && (
              <>
                <div className="mt-2">
                  {exchange.response.answer.trim()
                    ? <Markdown text={exchange.response.answer} />
                    : <p className="text-sm opacity-70">The model returned an empty answer. Ask again.</p>}
                </div>
                <AnswerDetails response={exchange.response} cloud={exchange.cloud} seconds={exchange.seconds} />
                <PassageList passages={exchange.response.passages} />
              </>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
