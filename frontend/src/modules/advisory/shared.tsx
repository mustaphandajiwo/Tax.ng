// Pieces shared by the public directory and the signed-in advisory pages.
import type { ReactNode } from "react";
import { verificationText, type PublicAdviser, type Verification } from "./api";

export function VerifiedBadge({ v }: { v: Verification }) {
  if (v.status !== "verified") return <span className="pill pill--muted">{verificationText(v)}</span>;
  return (
    <span className="adv-badge" title={verificationText(v)}>
      <span className={`pill ${v.mode === "sandbox" ? "pill--warn" : "pill--ok"}`}>{v.mode === "sandbox" ? "Verified (sandbox)" : "Verified"}</span>
      <span className="muted small">{verificationText(v)}</span>
    </span>
  );
}

export function PractitionerNotice({ text }: { text: string }) {
  return (
    <p className="notice adv-notice" role="note">
      <strong>Practitioner of record.</strong> {text}
    </p>
  );
}

export function AdviserCard({ a, labels, action }: { a: PublicAdviser; labels: Record<string, string>; action?: ReactNode }) {
  return (
    <article className="card adv-card">
      <h3>{a.name}</h3>
      <p className="muted small">
        {[a.firm, a.location, a.state].filter(Boolean).join(" · ")}
      </p>
      <VerifiedBadge v={a.verification} />
      <p className="adv-specs">
        {a.specialisms.map((s) => (
          <span key={s} className="pill pill--muted">
            {labels[s] ?? s}
          </span>
        ))}
      </p>
      {action}
    </article>
  );
}
