// Public-site pages for the compliance module: the health-check landing page
// (HC-01, HC-07) and the CALC-06 calculators. The check itself runs in the
// signed-in app at /app/#/compliance.
import { Link } from "../../router";
import type { SiteModule } from "../types";
import { CgtCalculator, StampDutyCalculator } from "./calculators";

const DIMENSIONS: [string, string][] = [
  ["Obligation coverage", "Which taxes apply to you, and whether you are registered and filing for each."],
  ["Timeliness", "Whether returns and payments go in by their due dates."],
  ["Documentation", "Whether you keep the records each obligation needs."],
  ["Reporting accuracy", "Signs that returns may leave something out."],
  ["Exposure materiality", "How much is likely to be at stake if a gap is confirmed. Never an amount owed."],
  ["Evidence confidence", "How complete your answers are. Not sure is fine and is reported as insufficient evidence."],
];

function HealthCheckLanding() {
  return (
    <div className="narrow">
      <p className="eyebrow">Check my tax health</p>
      <h1>Which taxes apply to me, and am I on top of them?</h1>
      <p className="lede">
        Answer a short set of questions about what you do, not just what kind of taxpayer you are. We work out which obligations apply under
        the 2026 rules, when each is due and what evidence to keep.
      </p>
      <p>
        <a className="btn" href="/app/#/compliance">
          Start my health check
        </a>{" "}
        <Link to="/reform/tax-health-check">How it works</Link>
      </p>
      <h2>What the report covers</h2>
      <p>Findings are reported for each area separately. We do not add them up into a single score.</p>
      <dl className="hc-dl">
        {DIMENSIONS.map(([term, text]) => (
          <div key={term}>
            <dt>{term}</dt>
            <dd>{text}</dd>
          </div>
        ))}
      </dl>
      <div className="notice notice--warn" role="note">
        The health check is self-reported and indicative. It is not an official assessment by the Nigeria Revenue Service or any state tax
        authority, and it does not say that you owe tax. Where it recommends a review, a qualified adviser can confirm your position.
      </div>
      <h2>Your data</h2>
      <p>
        We keep only the facts needed to work out your obligations, such as whether you employ staff or receive rent. Your answers are private
        to your account. An adviser sees them only if you choose to share them, and you can withdraw that at any time.
      </p>
      <h2>Related tools</h2>
      <ul>
        <li>
          <Link to="/calculators/cgt">Capital gains calculator</Link>
        </li>
        <li>
          <Link to="/calculators/stamp-duty">Stamp duty calculator</Link>
        </li>
        <li>
          <Link to="/advisers">Find a verified adviser</Link>
        </li>
      </ul>
    </div>
  );
}

export const siteModule: SiteModule = {
  id: "compliance",
  routes: [
    ["/health-check", () => <HealthCheckLanding />],
    ["/calculators/cgt", () => <CgtCalculator />],
    ["/calculators/stamp-duty", () => <StampDutyCalculator />],
  ],
};
