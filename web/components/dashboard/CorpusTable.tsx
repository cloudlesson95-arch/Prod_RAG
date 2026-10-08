import { formatBytes, formatTime } from "@/lib/dashboard";
import { shortSource } from "@/lib/format";
import type { Corpus } from "@/lib/types";

/** The documents of the snapshot this backend instance serves. */
export default function CorpusTable({ corpus }: { corpus: Corpus }) {
  if (corpus.documents.length === 0) {
    return <p className="text-sm opacity-70">The index is empty.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">Indexed documents</caption>
        <thead className="text-left text-xs opacity-70">
          <tr>
            <th className="py-1 pr-3 font-normal">Document</th>
            <th className="py-1 pr-3 text-right font-normal">Chunks</th>
            <th className="py-1 pr-3 text-right font-normal">Size</th>
            <th className="py-1 pr-3 text-right font-normal">Generated questions</th>
            <th className="py-1 font-normal">Indexed</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {corpus.documents.map((doc) => (
            <tr key={doc.filename} className="border-t border-black/10 dark:border-white/15">
              <td className="py-1.5 pr-3 break-all" title={doc.filename}>{shortSource(doc.filename)}</td>
              <td className="py-1.5 pr-3 text-right">{doc.chunk_count.toLocaleString()}</td>
              <td className="py-1.5 pr-3 text-right whitespace-nowrap">{formatBytes(doc.file_size)}</td>
              <td className="py-1.5 pr-3 text-right">{doc.questions}</td>
              <td className="py-1.5 whitespace-nowrap">{formatTime(doc.ingested_at)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot className="tabular-nums">
          <tr className="border-t border-black/20 font-medium dark:border-white/25">
            <td className="py-1.5 pr-3">{corpus.documents.length} documents</td>
            <td className="py-1.5 pr-3 text-right">{corpus.total_chunks.toLocaleString()}</td>
            <td colSpan={3} />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
