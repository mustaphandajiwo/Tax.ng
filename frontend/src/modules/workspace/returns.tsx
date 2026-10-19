// Returns: list and create, and the return page (line editor, results, review, export, filing, receipts, evidence).
import { useState, type FormEvent } from "react";
import type { Meta } from "../../api";
import { ResultView, type Headline } from "../../components/ResultView";
import { CheckField, Loading, MoneyField, Notice, SelectField, errorText, useLoad } from "../../components/ui";
import { date, naira } from "../../format";
import { Link } from "../../router";
import type { AppContext } from "../types";
import { downloadExport, ws, type Line, type LineBody, type ReturnDetail, type ReturnTypeSpec } from "./api";
import { OrgFrame, Pill, SandboxLabel, SubmissionRows, TextField } from "./pages";

// ---------------------------------------------------------------- field definitions
type FieldType = "money" | "date" | "text" | "check" | "select";
interface FieldDef {
  key: string;
  label: string;
  type: FieldType;
  required?: boolean;
  options?: (meta: Meta, values: Record<string, string | boolean>) => { value: string; label: string }[];
  initial?: string | boolean;
}

const label = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

const DETAIL_LABELS: Record<string, string> = {
  invoice_ref: "Invoice reference",
  counterparty: "Customer or supplier",
  description: "Description",
  payee_name: "Payee name",
  payee_tin: "Payee TIN",
  employee_ref: "Employee reference",
  employee_name: "Employee name",
  state_of_residence: "State of residence",
  accounting_period_end: "Accounting period end (YYYY-MM-DD)",
};

function inputFields(spec: ReturnTypeSpec, meta: Meta): FieldDef[] {
  const deduction = Object.fromEntries(meta.pit_deductions.map((d) => [d.id, d.label]));
  const defs: Record<string, FieldDef> = {
    supply_date: { key: "supply_date", label: "Supply date", type: "date", required: true },
    payment_date: { key: "payment_date", label: "Payment date", type: "date", required: true },
    amount: { key: "amount", label: "Amount", type: "money", required: true },
    category: {
      key: "category",
      label: "VAT category",
      type: "select",
      initial: "standard",
      options: (m) => m.vat_categories.map((c) => ({ value: c, label: label(c) })),
    },
    amount_includes_vat: { key: "amount_includes_vat", label: "Amount includes VAT", type: "check", initial: false },
    payment_type: {
      key: "payment_type",
      label: "Payment type",
      type: "select",
      initial: meta.wht_payment_types[0]?.id ?? "",
      options: (m) => m.wht_payment_types.map((t) => ({ value: t.id, label: t.label })),
    },
    recipient_type: {
      key: "recipient_type",
      label: "Payee type",
      type: "select",
      initial: "corporate",
      options: (m, v) =>
        (m.wht_payment_types.find((t) => t.id === v.payment_type)?.recipients ?? ["corporate", "non_corporate"]).map((r) => ({
          value: r,
          label: r === "corporate" ? "Company" : "Individual or other non-corporate",
        })),
    },
    recipient_has_tin: { key: "recipient_has_tin", label: "Payee has a TIN", type: "check", initial: true },
    payer_is_small_company: { key: "payer_is_small_company", label: "We are a small company", type: "check", initial: false },
    annual_gross_income: { key: "annual_gross_income", label: "Annual gross income", type: "money", required: true },
    annual_rent_paid: { key: "annual_rent_paid", label: "Annual rent paid", type: "money" },
    annual_turnover: { key: "annual_turnover", label: "Annual turnover", type: "money", required: true },
    fixed_assets: { key: "fixed_assets", label: "Total fixed assets", type: "money" },
    total_profits: { key: "total_profits", label: "Total profits", type: "money", required: true },
    assessable_profits: { key: "assessable_profits", label: "Assessable profits (levy base)", type: "money" },
    professional_services: { key: "professional_services", label: "Professional services firm", type: "check", initial: false },
    non_resident: { key: "non_resident", label: "Non-resident company", type: "check", initial: false },
  };
  return spec.inputs.map((k) => defs[k] ?? { key: k, label: deduction[k] ?? label(k), type: "money" });
}

