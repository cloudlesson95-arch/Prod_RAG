import type { ReactNode } from "react";

/** One headline number: a label, the value, and an optional line of context under it. */
export default function StatTile({ label, value, children }: { label: string; value: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-black/10 p-4 dark:border-white/15">
      <p className="text-xs opacity-70">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {children && <div className="mt-1 text-xs">{children}</div>}
    </div>
  );
}
