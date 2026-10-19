// Signed-in billing pages (PRD section 9): plan picker, subscription status, payment history,
// receipts and the sandbox checkout page. Commercial services only; tax is never paid here.
import { useState } from "react";
import { PageHead } from "../../app/core";
import { Loading, Notice, errorText, useLoad } from "../../components/ui";
import { date } from "../../format";
import { Link } from "../../router";
import type { AppContext, AppModule } from "../types";
import { billingApi as api, koboToNaira, type Plan } from "./api";

const COMMERCIAL_NOTE =
  "tax.ng billing covers tax.ng's own commercial services. Tax is paid to the tax authority directly and never passes through tax.ng.";

function ModeNote({ mode }: { mode: string }) {
  return mode === "sandbox" ? (
    <span className="pill pill--warn">Sandbox payments: no money moves</span>
  ) : (
    <span className="pill pill--ok">{mode}</span>
  );
}

function PlanCard({ plan, canBuy, onBuy }: { plan: Plan; canBuy: boolean; onBuy: (plan: Plan, quantity: number) => Promise<void> }) {
  const [quantity, setQuantity] = useState("1");
  const [busy, setBusy] = useState(false);
  const id = `seats-${plan.id}`;
  return (
    <div className="card billing-plan">
      <h3>{plan.name}</h3>
      <p className="billing-plan__price">
        {koboToNaira(plan.price_kobo)} <span className="muted small">{plan.unit}, per {plan.interval}</span>
      </p>
      {plan.price_label && <p className="pill pill--muted">{plan.price_label}</p>}
      <ul className="small">
        {plan.features.map((f) => (
          <li key={f}>{f}</li>
        ))}
      </ul>
      {plan.seats && (
        <div className="field">
          <label htmlFor={id}>Seats</label>
          <input id={id} inputMode="numeric" value={quantity} onChange={(e) => setQuantity(e.target.value.replace(/\D/g, ""))} />
        </div>
      )}
      <button
        type="button"
        className="btn"
        disabled={!canBuy || busy}
        onClick={() => {
          setBusy(true);
          void onBuy(plan, Math.max(1, Number(quantity) || 1)).finally(() => setBusy(false));
        }}
      >
        Choose plan
      </button>
    </div>
  );
}

