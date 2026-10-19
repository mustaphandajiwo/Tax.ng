// Health-check report view (HC-03 to HC-07). Findings by dimension only: there is
// no score, grade or total anywhere on this page. Unknown answers show as
// "Insufficient evidence", never as a failure, and the most severe items come first.
import { ReviewBadge } from "../../components/ui";
import { date } from "../../format";
import { DIMENSION_LABEL, type Cell, type Finding, type Report, type ReportLink } from "./api";

const CELL_LABEL: Record<Cell["status"], string> = {
  gap: "Possible gap",
  insufficient_evidence: "Insufficient evidence",
  ok: "No gap found",
  not_applicable: "Does not apply",
  not_assessed: "Not assessed",
};

export function cellTone(cell: Pick<Cell, "status" | "severity">): string {
  if (cell.status === "gap") return cell.severity === "high" ? "bad" : cell.severity === "medium" ? "warn" : "muted";
  if (cell.status === "ok") return "ok";
  return "muted";
}

function CellPill({ cell }: { cell: Cell }) {
  const text = cell.status === "gap" && cell.severity ? `${CELL_LABEL.gap} (${cell.severity})` : CELL_LABEL[cell.status];
  return <span className={`pill pill--${cellTone(cell)}`}>{text}</span>;
}

/** Public-site paths open on the main site; inside /app they need the site prefix. */
function href(link: ReportLink, sitePrefix: string): string {
  return `${sitePrefix}${link.path}`;
}

function FindingItem({ f, sitePrefix }: { f: Finding; sitePrefix: string }) {
  return (
    <li className={`hc-finding hc-finding--${f.status === "gap" ? f.severity : "unknown"}`}>
      <div className="hc-finding__head">
        <span className={`pill pill--${cellTone(f)}`}>{f.status === "gap" ? `${f.severity} severity` : "Insufficient evidence"}</span>
        <span className="pill pill--muted">{DIMENSION_LABEL[f.dimension] ?? f.dimension}</span>
        {f.review_recommended && <span className="pill pill--warn">Review recommended</span>}
      </div>
      <strong>{f.title}</strong>
      {f.question && (
        <span>
          {f.question} Your answer: {f.answer}
        </span>
      )}
      <span>
        <em>Why it matters:</em> {f.why_it_matters}
      </span>
      <span>
        <em>Next step:</em> {f.next_step}
      </span>
      {f.evidence_missing.length > 0 && <span>Evidence to gather: {f.evidence_missing.join("; ")}</span>}
      <span className="hc-links">
        <a href={`${sitePrefix}/laws/${f.provision}`}>Provision</a>
        {f.links.map((l) => (
          <a key={l.kind} href={href(l, sitePrefix)}>
            {l.label}
          </a>
        ))}
      </span>
    </li>
  );
}

export function ReportView({ report, sitePrefix = "/#" }: { report: Report; sitePrefix?: string }) {
  const dims = report.dimensions.map((d) => d.id);
  return (
    <div className="hc-report" aria-live="polite">
      <div className="notice notice--warn" role="note">
        <strong>Self-reported and indicative.</strong> {report.statement} {report.review_note}
      </div>
      <p className="muted small">
        Tax year {report.year} · generated {date(report.generated_at.slice(0, 10))} · rules {report.rules_version}
      </p>

      <h2>Findings by dimension</h2>
      <p className="small muted">Each dimension is reported on its own. They are not added together.</p>
      <div className="hc-dims">
        {report.dimensions.map((d) => (
          <div key={d.id} className="card hc-dim">
            <h3>{d.label}</h3>
            <p>
              <span className={`pill pill--${d.status === "gaps_found" ? (d.gaps.high ? "bad" : "warn") : d.status === "no_gaps_found" ? "ok" : "muted"}`}>
                {{ gaps_found: "Possible gaps", insufficient_evidence: "Insufficient evidence", no_gaps_found: "No gaps found", not_assessed: "Not assessed" }[d.status]}
              </span>
            </p>
            <ul className="small hc-counts">
              {d.gaps.high > 0 && <li>{d.gaps.high} high</li>}
              {d.gaps.medium > 0 && <li>{d.gaps.medium} medium</li>}
              {d.gaps.low > 0 && <li>{d.gaps.low} low</li>}
              {d.insufficient_evidence > 0 && <li>{d.insufficient_evidence} need more evidence</li>}
            </ul>
          </div>
        ))}
      </div>

      <h2>Obligations</h2>
      {report.obligations.length === 0 ? (
        <p>Based on your answers, none of the obligations we check apply to you for this year.</p>
      ) : (
        <div className="table-wrap">
          <table className="table hc-matrix">
            <thead>
              <tr>
                <th scope="col">Obligation</th>
                {dims.map((d) => (
                  <th key={d} scope="col">
                    {DIMENSION_LABEL[d]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {report.obligations.map((row) => (
                <tr key={row.id}>
                  <th scope="row">
                    {row.title}
                    <span className="step-note">{row.applies_because}</span>
                    {row.status === "applies" && row.next_due_date && (
                      <span className="step-note">
                        Next due {date(row.next_due_date)} ({row.due_rule}) <ReviewBadge status={row.due_date_review_status ?? "unverified"} />
                      </span>
                    )}
                    {row.status === "undetermined" && <span className="pill pill--muted">May apply</span>}
                    {row.note && <span className="step-note">{row.note}</span>}
                  </th>
                  {dims.map((d) => (
                    <td key={d}>
                      <CellPill cell={row.cells[d]} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>What we found</h2>
      {report.findings.length === 0 ? (
        <p>No gaps or open questions were found from your answers.</p>
      ) : (
        <ol className="list hc-findings">
          {report.findings.map((f) => (
            <FindingItem key={f.id} f={f} sitePrefix={sitePrefix} />
          ))}
        </ol>
      )}

      {report.missing_evidence.length > 0 && (
        <>
          <h2>Evidence to gather</h2>
          <ul>
            {report.missing_evidence.map((m) => (
              <li key={m.obligation}>
                <strong>{m.obligation_title}:</strong> {m.documents.join("; ")}
              </li>
            ))}
          </ul>
        </>
      )}

      <h2>Next steps</h2>
      <ol>
        {report.next_steps.map((s) => (
          <li key={s.text}>
            {s.text}{" "}
            {s.links.map((l) => (
              <a key={l.kind} className="small" href={href(l, sitePrefix)}>
                {l.label}
              </a>
            ))}
          </li>
        ))}
      </ol>

      <h2>Sources</h2>
      <ul className="cites">
        {report.citations.map((c) => (
          <li key={c.id}>
            <a href={`${sitePrefix}/laws/${c.id}`}>{c.title}</a> <span className="muted small">{c.instrument}, section {c.section}</span>{" "}
            <ReviewBadge status={c.review_status} />
          </li>
        ))}
      </ul>
    </div>
  );
}
