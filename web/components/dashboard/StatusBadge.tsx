import type { Status } from "@/lib/dashboard";

const ICONS: Record<Status, string> = { good: "✓", warning: "!", serious: "▲", critical: "✕" };

/** A state shown as icon + label: the status color marks the icon only, so it never carries the meaning alone. */
export default function StatusBadge({ status, label }: { status: Status; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 font-medium">
      <span aria-hidden style={{ color: `var(--viz-${status})` }}>{ICONS[status]}</span>
      {label}
    </span>
  );
}