function BillingPage({ ctx }: { ctx: AppContext }) {
  const orgId = ctx.orgId;
  const isOwner = !orgId || ctx.org?.role === "owner";
  const [version, setVersion] = useState(0);
  const [error, setError] = useState<string>();
  const plans = useLoad(() => api.plans(), []);
  const subs = useLoad(() => (isOwner ? api.subscriptions(orgId) : Promise.resolve({ items: [] })), [orgId, version, isOwner]);
  const payments = useLoad(() => (isOwner ? api.payments(orgId) : Promise.resolve({ items: [], mode: "sandbox" })), [orgId, version, isOwner]);

  const buy = async (plan: Plan, quantity: number) => {
    setError(undefined);
    try {
      const r = await api.subscribe(plan.id, orgId, quantity);
      window.location.href = r.checkout.url;
    } catch (err) {
      setError(errorText(err));
    }
  };
  const cancel = async (id: string) => {
    setError(undefined);
    try {
      await api.cancel(id);
      setVersion(version + 1);
    } catch (err) {
      setError(errorText(err));
    }
  };

  const scope = orgId ? "org" : "user";
  return (
    <>
      <PageHead title="Billing" intro={orgId ? `Plans and payments for ${ctx.org?.name}.` : "Your personal plans and payments."} />
      <Notice>{COMMERCIAL_NOTE}</Notice>
      {plans.data && <ModeNote mode={plans.data.mode} />}
      {!isOwner && <Notice tone="warn">Only a workspace owner can manage billing for {ctx.org?.name}.</Notice>}
      <div aria-live="polite">{error && <Notice tone="error">{error}</Notice>}</div>

      <h2>Choose a plan</h2>
      {!plans.data ? (
        <Loading error={plans.error} />
      ) : (
        <div className="cards billing-plans">
          {plans.data.items
            .filter((p) => p.scope === scope)
            .map((p) => (
              <PlanCard key={p.id} plan={p} canBuy={isOwner} onBuy={buy} />
            ))}
        </div>
      )}
      {!orgId && <p className="small muted">Business plans appear when you switch to a business workspace.</p>}

      {isOwner && (
        <>
          <h2>Subscriptions</h2>
          {!subs.data ? (
            <Loading error={subs.error} />
          ) : subs.data.items.length === 0 ? (
            <p className="muted">No subscriptions yet.</p>
          ) : (
            <ul className="list">
              {subs.data.items.map((s) => (
                <li key={s.id}>
                  <strong>
                    {s.plan?.name ?? s.plan_id}
                    {s.quantity > 1 ? ` x ${s.quantity}` : ""}{" "}
                    <span className={`pill pill--${s.status === "active" ? "ok" : s.status === "pending" ? "warn" : "muted"}`}>{s.status}</span>
                  </strong>
                  <span>
                    {s.status === "active" && s.current_period_end ? `Renews ${date(s.current_period_end.slice(0, 10))}` : `Started ${date(s.created_at.slice(0, 10))}`}
                  </span>
                  <div className="row-actions">
                    {s.status === "pending" && s.checkout_id && (
                      <Link to={`/billing/checkout/${s.checkout_id}`} className="btn btn--small">
                        Complete payment
                      </Link>
                    )}
                    {(s.status === "pending" || s.status === "active") && (
                      <button type="button" className="btn btn--small btn--ghost" onClick={() => void cancel(s.id)}>
                        Cancel
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          <h2>Payments</h2>
          {!payments.data ? (
            <Loading error={payments.error} />
          ) : payments.data.items.length === 0 ? (
            <p className="muted">No payments yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Description</th>
                    <th scope="col" className="num">
                      Amount
                    </th>
                    <th scope="col">Status</th>
                    <th scope="col">Receipt</th>
                  </tr>
                </thead>
                <tbody>
                  {payments.data.items.map((p) => (
                    <tr key={p.id}>
                      <td>{date(p.created_at.slice(0, 10))}</td>
                      <th scope="row">
                        {p.description}
                        <span className="step-note">
                          {p.purpose} · {p.mode === "sandbox" ? "sandbox, no money moved" : p.mode}
                        </span>
                      </th>
                      <td className="num">{koboToNaira(p.amount_kobo)}</td>
                      <td>
                        <span className={`pill pill--${p.status === "paid" ? "ok" : p.status === "failed" ? "bad" : "warn"}`}>{p.status}</span>
                      </td>
                      <td>{p.receipt_id ? <Link to={`/billing/receipts/${p.receipt_id}`}>View</Link> : <span className="muted">None</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}

function CheckoutPage({ ctx }: { ctx: AppContext }) {
  const id = ctx.params.id;
  const [version, setVersion] = useState(0);
  const [result, setResult] = useState<{ status: string; receipt_id: string | null; mode: string }>();
  const [error, setError] = useState<string>();
  const checkout = useLoad(() => api.checkout(id), [id, version]);
  const complete = async (outcome: "paid" | "failed") => {
    setError(undefined);
    try {
      setResult(await api.complete(id, outcome));
      setVersion(version + 1);
    } catch (err) {
      setError(errorText(err));
    }
  };
  if (!checkout.data) return <Loading error={checkout.error} />;
  const c = checkout.data;
  return (
    <>
      <PageHead title="Checkout" intro="Sandbox payment provider" />
      <Notice tone="warn">
        This page stands in for a licensed payment provider's hosted checkout. No card details are collected and no money moves. Choosing an
        outcome sends the provider's signed webhook to tax.ng, which verifies it before marking the payment.
      </Notice>
      <div className="card narrow">
        <h2>{c.description}</h2>
        <p className="billing-plan__price">{koboToNaira(c.amount_kobo)}</p>
        <p className="small muted">
          Reference {c.checkout_id} · {c.mode}
        </p>
        <p>
          Status: <span className={`pill pill--${c.status === "paid" ? "ok" : c.status === "failed" ? "bad" : "warn"}`}>{c.status}</span>
        </p>
        {c.status === "pending" && (
          <div className="row-actions">
            <button type="button" className="btn" onClick={() => void complete("paid")}>
              Simulate successful payment
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => void complete("failed")}>
              Simulate failed payment
            </button>
          </div>
        )}
      </div>
      <div aria-live="polite">
        {error && <Notice tone="error">{error}</Notice>}
        {result && (
          <Notice tone={result.status === "paid" ? "info" : "warn"}>
            Webhook verified: {result.status} ({result.mode}).{" "}
            {result.receipt_id && <Link to={`/billing/receipts/${result.receipt_id}`}>View receipt</Link>}
          </Notice>
        )}
      </div>
      <Link to="/billing">Back to billing</Link>
    </>
  );
}

function ReceiptPage({ ctx }: { ctx: AppContext }) {
  const receipt = useLoad(() => api.receipt(ctx.params.id), [ctx.params.id]);
  if (!receipt.data) return <Loading error={receipt.error} />;
  const r = receipt.data;
  return (
    <>
      <PageHead title={`Receipt ${r.number}`} intro={r.seller}>
        <button type="button" className="btn btn--ghost" onClick={() => window.print()}>
          Print
        </button>
      </PageHead>
      {r.sandbox_note && <Notice tone="warn">{r.sandbox_note}</Notice>}
      <div className="card narrow billing-receipt">
        <dl>
          <dt>Issued</dt>
          <dd>{date(r.issued_at.slice(0, 10))}</dd>
          {r.billed_to && (
            <>
              <dt>Billed to</dt>
              <dd>
                {r.billed_to}
                {r.billed_to_tin ? ` (TIN ${r.billed_to_tin})` : ""}
              </dd>
            </>
          )}
          <dt>Description</dt>
          <dd>{r.description}</dd>
          <dt>Amount</dt>
          <dd>
            <strong>{koboToNaira(r.amount_kobo)}</strong>
          </dd>
        </dl>
        <p className="small muted">{r.nature}</p>
      </div>
      <Link to="/billing">Back to billing</Link>
    </>
  );
}

export const appModule: AppModule = {
  id: "billing",
  routes: [
    ["/billing", (ctx) => <BillingPage ctx={ctx} />],
    ["/billing/checkout/:id", (ctx) => <CheckoutPage ctx={ctx} />],
    ["/billing/receipts/:id", (ctx) => <ReceiptPage ctx={ctx} />],
  ],
};
