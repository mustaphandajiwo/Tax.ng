// Shows a calculation result: headline, steps, bands, citations, caveats,
// provenance, and a worksheet download (CALC-08).
import type { CalcResult } from "../api";
import { naira, percent, REGIME_LABEL } from "../format";
import { Link } from "../router";
import { Notice, ReviewBadge } from "./ui";

export interface Headline {
  label: string;
  value: string;
}

function csvCell(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

export function downloadWorksheet(result: CalcResult): void {
  const rows: string[][] = [
    ["tax.ng worksheet", result.calculator.toUpperCase()],
    ["Regime", REGIME_LABEL[result.regime] ?? result.regime],
    ["Period", result.period],
    ["Rules version", result.rules_version],
    ["Engine version", result.engine_version],
    ["Review status", result.review_status],
    [],
    ["Step", "Amount (NGN)", "Note"],
    ...result.steps.map((s) => [s.label, s.amount ?? "", s.note ?? ""]),
  ];
  if (result.bands.length) {
    rows.push([], ["Band from", "Band to", "Rate", "Taxable", "Tax"]);
    result.bands.forEach((b) => rows.push([b.lower, b.upper ?? "", b.rate, b.taxable, b.tax]));
  }
  rows.push([], ["Citations"], ...result.citations.map((c) => [c]));
  rows.push([], ["Assumptions"], ...result.assumptions.map((a) => [a]));
  const csv = rows.map((r) => r.map(csvCell).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `taxng-${result.calculator}-worksheet.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export function ResultView({ result, headlines }: { result: CalcResult; headlines: Headline[] }) {
  return (
    <section className="result" aria-live="polite" aria-label="Result">
      <div className="result__head">
        {headlines.map((h) => (
          <div key={h.label} className="stat">
            <span className="stat__label">{h.label}</span>
            <span className="stat__value">{h.value}</span>
          </div>
        ))}
      </div>

      <p className="muted small">
        {REGIME_LABEL[result.regime] ?? result.regime} · {result.period}
      </p>

      {result.warnings.map((w) => (
        <Notice key={w} tone="warn">
          {w}
        </Notice>
      ))}

      <h3>How this was worked out</h3>
      <table className="table">
        <tbody>
          {result.steps.map((s, i) => (
            <tr key={i}>
              <th scope="row">
                {s.label}
                {s.note && <span className="step-note">{s.note}</span>}
              </th>
              <td className="num">{s.amount !== null ? naira(s.amount) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {result.bands.length > 0 && (
        <>
          <h3>Tax by band</h3>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Band</th>
                <th scope="col">Rate</th>
                <th scope="col" className="num">
                  Taxed
                </th>
                <th scope="col" className="num">
                  Tax
                </th>
              </tr>
            </thead>
            <tbody>
              {result.bands.map((b) => (
                <tr key={b.lower}>
                  <td>{b.upper ? `${naira(b.lower)} to ${naira(b.upper)}` : `Above ${naira(b.lower)}`}</td>
                  <td>{percent(b.rate)}</td>
                  <td className="num">{naira(b.taxable)}</td>
                  <td className="num">{naira(b.tax)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <div className="result__foot">
        <div>
          <h3>Sources</h3>
          <ul className="cites">
            {result.citations.map((c) => (
              <li key={c}>
                <Link to={`/laws/${c}`}>{c}</Link>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Assumptions</h3>
          <ul>
            {result.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      </div>

      <div className="provenance">
        <ReviewBadge status={result.review_status} />
        <span>
          Rules {result.rules_version} · engine {result.engine_version}
        </span>
        <button type="button" className="btn btn--ghost" onClick={() => downloadWorksheet(result)}>
          Download worksheet
        </button>
      </div>
    </section>
  );
}
