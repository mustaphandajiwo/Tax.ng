// Public-site pages for the "workspace" module: Business Solutions (/business) and File & Pay availability (/file-pay).
import { Loading, Notice, useLoad } from "../../components/ui";
import { Link } from "../../router";
import type { SiteModule } from "../types";
import { ws } from "./api";

function Business() {
  return (
    <article className="article">
      <p className="eyebrow">Business Solutions</p>
      <h1>Run your organisation's tax work in one place</h1>
      <p className="lede">
        Business workspaces give your finance team a shared home for returns, approvals, evidence and payment records. Every figure
        comes from the same published rules as our calculators, and every action is logged.
      </p>
      <p>
        <a className="btn" href="/app/#/workspaces">
          Open your workspace
        </a>{" "}
        <a className="btn btn--ghost" href="/app/">
          Sign in
        </a>
      </p>

      <div className="cards">
        <section className="card">
          <h2>Workspaces and roles</h2>
          <p>
            Invite colleagues and advisers as owner, preparer, reviewer or read only. Access is limited to members of the
            organisation. tax.ng editorial and advertising staff cannot see your records.
          </p>
        </section>
        <section className="card">
          <h2>Compliance calendar</h2>
          <p>
            Your profile (entity type, state, staff, turnover and activities) drives a calendar of the returns that apply to you,
            with the provision and evidence behind each one.
          </p>
        </section>
        <section className="card">
          <h2>Returns</h2>
          <p>
            Prepare VAT and withholding tax returns, PAYE schedules and the annual companies income tax computation line by line.
            Each line keeps the rules version it was worked out with, so it can be reproduced later.
          </p>
        </section>
        <section className="card">
          <h2>Maker and checker approvals</h2>
          <p>
            A preparer submits, and a different reviewer approves or asks for changes. Nobody can approve a return they prepared.
            Approved returns are locked; reopening needs an owner and is recorded.
          </p>
        </section>
        <section className="card">
          <h2>Document vault</h2>
          <p>Keep invoices, contracts and receipts with the return they support. Downloads use short-lived signed links.</p>
        </section>
        <section className="card">
          <h2>Payment reconciliation</h2>
          <p>
            Record the receipt reference for each remittance you make through official channels and see any difference against
            the liability. tax.ng never holds or sends tax payments.
          </p>
        </section>
        <section className="card">
          <h2>E-invoicing</h2>
          <p>
            Prepare and validate invoices for the national e-invoicing scheme, and import them from your accounting system, from
            the same workspace.
          </p>
        </section>
        <section className="card">
          <h2>Export and filing</h2>
          <p>
            Export an approved return as JSON or CSV for submission through official channels. Direct filing will be offered
            only once tax.ng is authorised. <Link to="/file-pay">Check filing availability</Link>.
          </p>
        </section>
      </div>
    </article>
  );
}

function FilePay() {
  const status = useLoad(() => ws.filingStatus(), []);
  return (
    <article className="article">
      <p className="eyebrow">File &amp; Pay</p>
      <h1>Filing returns through tax.ng</h1>
      {!status.data ? (
        <Loading error={status.error} />
      ) : status.data.available ? (
        <Notice>
          Direct filing is available for approved returns in business workspaces. Each filing shows the acknowledgement reference
          returned by the tax authority.
        </Notice>
      ) : (
        <Notice tone="warn">
          Direct filing is not available yet. tax.ng does not file returns with the Nigeria Revenue Service or any State Internal
          Revenue Service today.
        </Notice>
      )}
      <h2>What you can do now</h2>
      <ul>
        <li>Prepare and approve returns in a business workspace.</li>
        <li>Export the approved return as JSON or CSV, marked for submission through official channels.</li>
        <li>Submit it yourself on the authority's portal or at its office, and pay through the authority's own channels.</li>
        <li>Record the receipt reference against the return to keep your records reconciled.</li>
      </ul>
      <h2>What direct filing needs</h2>
      <p>
        Before tax.ng can submit a return for you, it must hold accreditation from the Nigeria Revenue Service, API credentials
        and certificates, and your written authorisation to file on your behalf. Until all of these are in place, any test
        submission in the demo is labelled as a sandbox acknowledgement and is never treated as a filed return.
      </p>
      <h2>Payments</h2>
      <p>
        tax.ng does not collect, hold or send tax payments. Remittances go directly from you to the tax authority through its
        approved channels.
      </p>
      <p>
        <Link to="/business">Business Solutions</Link> · <a href="/app/#/workspaces">Open your workspace</a>
      </p>
    </article>
  );
}

export const siteModule: SiteModule = {
  id: "workspace",
  routes: [
    ["/business", () => <Business />],
    ["/file-pay", () => <FilePay />],
  ],
};