const KIND_LABEL: Record<string, string> = {
  output: "Sale (output VAT)",
  input: "Purchase (input VAT)",
  payment: "Payment",
  employee: "Employee",
  computation: "Computation",
};

function headlines(result: Line["result"]): Headline[] {
  const o = result.outputs as Record<string, string>;
  switch (result.calculator) {
    case "vat":
      return [
        { label: "VAT", value: naira(o.vat) },
        { label: "Net amount", value: naira(o.net_amount) },
      ];
    case "wht":
      return [
        { label: "WHT to remit", value: naira(o.wht) },
        { label: "Net payment", value: naira(o.net_payment) },
      ];
    case "pit":
      return [
        { label: "Monthly PAYE", value: naira(o.monthly_tax) },
        { label: "Annual tax", value: naira(o.annual_tax) },
      ];
    default:
      return [
        { label: "Total tax", value: naira(o.total_tax) },
        { label: "CIT", value: naira(o.cit) },
      ];
  }
}

function lineHeadline(line: Line): string {
  return headlines(line.result)[0].value;
}

function lineTitle(line: Line): string {
  const d = line.details;
  return d.invoice_ref || d.counterparty || d.payee_name || d.employee_name || d.employee_ref || d.description || KIND_LABEL[line.kind] || line.kind;
}

// ---------------------------------------------------------------- list
const TYPE_PERIOD_HINT: Record<string, string> = { monthly: "YYYY-MM", annual: "YYYY" };

