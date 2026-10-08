import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** LLM answers are Markdown: bold, lists and often tables. Raw HTML in them is shown as text, never rendered. */
export default function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}
