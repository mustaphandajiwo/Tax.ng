// Signed-in pages for e-invoicing (PRD 5, EINV-01 to EINV-03): list, create and edit,
// validate, submit to NRS (sandbox), status sync, exception queue and per-invoice event log.
import { useState, type FormEvent, type ReactNode } from "react";
import { PageHead } from "../../app/core";
import { Loading, Notice, errorText, useLoad } from "../../components/ui";
import { date, naira } from "../../format";
import { ApiError } from "../../http";
import { Link } from "../../router";
import type { AppContext, AppModule } from "../types";
import {
  CATEGORY_LABEL,
  STATUSES,
  STATUS_TONE,
  einvoicingApi as api,
  modeLabel,
  type Invoice,
  type InvoiceInput,
  type InvoiceStatus,
  type LineInput,
  type VatCategory,
} from "./api";

const go = (path: string) => {
  window.location.hash = `#${path}`;
};

function canEdit(ctx: AppContext): boolean {
  return ctx.org?.role === "owner" || ctx.org?.role === "preparer";
}

function newKey(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  return c?.randomUUID ? c.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function StatusPill({ status }: { status: InvoiceStatus }) {
  return <span className={`pill pill--${STATUS_TONE[status]}`}>{status.replace("_", " ")}</span>;
}

export function ModePill({ mode }: { mode: string }) {
  return <span className={`pill ${mode === "sandbox" ? "pill--warn" : "pill--ok"}`}>{modeLabel(mode)}</span>;
}

function NeedsOrg({ ctx, children }: { ctx: AppContext; children: ReactNode }) {
  if (!ctx.orgId)
    return (
      <>
        <PageHead title="E-invoicing" intro="E-invoices are issued by a business workspace." />
        <Notice tone="warn">
          Choose a business workspace in the switcher above, or <Link to="/workspaces">create one</Link>.
        </Notice>
      </>
    );
  return <>{children}</>;
}

// ---------------------------------------------------------------- list
function InvoiceList({ ctx }: { ctx: AppContext }) {
  const orgId = ctx.orgId as string;
  const [tab, setTab] = useState<InvoiceStatus | "all" | "exceptions">("all");
  const [version, setVersion] = useState(0);
  const [message, setMessage] = useState<string>();
  const [busy, setBusy] = useState(false);
  const list = useLoad(() => api.list(orgId, tab === "all" || tab === "exceptions" ? undefined : tab), [orgId, tab, version]);

  const sync = async () => {
    setBusy(true);
    setMessage(undefined);
    try {
      const r = await api.sync(orgId);
      setMessage(
        r.processed
          ? `Status sync applied ${r.processed} signed callback${r.processed === 1 ? "" : "s"}: ${r.items.map((i) => `${i.invoice_number} ${i.status}`).join(", ")}. ${modeLabel(r.mode)}.`
          : `No submitted invoices were waiting for a status. ${modeLabel(r.mode)}.`,
      );
      setVersion(version + 1);
    } catch (err) {
      setMessage(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead title="E-invoicing" intro={`Invoices for ${ctx.org?.name}. VAT on each line comes from the rules engine.`}>
        {canEdit(ctx) && (
          <>
            <Link to="/einvoicing/new" className="btn">
              New invoice
            </Link>
            <button type="button" className="btn btn--ghost" disabled={busy} onClick={() => void sync()}>
              Run status sync
            </button>
          </>
        )}
      </PageHead>
      {list.data && <ModePill mode={list.data.mode} />}
      <div aria-live="polite">{message && <Notice>{message}</Notice>}</div>
      <div className="tabs" role="tablist" aria-label="Filter invoices">
        {(["all", ...STATUSES, "exceptions"] as const).map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
            {t === "all" ? "All" : t === "exceptions" ? "Exception queue" : t.charAt(0).toUpperCase() + t.slice(1)}
            {list.data && t !== "all" && t !== "exceptions" ? ` (${list.data.counts[t]})` : ""}
          </button>
        ))}
      </div>
      {tab === "exceptions" ? (
        <ExceptionQueue ctx={ctx} onChange={() => setVersion(version + 1)} version={version} />
      ) : !list.data ? (
        <Loading error={list.error} />
      ) : list.data.items.length === 0 ? (
        <p className="muted">No invoices here yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Number</th>
                <th scope="col">Buyer</th>
                <th scope="col">Issued</th>
                <th scope="col" className="num">
                  Gross
                </th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((i) => (
                <tr key={i.id}>
                  <th scope="row">
                    <Link to={`/einvoicing/${i.id}`}>{i.invoice_number}</Link>
                    {i.kind === "credit_note" && <span className="step-note">Credit note</span>}
                    {i.source !== "manual" && <span className="step-note">From {i.source}</span>}
                  </th>
                  <td>{i.buyer_name || "Not set"}</td>
                  <td>{i.issue_date ? date(i.issue_date) : "Not set"}</td>
                  <td className="num">{i.totals.gross ? naira(i.totals.gross) : "Not computed"}</td>
                  <td>
                    <StatusPill status={i.status} />
                    {Object.keys(i.errors).length > 0 && <span className="step-note">{Object.keys(i.errors).length} field issue(s)</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function ExceptionQueue({ ctx, onChange, version }: { ctx: AppContext; onChange: () => void; version: number }) {
  const orgId = ctx.orgId as string;
  const [local, setLocal] = useState(0);
  const [message, setMessage] = useState<string>();
  const queue = useLoad(() => api.exceptions(orgId), [orgId, version, local]);
  const retry = async (id: string) => {
    setMessage(undefined);
    try {
      const r = await api.retry(orgId, id);
      setMessage(`${r.invoice.invoice_number} resubmitted. Run the status sync to fetch the result. ${modeLabel(r.mode)}.`);
      setLocal(local + 1);
      onChange();
    } catch (err) {
      setMessage(errorText(err));
    }
  };
  if (!queue.data) return <Loading error={queue.error} />;
  return (
    <>
      <p className="small muted">Rejected invoices and failed submissions. Fix the cause, then retry.</p>
      <div aria-live="polite">{message && <Notice>{message}</Notice>}</div>
      {queue.data.items.length === 0 ? (
        <p className="muted">Nothing needs attention.</p>
      ) : (
        <ul className="list">
          {queue.data.items.map((q) => (
            <li key={q.id}>
              <strong>
                <Link to={`/einvoicing/${q.id}`}>{q.invoice_number}</Link> <StatusPill status={q.status} />{" "}
                <span className="pill pill--bad">{q.kind}</span>
              </strong>
              <span>{q.reason}</span>
              {canEdit(ctx) && (
                <div className="row-actions">
                  <Link to={`/einvoicing/${q.id}/edit`} className="btn btn--small btn--ghost">
                    Edit
                  </Link>
                  <button type="button" className="btn btn--small" onClick={() => void retry(q.id)}>
                    Retry submission
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

// ---------------------------------------------------------------- form
const EMPTY_LINE: LineInput = { description: "", quantity: "1", unit_price: "", vat_category: "standard" };

function toInput(inv?: Invoice): InvoiceInput {
  if (!inv)
    return { invoice_number: "", issue_date: new Date().toISOString().slice(0, 10), buyer_name: "", buyer_tin: "", lines: [{ ...EMPTY_LINE }] };
  return {
    invoice_number: inv.invoice_number,
    issue_date: inv.issue_date ?? "",
    due_date: inv.due_date ?? "",
    buyer_name: inv.buyer_name,
    buyer_tin: inv.buyer_tin,
    buyer_email: inv.buyer_email ?? "",
    notes: inv.notes ?? "",
    lines: inv.input_lines.length
      ? inv.input_lines.map((l) => ({ ...EMPTY_LINE, ...l, vat_category: (l.vat_category as VatCategory) ?? "standard" }))
      : [{ ...EMPTY_LINE }],
  };
}

function Field(props: { id: string; label: string; value: string; onChange: (v: string) => void; error?: string; type?: string; hint?: string; inputMode?: "decimal" | "numeric" }) {
  return (
    <div className={`field${props.error ? " field--error" : ""}`}>
      <label htmlFor={props.id}>{props.label}</label>
      <input
        id={props.id}
        type={props.type ?? "text"}
        inputMode={props.inputMode}
        value={props.value}
        aria-invalid={Boolean(props.error)}
        aria-describedby={props.error || props.hint ? `${props.id}-hint` : undefined}
        onChange={(e) => props.onChange(e.target.value)}
      />
      {(props.error || props.hint) && (
        <p id={`${props.id}-hint`} className="field__hint">
          {props.error ?? props.hint}
        </p>
      )}
    </div>
  );
}

function InvoiceForm({ ctx, existing }: { ctx: AppContext; existing?: Invoice }) {
  const orgId = ctx.orgId as string;
  const [form, setForm] = useState<InvoiceInput>(() => toInput(existing));
  const [errors, setErrors] = useState<Record<string, string>>(existing?.errors ?? {});
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<InvoiceInput>) => setForm({ ...form, ...patch });
  const setLine = (i: number, patch: Partial<LineInput>) => set({ lines: form.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) });

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const inv = existing ? await api.update(orgId, existing.id, form) : await api.create(orgId, form);
      go(`/einvoicing/${inv.id}`);
    } catch (err) {
      if (err instanceof ApiError) setErrors(err.fields);
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  if (!canEdit(ctx)) return <Notice tone="error">Your role can view invoices but not create or edit them.</Notice>;
  const fe = (k: string) => errors[k];
  return (
    <>
      <PageHead title={existing ? `Edit ${existing.invoice_number}` : "New e-invoice"} intro="Saved as a draft. Validate, then submit to NRS." />
      <form onSubmit={save} noValidate>
        {errors.supplier_tin && <Notice tone="warn">Supplier TIN: {errors.supplier_tin}.</Notice>}
        <div className="grid-2">
          <div className="card">
            <h2>Invoice</h2>
            <Field id="inv-number" label="Invoice number" value={form.invoice_number} onChange={(v) => set({ invoice_number: v })} error={fe("invoice_number")} />
            <Field id="inv-issue" label="Issue date" type="date" value={form.issue_date} onChange={(v) => set({ issue_date: v })} error={fe("issue_date")} />
            <Field id="inv-due" label="Due date (optional)" type="date" value={form.due_date ?? ""} onChange={(v) => set({ due_date: v })} error={fe("due_date")} />
            <div className="field">
              <label htmlFor="inv-notes">Notes (optional)</label>
              <textarea id="inv-notes" value={form.notes ?? ""} onChange={(e) => set({ notes: e.target.value })} />
            </div>
          </div>
          <div className="card">
            <h2>Buyer</h2>
            <Field id="inv-buyer" label="Buyer name" value={form.buyer_name} onChange={(v) => set({ buyer_name: v })} error={fe("buyer_name")} />
            <Field
              id="inv-buyer-tin"
              label="Buyer TIN"
              value={form.buyer_tin}
              onChange={(v) => set({ buyer_tin: v })}
              error={fe("buyer_tin")}
              hint="12345678-0001 or a 10-digit TIN. In the sandbox, TINs ending 0000 are rejected."
            />
            <Field id="inv-buyer-email" label="Buyer email (optional)" type="email" value={form.buyer_email ?? ""} onChange={(v) => set({ buyer_email: v })} error={fe("buyer_email")} />
          </div>
        </div>
        <h2>Lines</h2>
        {fe("lines") && <Notice tone="error">{fe("lines")}</Notice>}
        {form.lines.map((line, i) => (
          <fieldset key={i}>
            <legend>Line {i + 1}</legend>
            <Field id={`l${i}-desc`} label="Description" value={line.description} onChange={(v) => setLine(i, { description: v })} error={fe(`lines.${i}.description`)} />
            <div className="grid-2">
              <Field id={`l${i}-qty`} label="Quantity" inputMode="decimal" value={line.quantity} onChange={(v) => setLine(i, { quantity: v })} error={fe(`lines.${i}.quantity`)} />
              <Field id={`l${i}-price`} label="Unit price (₦, excluding VAT)" inputMode="decimal" value={line.unit_price} onChange={(v) => setLine(i, { unit_price: v })} error={fe(`lines.${i}.unit_price`)} />
            </div>
            <div className={`field${fe(`lines.${i}.vat_category`) ? " field--error" : ""}`}>
              <label htmlFor={`l${i}-cat`}>VAT category</label>
              <select id={`l${i}-cat`} value={line.vat_category} onChange={(e) => setLine(i, { vat_category: e.target.value as VatCategory })}>
                {(Object.keys(CATEGORY_LABEL) as VatCategory[]).map((c) => (
                  <option key={c} value={c}>
                    {CATEGORY_LABEL[c]}
                  </option>
                ))}
              </select>
            </div>
            {form.lines.length > 1 && (
              <button type="button" className="btn btn--small btn--ghost" onClick={() => set({ lines: form.lines.filter((_, j) => j !== i) })}>
                Remove line {i + 1}
              </button>
            )}
          </fieldset>
        ))}
        <div className="row-actions">
          <button type="button" className="btn btn--ghost" onClick={() => set({ lines: [...form.lines, { ...EMPTY_LINE }] })}>
            Add a line
          </button>
          <button className="btn" disabled={busy}>
            Save draft
          </button>
          <Link to={existing ? `/einvoicing/${existing.id}` : "/einvoicing"} className="btn btn--ghost">
            Cancel
          </Link>
        </div>
        <div aria-live="polite">{error && <Notice tone="error">{error}</Notice>}</div>
      </form>
    </>
  );
}

function EditPage({ ctx }: { ctx: AppContext }) {
  const inv = useLoad(() => api.get(ctx.orgId as string, ctx.params.id), [ctx.orgId, ctx.params.id]);
  if (!inv.data) return <Loading error={inv.error} />;
  if (!["draft", "validated", "rejected"].includes(inv.data.status) || inv.data.kind === "credit_note")
    return <Notice tone="warn">A {inv.data.status} {inv.data.kind.replace("_", " ")} cannot be edited.</Notice>;
  return <InvoiceForm ctx={ctx} existing={inv.data} />;
}

// -------------------------------------------------------------- detail
function InvoiceDetail({ ctx }: { ctx: AppContext }) {
  const orgId = ctx.orgId as string;
  const id = ctx.params.id;
  const [version, setVersion] = useState(0);
  const [message, setMessage] = useState<{ tone: "info" | "warn" | "error"; text: string }>();
  const [fields, setFields] = useState<Record<string, string>>({});
  const [idemKey] = useState(newKey);
  const [reason, setReason] = useState("");
  const inv = useLoad(() => api.get(orgId, id), [orgId, id, version]);

  const act = async (label: string, run: () => Promise<{ mode?: string } | Invoice | unknown>, after?: (r: unknown) => void) => {
    setMessage(undefined);
    setFields({});
    try {
      const r = await run();
      setMessage({ tone: "info", text: label });
      after?.(r);
      setVersion(version + 1);
    } catch (err) {
      if (err instanceof ApiError) setFields(err.fields);
      setMessage({ tone: "error", text: errorText(err) });
      setVersion(version + 1);
    }
  };

  if (!inv.data) return <Loading error={inv.error} />;
  const i = inv.data;
  const edit = canEdit(ctx);
  const errs = Object.keys(fields).length ? fields : i.errors;
  return (
    <>
      <PageHead title={`${i.kind === "credit_note" ? "Credit note" : "Invoice"} ${i.invoice_number}`} intro={`${i.buyer_name || "Buyer not set"} · TIN ${i.buyer_tin || "not set"}`}>
        <Link to="/einvoicing" className="btn btn--ghost">
          All invoices
        </Link>
      </PageHead>
      <p>
        <StatusPill status={i.status} /> <ModePill mode={i.mode} />
      </p>
      <div aria-live="polite">{message && <Notice tone={message.tone}>{message.text}</Notice>}</div>
      {i.status === "rejected" && <Notice tone="error">Rejected: {i.rejection_reason}</Notice>}
      {i.last_error && <Notice tone="error">Submission failed: {i.last_error}</Notice>}
      {Object.keys(errs).length > 0 && (
        <Notice tone="warn">
          Fix these before submitting:
          <ul>
            {Object.entries(errs).map(([k, v]) => (
              <li key={k}>
                <strong>{k}</strong>: {v}
              </li>
            ))}
          </ul>
        </Notice>
      )}
      {edit && (
        <div className="row-actions">
          {["draft", "validated", "rejected"].includes(i.status) && i.kind === "invoice" && (
            <Link to={`/einvoicing/${i.id}/edit`} className="btn btn--ghost">
              Edit
            </Link>
          )}
          {["draft", "rejected"].includes(i.status) && (
            <button type="button" className="btn btn--ghost" onClick={() => void act("Validated. Ready to submit.", () => api.validate(orgId, i.id))}>
              Validate
            </button>
          )}
          {["draft", "validated", "rejected"].includes(i.status) && (
            <button
              type="button"
              className="btn"
              onClick={() =>
                void act("Submitted. The NRS status arrives later: run the status sync on the invoice list.", () => api.submit(orgId, i.id, idemKey))
              }
            >
              Submit to NRS
            </button>
          )}
          {["draft", "validated", "rejected"].includes(i.status) && (
            <button type="button" className="btn btn--danger" onClick={() => void act("Cancelled.", () => api.cancel(orgId, i.id, reason))}>
              Cancel invoice
            </button>
          )}
          {i.status === "accepted" && i.kind === "invoice" && (
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => void act("Credit note drafted.", () => api.creditNote(orgId, i.id, reason), (r) => go(`/einvoicing/${(r as Invoice).id}`))}
            >
              Issue credit note
            </button>
          )}
        </div>
      )}
      {edit && ["draft", "validated", "rejected", "accepted"].includes(i.status) && (
        <div className="field narrow">
          <label htmlFor="inv-reason">Reason (for cancellation or a credit note)</label>
          <input id="inv-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
      )}

      <h2>Lines and VAT</h2>
      {i.lines.length === 0 ? (
        <p className="muted">VAT is computed once the lines and issue date are valid.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Description</th>
                <th scope="col" className="num">
                  Qty
                </th>
                <th scope="col" className="num">
                  Unit price
                </th>
                <th scope="col">Category</th>
                <th scope="col" className="num">
                  Net
                </th>
                <th scope="col" className="num">
                  VAT
                </th>
                <th scope="col" className="num">
                  Gross
                </th>
              </tr>
            </thead>
            <tbody>
              {i.lines.map((l, n) => (
                <tr key={n}>
                  <th scope="row">{l.description}</th>
                  <td className="num">{l.quantity}</td>
                  <td className="num">{naira(l.unit_price)}</td>
                  <td>{CATEGORY_LABEL[l.vat_category]}</td>
                  <td className="num">{naira(l.net)}</td>
                  <td className="num">{naira(l.vat)}</td>
                  <td className="num">{naira(l.gross)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" colSpan={4}>
                  Total
                </th>
                <td className="num">{naira(i.totals.net)}</td>
                <td className="num">{naira(i.totals.vat)}</td>
                <td className="num">
                  <strong>{naira(i.totals.gross)}</strong>
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {i.rules_version && <p className="small muted">VAT from the tax.ng rules engine, rules version {i.rules_version.slice(0, 12)}.</p>}

      {i.irn && (
        <div className="card">
          <h2>NRS reference</h2>
          <p>
            <strong>IRN:</strong> <code>{i.irn}</code>
          </p>
          <p className="small">
            <strong>QR payload:</strong> <code className="einv-code">{i.qr_payload}</code>
          </p>
          {i.mode === "sandbox" && <p className="small muted">Sandbox reference. This invoice was not sent to NRS and has no legal effect.</p>}
        </div>
      )}

      <h2>Event log</h2>
      <p className="small muted">Append-only. Entries cannot be changed or removed.</p>
      <ol className="list list--tight">
        {(i.events ?? []).map((e) => (
          <li key={e.seq}>
            <strong>
              {e.event.replace(/_/g, " ")}
              {e.to_status && e.to_status !== e.from_status ? `: ${e.from_status ?? "new"} to ${e.to_status}` : ""}
            </strong>
            <span>
              {new Date(e.at).toLocaleString("en-NG")}
              {e.actor_id ? "" : " · from NRS"}
              {typeof e.data.reason === "string" && e.data.reason ? ` · ${e.data.reason}` : ""}
              {typeof e.data.mode === "string" ? ` · ${e.data.mode}` : ""}
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}

export const appModule: AppModule = {
  id: "einvoicing",
  routes: [
    ["/einvoicing", (ctx) => <NeedsOrg ctx={ctx}><InvoiceList ctx={ctx} /></NeedsOrg>],
    ["/einvoicing/new", (ctx) => <NeedsOrg ctx={ctx}><InvoiceForm ctx={ctx} /></NeedsOrg>],
    ["/einvoicing/:id", (ctx) => <NeedsOrg ctx={ctx}><InvoiceDetail ctx={ctx} /></NeedsOrg>],
    ["/einvoicing/:id/edit", (ctx) => <NeedsOrg ctx={ctx}><EditPage ctx={ctx} /></NeedsOrg>],
  ],
};
