import { statusMeta } from "@/lib/format";

export function StatusBadge({ status, size = "md" }: { status: string | null | undefined; size?: "sm" | "md" | "lg" }) {
  const m = statusMeta(status);
  return (
    <span className={`badge ${m.cls} badge-${size}`} title={m.meaning} data-status={m.label}>
      <span aria-hidden="true" className="badge-icon">{m.icon}</span>
      {m.label}
    </span>
  );
}

export function FreshPill({ result, age }: { result?: string | null; age?: string }) {
  const r = result ?? "n/a";
  const icon = r === "fresh" ? "●" : r === "stale" ? "◐" : r === "missing" ? "○" : "·";
  return (
    <span className={`pill fresh-${r}`}>
      <span aria-hidden="true">{icon}</span> {r}
      {age ? <span className="pill-sub">{age}</span> : null}
    </span>
  );
}
