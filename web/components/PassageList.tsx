import { bestPassage, formatScore, shortSource } from "@/lib/format";
import type { Passage } from "@/lib/types";

/** The chunks an answer was generated from, collapsed by default, with the most similar one marked. */
export default function PassageList({ passages }: { passages: Passage[] }) {
  if (passages.length === 0) return null;
  const best = bestPassage(passages);
  return (
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer opacity-70 hover:opacity-100">
        {passages.length} {passages.length === 1 ? "passage" : "passages"} used
      </summary>
      <ol className="mt-2 space-y-2">
        {passages.map((passage, index) => (
          <li
            key={index}
            className={`rounded-md border p-2 ${index === best ? "border-emerald-500/70" : "border-black/10 dark:border-white/15"}`}
          >
            <div className="flex flex-wrap justify-between gap-2 text-xs opacity-70">
              <span title={passage.source}>{shortSource(passage.source)}</span>
              <span>
                similarity {formatScore(passage.similarity)}
                {index === best ? " · best match" : ""}
              </span>
            </div>
            <p className="mt-1 whitespace-pre-wrap break-words">{passage.text}</p>
          </li>
        ))}
      </ol>
    </details>
  );
}