export function ReturnsList({ ctx }: { ctx: AppContext }) {
  const orgId = ctx.params.orgId;
  const [version, setVersion] = useState(0);
  const list = useLoad(() => ws.returns(orgId), [orgId, version]);
  const types = useLoad(() => ws.returnTypes(), []);
  const [type, setType] = useState("vat_monthly");
  const [period, setPeriod] = useState("");
  const [error, setError] = useState<string>();
  const role = ctx.me.memberships[orgId];
  const canEdit = role === "owner" || role === "preparer";
  const spec = types.data?.items.find((t) => t.id === type);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      const ret = await ws.createReturn(orgId, { return_type: type, period });
      window.location.hash = `#/workspaces/${orgId}/returns/${ret.id}`;
    } catch (err) {
      setError(errorText(err));
      setVersion(version + 1);
    }
  };

  return (
    <OrgFrame ctx={ctx} tab="returns" title="Returns">
      {(org) => (
        <>
          {canEdit && types.data && (
            <form className="card ws-create" onSubmit={create}>
              <h2>New return</h2>
              <SelectField label="Return type" value={type} options={types.data.items.map((t) => ({ value: t.id, label: t.label }))} onChange={setType} />
              <TextField
                label={`Period (${TYPE_PERIOD_HINT[spec?.frequency ?? "monthly"]})`}
                value={period}
                onChange={setPeriod}
                required
                hint={spec ? `Tax authority: ${spec.authority}` : undefined}
              />
              {error && <Notice tone="error">{error}</Notice>}
              <button className="btn" disabled={!period}>
                Create draft
              </button>
            </form>
          )}
          {!list.data ? (
            <Loading error={list.error} />
          ) : list.data.items.length === 0 ? (
            <p className="muted">No returns yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Return</th>
                    <th scope="col">Status</th>
                    <th scope="col">Due</th>
                    <th scope="col" className="num">
                      Liability
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.items.map((r) => (
                    <tr key={r.id}>
                      <th scope="row">
                        <Link to={`/workspaces/${org.id}/returns/${r.id}`}>{r.title}</Link>
                        <span className="step-note">{r.totals.lines} line(s)</span>
                      </th>
                      <td>
                        <Pill status={r.status} />
                      </td>
                      <td>{r.due_date ? date(r.due_date) : "Not linked"}</td>
                      <td className="num">{naira(String(r.totals.liability ?? "0"))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </OrgFrame>
  );
}

// ---------------------------------------------------------------- line editor
function LineEditor({
  spec,
  meta,
  line,
  onSave,
  onCancel,
}: {
  spec: ReturnTypeSpec;
  meta: Meta;
  line?: Line;
  onSave: (body: LineBody) => Promise<void>;
  onCancel?: () => void;
}) {
  const fields = inputFields(spec, meta);
  const [kind, setKind] = useState(line?.kind ?? spec.kinds[0]);
  const [details, setDetails] = useState<Record<string, string>>(line?.details ?? {});
  const [values, setValues] = useState<Record<string, string | boolean>>(() => {
    const out: Record<string, string | boolean> = {};
    for (const f of fields) {
      const existing = line?.inputs[f.key];
      out[f.key] = existing !== undefined && existing !== null ? (typeof existing === "boolean" ? existing : String(existing)) : f.initial ?? "";
    }
    return out;
  });
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    const inputs: Record<string, string | boolean> = {};
    for (const f of fields) if (values[f.key] !== "") inputs[f.key] = values[f.key];
    try {
      await onSave({ kind, details, inputs });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card ws-line-editor" onSubmit={save} aria-label={line ? "Edit line" : "Add line"}>
      <h3>{line ? "Edit line" : "Add a line"}</h3>
      {spec.kinds.length > 1 && (
        <SelectField label="Line type" value={kind} options={spec.kinds.map((k) => ({ value: k, label: KIND_LABEL[k] ?? k }))} onChange={setKind} />
      )}
      <div className="ws-fields">
        {spec.details.map((k) => (
          <TextField key={k} label={DETAIL_LABELS[k] ?? label(k)} value={details[k] ?? ""} onChange={(v) => setDetails({ ...details, [k]: v })} />
        ))}
        {fields.map((f) => {
          const v = values[f.key];
          const set = (nv: string | boolean) => setValues({ ...values, [f.key]: nv });
          if (f.type === "money") return <MoneyField key={f.key} label={f.label} value={String(v)} onChange={set} required={f.required} />;
          if (f.type === "check") return <CheckField key={f.key} label={f.label} checked={Boolean(v)} onChange={set} />;
          if (f.type === "select")
            return <SelectField key={f.key} label={f.label} value={String(v)} options={f.options?.(meta, values) ?? []} onChange={set} />;
          return <TextField key={f.key} label={f.label} type={f.type === "date" ? "date" : "text"} value={String(v)} onChange={set} required={f.required} />;
        })}
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="row-actions">
        <button className="btn" disabled={busy}>
          {line ? "Save and recalculate" : "Add and calculate"}
        </button>
        {onCancel && (
          <button type="button" className="btn btn--ghost" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- return page
const TOTAL_LABELS: Record<string, string> = {
  liability: "Liability for the period",
  output_vat: "Output VAT",
  input_vat: "Input VAT",
  net_vat: "Net VAT",
  credit_carried_forward: "Credit carried forward",
  wht: "WHT deducted",
  gross_payments: "Gross payments",
  monthly_paye: "PAYE for the month",
  cit: "CIT",
  development_levy: "Development levy",
  total_tax: "Total tax",
};

function newKey(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return `ui-${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

export function ReturnPage({ ctx }: { ctx: AppContext }) {
  const { orgId, returnId } = ctx.params;
  const [version, setVersion] = useState(0);
  const detail = useLoad(() => ws.returnDetail(orgId, returnId), [orgId, returnId, version]);
  const reload = () => setVersion((v) => v + 1);
  return (
    <OrgFrame ctx={ctx} tab="returns" title={detail.data?.title ?? "Return"}>
      {() => (!detail.data ? <Loading error={detail.error} /> : <ReturnBody ctx={ctx} r={detail.data} reload={reload} />)}
    </OrgFrame>
  );
}

function ReturnBody({ ctx, r, reload }: { ctx: AppContext; r: ReturnDetail; reload: () => void }) {
  const orgId = ctx.params.orgId;
  const [editing, setEditing] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [msg, setMsg] = useState<{ tone: "info" | "warn" | "error"; text: string }>();
  // One key per filing attempt: a retry after a network error reuses it, so the server never submits twice.
  const [fileKey, setFileKey] = useState(newKey);
  const p = r.permissions;
  const sandbox = r.filing.mode === "sandbox";

  const run = async (fn: () => Promise<unknown>, ok: string, tone: "info" | "warn" = "info") => {
    setMsg(undefined);
    try {
      await fn();
      setMsg({ tone, text: ok });
      setComment("");
      reload();
    } catch (err) {
      setMsg({ tone: "error", text: errorText(err) });
    }
  };

  const file = () =>
    void run(async () => {
      const sub = await ws.file(orgId, r.id, fileKey);
      setFileKey(newKey());
      if (sub.status !== "acknowledged") throw new Error(`Submission ${sub.status}: ${sub.message}`);
    }, sandbox ? "Sandbox acknowledgement received. This is a test: the return has NOT been filed. Submit it through official channels." : "Filed. Acknowledgement verified.", sandbox ? "warn" : "info");

  const totals = Object.entries(r.totals).filter(([k]) => TOTAL_LABELS[k]);

  return (
    <>
      <div className="ws-status-row">
        <Pill status={r.status} />
        {r.locked && <span className="pill pill--muted">Locked</span>}
        {r.due_date && <span className="muted small">Due {date(r.due_date)}</span>}
        <span className="muted small">Tax authority: {r.spec.authority}</span>
      </div>
      {r.status === "filed_sandbox" && (
        <Notice tone="warn">
          Sandbox acknowledgement {r.filed_reference}. This return has NOT been filed with any tax authority. Export it and submit it
          through official channels.
        </Notice>
      )}
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}

      <section className="result__head" aria-live="polite" aria-label="Return totals">
        {totals.map(([k, v]) => (
          <div key={k} className="stat">
            <span className="stat__label">{TOTAL_LABELS[k]}</span>
            <span className="stat__value">{naira(String(v))}</span>
          </div>
        ))}
      </section>
      <p className="small muted">Every figure is worked out by the tax.ng rules engine. Each line keeps the rules version it used.</p>

      <h2>Lines</h2>
      {r.lines.length === 0 && <p className="muted">No lines yet.</p>}
      {r.lines.map((line) =>
        editing === line.id ? (
          <LineEditor
            key={line.id}
            spec={r.spec}
            meta={ctx.meta}
            line={line}
            onCancel={() => setEditing(null)}
            onSave={async (body) => {
              await ws.updateLine(orgId, r.id, line.id, body);
              setEditing(null);
              reload();
            }}
          />
        ) : (
          <details key={line.id} className="card ws-line">
            <summary>
              <span>
                <strong>
                  {line.position}. {lineTitle(line)}
                </strong>{" "}
                <span className="muted small">{KIND_LABEL[line.kind] ?? line.kind}</span>
              </span>
              <span className="num">{lineHeadline(line)}</span>
            </summary>
            {p.edit && (
              <div className="row-actions">
                <button type="button" className="btn btn--small btn--ghost" onClick={() => setEditing(line.id)}>
                  Edit
                </button>
                <button
                  type="button"
                  className="btn btn--small btn--ghost"
                  onClick={() => window.confirm("Delete this line?") && void run(() => ws.deleteLine(orgId, r.id, line.id), "Line deleted.")}
                >
                  Delete
                </button>
              </div>
            )}
            <ResultView result={line.result} headlines={headlines(line.result)} />
          </details>
        ),
      )}
      {p.edit && !editing && !(r.spec.max_lines && r.lines.length >= r.spec.max_lines) && (
        <LineEditor
          key={`new-${r.lines.length}`}
          spec={r.spec}
          meta={ctx.meta}
          onSave={async (body) => {
            await ws.addLine(orgId, r.id, body);
            reload();
          }}
        />
      )}

      <h2>Review and approval</h2>
      <div className="card">
        {(p.submit || p.review || p.reopen) && (
          <div className="field">
            <label htmlFor="ws-comment">{p.reopen ? "Reason for reopening" : "Comment"}</label>
            <textarea id="ws-comment" value={comment} onChange={(e) => setComment(e.target.value)} />
          </div>
        )}
        <div className="row-actions">
          {p.submit && (
            <button type="button" className="btn" onClick={() => void run(() => ws.submit(orgId, r.id, comment), "Submitted for review. A different reviewer must approve it.")}>
              Submit for review
            </button>
          )}
          {p.review && (
            <>
              <button type="button" className="btn" onClick={() => void run(() => ws.approve(orgId, r.id, comment), "Approved. The return is now locked.")}>
                Approve
              </button>
              <button type="button" className="btn btn--ghost" onClick={() => void run(() => ws.requestChanges(orgId, r.id, comment), "Sent back to the preparer.")}>
                Request changes
              </button>
            </>
          )}
          {p.reopen && (
            <button type="button" className="btn btn--danger" onClick={() => void run(() => ws.reopen(orgId, r.id, comment), "Reopened as a draft. It needs review again.")}>
              Reopen for editing
            </button>
          )}
        </div>
        {p.review_block && <Notice tone="warn">{p.review_block}</Notice>}
        {r.status === "submitted_for_review" && !p.review && !p.review_block && <p className="muted small">Waiting for a reviewer.</p>}
        <ol className="list list--tight ws-history">
          {r.events.map((e, i) => (
            <li key={i}>
              <strong>
                {e.action.replace(/_/g, " ")} by {e.actor_email ?? "a former member"}
              </strong>
              <span>
                {e.at.replace("T", " ").slice(0, 16)}
                {e.comment ? `: ${e.comment}` : ""}
              </span>
            </li>
          ))}
        </ol>
        {r.approval_hash && <p className="small muted">Approved content fingerprint {r.approval_hash.slice(0, 16)}</p>}
      </div>

      <div className="grid-2">
        <section className="card">
          <h2>Export</h2>
          {p.export ? (
            <>
              <p className="small">
                Authority-style layout ({r.filing.authorised ? "approved return" : "for submission through official channels"}).
              </p>
              <div className="row-actions">
                {(["json", "csv"] as const).map((fmt) => (
                  <button
                    key={fmt}
                    type="button"
                    className="btn btn--ghost btn--small"
                    onClick={() => void run(() => downloadExport(ws.exportUrl(orgId, r.id, fmt), `return.${fmt}`), `Exported as ${fmt.toUpperCase()}.`)}
                  >
                    Download {fmt.toUpperCase()}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <p className="muted small">Available once the return is approved.</p>
          )}
        </section>
        <section className="card">
          <h2>
            Filing <SandboxLabel mode={r.filing.mode} />
          </h2>
          {sandbox ? (
            <p className="small">
              Direct filing is not authorised. A test submission returns a sandbox acknowledgement only, which is never treated as
              filed. Needs: {r.filing.needs}.
            </p>
          ) : (
            <p className="small">Submits to the tax authority. The return is marked filed only when the acknowledgement verifies.</p>
          )}
          {p.file ? (
            <button type="button" className="btn btn--small" onClick={file}>
              {sandbox ? "Send sandbox test submission" : "File return"}
            </button>
          ) : (
            <p className="muted small">
              {r.status === "filed" ? `Filed. Reference ${r.filed_reference}.` : r.status === "filed_sandbox" ? "Sandbox test already done." : "Available once approved."}
            </p>
          )}
          <SubmissionRows orgId={orgId} items={r.submissions.map((s) => ({ ...s, return_title: undefined }))} canReconcile={p.review || ctx.me.memberships[orgId] === "owner" || ctx.me.memberships[orgId] === "reviewer"} onChange={reload} />
        </section>
      </div>

      <div className="grid-2">
        <PaymentsCard ctx={ctx} r={r} reload={reload} />
        <EvidenceCard ctx={ctx} r={r} reload={reload} />
      </div>
    </>
  );
}

function PaymentsCard({ ctx, r, reload }: { ctx: AppContext; r: ReturnDetail; reload: () => void }) {
  const orgId = ctx.params.orgId;
  const channels = useLoad(() => ws.returnTypes(), []);
  const [form, setForm] = useState({ receipt_reference: "", amount: "", paid_on: new Date().toISOString().slice(0, 10), channel: "remita" });
  const [error, setError] = useState<string>();
  const rec = r.reconciliation;
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      await ws.recordPayment(orgId, r.id, form);
      setForm({ ...form, receipt_reference: "", amount: "" });
      reload();
    } catch (err) {
      setError(errorText(err));
    }
  };
  return (
    <section className="card">
      <h2>Remittance receipts</h2>
      <p className="small muted">tax.ng never holds or sends tax payments. Record the receipt you got from the authority's channel.</p>
      <div className="result__head">
        <div className="stat">
          <span className="stat__label">Liability</span>
          <span className="stat__value">{naira(rec.liability)}</span>
        </div>
        <div className="stat">
          <span className="stat__label">Remitted</span>
          <span className="stat__value">{naira(rec.remitted)}</span>
        </div>
      </div>
      <p>
        <Pill status={rec.status} /> {rec.flag && <span className="small">{rec.flag}</span>}
      </p>
      <ul className="list list--tight">
        {r.payments.map((pmt) => (
          <li key={pmt.id}>
            <strong>
              {pmt.receipt_reference}: {naira(pmt.amount)}
            </strong>
            <span>
              {date(pmt.paid_on)} · {pmt.channel.replace(/_/g, " ")}
              {ctx.me.memberships[orgId] === "owner" && (
                <>
                  {" "}
                  <button
                    type="button"
                    className="btn btn--small btn--ghost"
                    onClick={() => window.confirm("Void this receipt record?") && void ws.voidPayment(orgId, pmt.id).then(reload, (err: unknown) => setError(errorText(err)))}
                  >
                    Void
                  </button>
                </>
              )}
            </span>
          </li>
        ))}
      </ul>
      {r.permissions.record_payment && (
        <form onSubmit={save}>
          <TextField label="Authority receipt reference" value={form.receipt_reference} onChange={(v) => setForm({ ...form, receipt_reference: v })} required />
          <MoneyField label="Amount remitted" value={form.amount} onChange={(v) => setForm({ ...form, amount: v })} required />
          <TextField label="Date paid" type="date" value={form.paid_on} onChange={(v) => setForm({ ...form, paid_on: v })} required />
          <SelectField
            label="Channel"
            value={form.channel}
            options={(channels.data?.channels ?? ["remita"]).map((c) => ({ value: c, label: c.replace(/_/g, " ") }))}
            onChange={(v) => setForm({ ...form, channel: v })}
          />
          {error && <Notice tone="error">{error}</Notice>}
          <button className="btn btn--small" disabled={!form.receipt_reference || !form.amount}>
            Record receipt
          </button>
        </form>
      )}
    </section>
  );
}

function EvidenceCard({ ctx, r, reload }: { ctx: AppContext; r: ReturnDetail; reload: () => void }) {
  const orgId = ctx.params.orgId;
  const files = useLoad(() => ws.files(orgId), [orgId, r.documents.length]);
  const [pick, setPick] = useState("");
  const [error, setError] = useState<string>();
  const linked = new Set(r.documents.map((d) => d.id));
  const act = (fn: () => Promise<unknown>) => void fn().then(reload, (err: unknown) => setError(errorText(err)));
  return (
    <section className="card">
      <h2>Evidence</h2>
      {error && <Notice tone="error">{error}</Notice>}
      {r.documents.length === 0 ? (
        <p className="muted small">No documents linked.</p>
      ) : (
        <ul className="list list--tight">
          {r.documents.map((d) => (
            <li key={d.id}>
              <strong>{d.name}</strong>
              <span>
                {d.category.replace(/_/g, " ")}{" "}
                <button type="button" className="btn btn--small btn--ghost" onClick={() => act(async () => window.location.assign((await ws.fileLink(d.id)).url))}>
                  Download
                </button>
                {r.permissions.link_documents && (
                  <button type="button" className="btn btn--small btn--ghost" onClick={() => act(() => ws.unlinkDocument(orgId, r.id, d.id))}>
                    Unlink
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {r.permissions.link_documents && files.data && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (pick) act(() => ws.linkDocument(orgId, r.id, pick));
          }}
        >
          <SelectField
            label="Link a document from the vault"
            value={pick}
            options={[{ value: "", label: "Choose a document" }, ...files.data.items.filter((f) => !linked.has(f.id)).map((f) => ({ value: f.id, label: f.name }))]}
            onChange={setPick}
          />
          <div className="row-actions">
            <button className="btn btn--small" disabled={!pick}>
              Link
            </button>
            <Link to={`/workspaces/${orgId}/documents`} className="btn btn--small btn--ghost">
              Upload to vault
            </Link>
          </div>
        </form>
      )}
    </section>
  );
}
