// Workspace pages: organisation list, overview and calendar, profile, members, documents, payments, audit, filing.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { PageHead } from "../../app/core";
import { CheckField, Loading, MoneyField, Notice, SelectField, errorText, useLoad } from "../../components/ui";
import { date, naira } from "../../format";
import { fileToBase64 } from "../../http";
import { Link } from "../../router";
import type { AppContext } from "../types";
import { ROLE_LABEL, STATUS_LABEL, STATUS_TONE, ws, type Facts, type Org, type Role, type Submission } from "./api";

export const ENTITY_OPTIONS = [
  { value: "company", label: "Company" },
  { value: "sole_proprietor", label: "Sole proprietor" },
  { value: "partnership", label: "Partnership" },
  { value: "nonprofit", label: "Non-profit" },
  { value: "government", label: "Government body" },
  { value: "other", label: "Other" },
];
const ROLE_OPTIONS: { value: Role; label: string }[] = (Object.keys(ROLE_LABEL) as Role[]).map((r) => ({ value: r, label: ROLE_LABEL[r] }));

export function Pill({ status }: { status: string }) {
  const tone = STATUS_TONE[status];
  return <span className={`pill${tone ? ` pill--${tone}` : ""}`}>{STATUS_LABEL[status] ?? status.replace(/_/g, " ")}</span>;
}

export function SandboxLabel({ mode }: { mode: string }) {
  return mode === "sandbox" ? <span className="pill pill--warn ws-sandbox">Sandbox: not a real filing</span> : <span className="pill pill--ok">Production</span>;
}

/** Shared frame for every organisation page: loads the org, keeps it active, shows the tabs. */
export function OrgFrame({ ctx, tab, title, children }: { ctx: AppContext; tab: string; title?: string; children: (org: Org, reload: () => void) => ReactNode }) {
  const orgId = ctx.params.orgId;
  const [version, setVersion] = useState(0);
  const org = useLoad(() => ws.org(orgId), [orgId, version]);
  useEffect(() => {
    if (org.data && ctx.orgId !== orgId) ctx.setOrgId(orgId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org.data, orgId]);
  if (!org.data) return <Loading error={org.error} />;
  const o = org.data;
  const base = `/workspaces/${o.id}`;
  const tabs: [string, string, string][] = [
    ["overview", "Overview", base],
    ["returns", "Returns", `${base}/returns`],
    ["documents", "Documents", `${base}/documents`],
    ["payments", "Payments", `${base}/payments`],
    ["members", "Members", `${base}/members`],
    ["profile", "Profile", `${base}/profile`],
  ];
  if (o.role === "owner" || o.role === "reviewer") tabs.push(["audit", "Audit trail", `${base}/audit`]);
  return (
    <>
      <PageHead title={title ?? o.name} intro={`${o.name} · you are ${ROLE_LABEL[o.role].toLowerCase()}`}>
        <Link to="/workspaces" className="btn btn--ghost btn--small">
          All workspaces
        </Link>
      </PageHead>
      <nav className="tabs" aria-label="Workspace sections">
        {tabs.map(([id, label, to]) => (
          <Link key={id} to={to} aria-current={id === tab ? "page" : undefined}>
            {label}
          </Link>
        ))}
      </nav>
      {children(o, () => setVersion((v) => v + 1))}
    </>
  );
}

// ---------------------------------------------------------------- list / create
export function WorkspaceList({ ctx }: { ctx: AppContext }) {
  const [version, setVersion] = useState(0);
  const orgs = useLoad(() => ws.orgs(), [version]);
  const [form, setForm] = useState({ name: "", entity_type: "company", tin: "", cac_number: "", state: "" });
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (v: string) => setForm({ ...form, [k]: v });

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const org = await ws.createOrg(form);
      await ctx.refreshMe();
      ctx.setOrgId(org.id);
      window.location.hash = `#/workspaces/${org.id}/profile`;
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
      setVersion(version + 1);
    }
  };

  return (
    <>
      <PageHead title="Business workspaces" intro="Each organisation has its own members, returns, documents and audit trail." />
      <div className="grid-2">
        <section className="card">
          <h2>Your organisations</h2>
          {!orgs.data ? (
            <Loading error={orgs.error} />
          ) : orgs.data.items.length === 0 ? (
            <p className="muted">You are not a member of any organisation yet. Create one, or accept an invitation from its owner.</p>
          ) : (
            <ul className="list">
              {orgs.data.items.map((o) => (
                <li key={o.id}>
                  <Link to={`/workspaces/${o.id}`}>
                    <strong>{o.name}</strong>
                  </Link>
                  <span>
                    {ROLE_LABEL[o.role]} · {o.entity_type.replace("_", " ")}
                    {o.state ? ` · ${o.state}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <form className="card" onSubmit={create}>
          <h2>Create an organisation</h2>
          <p className="small muted">You become its owner. You can add the tax profile next.</p>
          <TextField label="Organisation name" value={form.name} onChange={set("name")} required />
          <SelectField label="Entity type" value={form.entity_type} options={ENTITY_OPTIONS} onChange={set("entity_type")} />
          <TextField label="TIN (optional)" value={form.tin} onChange={set("tin")} inputMode="numeric" />
          <TextField label="CAC registration number (optional)" value={form.cac_number} onChange={set("cac_number")} />
          <TextField label="State" value={form.state} onChange={set("state")} />
          {error && <Notice tone="error">{error}</Notice>}
          <button className="btn" disabled={busy || !form.name}>
            Create workspace
          </button>
        </form>
      </div>
    </>
  );
}

export function TextField(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  type?: string;
  inputMode?: "numeric" | "text" | "email";
  hint?: string;
}) {
  const id = `f-${props.label.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <div className="field">
      <label htmlFor={id}>
        {props.label}
        {props.required && <span aria-hidden="true"> *</span>}
      </label>
      <input
        id={id}
        type={props.type ?? "text"}
        inputMode={props.inputMode}
        value={props.value}
        required={props.required}
        onChange={(e) => props.onChange(e.target.value)}
      />
      {props.hint && <p className="field__hint">{props.hint}</p>}
    </div>
  );
}

export function AcceptInvitation({ ctx }: { ctx: AppContext }) {
  const [state, setState] = useState<{ error?: string; done?: { org_id: string; name: string; role: Role } }>({});
  const [busy, setBusy] = useState(false);
  const accept = async () => {
    setBusy(true);
    try {
      const done = await ws.acceptInvitation(ctx.params.token);
      await ctx.refreshMe();
      ctx.setOrgId(done.org_id);
      setState({ done });
    } catch (err) {
      setState({ error: errorText(err) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <PageHead title="Accept invitation" intro={`Signed in as ${ctx.me.email}. The invitation must have been sent to this address.`} />
      {state.done ? (
        <Notice>
          You joined {state.done.name} as {ROLE_LABEL[state.done.role].toLowerCase()}. <Link to={`/workspaces/${state.done.org_id}`}>Open the workspace</Link>
        </Notice>
      ) : (
        <>
          {state.error && <Notice tone="error">{state.error}</Notice>}
          <button type="button" className="btn" disabled={busy} onClick={() => void accept()}>
            Join the organisation
          </button>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------- overview and calendar
const RETURN_TYPE_LABEL: Record<string, string> = {
  vat_monthly: "VAT return",
  wht_monthly: "WHT schedule",
  paye_monthly: "PAYE schedule",
  cit_annual: "CIT return",
};

export function guessPeriod(period: string, returnType: string): string {
  if (returnType === "cit_annual") return /^\d{4}/.test(period) ? period.slice(0, 4) : "";
  return /^\d{4}-\d{2}$/.test(period) ? period : "";
}

export function Overview({ ctx }: { ctx: AppContext }) {
  const [year, setYear] = useState(new Date().getFullYear());
  const [version, setVersion] = useState(0);
  const orgId = ctx.params.orgId;
  const cal = useLoad(() => ws.calendar(orgId, year), [orgId, year, version]);
  const open = useLoad(() => ws.returns(orgId), [orgId, version]);
  const [error, setError] = useState<string>();

  const start = async (obligationId: string, obligationPeriod: string, returnType: string) => {
    setError(undefined);
    const period =
      guessPeriod(obligationPeriod, returnType) ||
      window.prompt(returnType === "cit_annual" ? "Year of assessment (YYYY)" : "Return period (YYYY-MM)", "");
    if (!period) return;
    try {
      const ret = await ws.createReturn(orgId, { return_type: returnType, period, obligation_id: obligationId, obligation_period: obligationPeriod });
      window.location.hash = `#/workspaces/${orgId}/returns/${ret.id}`;
    } catch (err) {
      setError(errorText(err));
      setVersion(version + 1);
    }
  };

  return (
    <OrgFrame ctx={ctx} tab="overview">
      {(org) => {
        const canEdit = org.role === "owner" || org.role === "preparer";
        const items = cal.data?.items ?? [];
        const today = new Date().toISOString().slice(0, 10);
        const upcoming = items.filter((i) => i.due_date >= today);
        const past = items.filter((i) => i.due_date < today);
        const openReturns = (open.data?.items ?? []).filter((r) => r.status !== "filed");
        return (
          <>
            {error && <Notice tone="error">{error}</Notice>}
            <section aria-labelledby="cal-h">
              <div className="page-head">
                <h2 id="cal-h">Compliance calendar</h2>
                <div className="field ws-inline">
                  <label htmlFor="cal-year">Year</label>
                  <select id="cal-year" value={year} onChange={(e) => setYear(Number(e.target.value))}>
                    {[year - 1, year, year + 1].map((y) => (
                      <option key={y} value={y}>
                        {y}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              {!cal.data ? (
                <Loading error={cal.error} />
              ) : !cal.data.available ? (
                <Notice tone="warn">
                  {cal.data.notice} <Link to={`/workspaces/${org.id}/returns`}>Prepare a return</Link>
                </Notice>
              ) : items.length === 0 ? (
                <p className="muted">
                  No obligations found for this profile. <Link to={`/workspaces/${org.id}/profile`}>Check the tax profile</Link>.
                </p>
              ) : (
                <div className="table-wrap">
                  <table className="table table--compact">
                    <thead>
                      <tr>
                        <th scope="col">Due</th>
                        <th scope="col">Obligation</th>
                        <th scope="col">Period</th>
                        <th scope="col">Status</th>
                        <th scope="col">Return</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...upcoming, ...past].map((i) => (
                        <tr key={`${i.id}-${i.period}`}>
                          <td>
                            {date(i.due_date)}
                            {i.overdue && <span className="pill pill--bad ws-gap">Overdue</span>}
                          </td>
                          <th scope="row">
                            {i.title}
                            <span className="step-note">{i.applies_because}</span>
                          </th>
                          <td>{i.period}</td>
                          <td>
                            <Pill status={i.status} />
                            {i.sandbox_acknowledged && <span className="pill pill--warn ws-gap">Sandbox only</span>}
                          </td>
                          <td>
                            {i.return_id ? (
                              <Link to={`/workspaces/${org.id}/returns/${i.return_id}`}>Open</Link>
                            ) : canEdit && i.suggested_return_type ? (
                              <button type="button" className="btn btn--small btn--ghost" onClick={() => void start(i.id, i.period, i.suggested_return_type!)}>
                                Start {RETURN_TYPE_LABEL[i.suggested_return_type] ?? "return"}
                              </button>
                            ) : (
                              <span className="muted small">Outside workspace returns</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
            <section aria-labelledby="open-h">
              <h2 id="open-h">Open returns</h2>
              {!open.data ? (
                <Loading error={open.error} />
              ) : openReturns.length === 0 ? (
                <p className="muted">No open returns.</p>
              ) : (
                <ul className="list">
                  {openReturns.map((r) => (
                    <li key={r.id}>
                      <Link to={`/workspaces/${org.id}/returns/${r.id}`}>
                        <strong>{r.title}</strong>
                      </Link>
                      <span>
                        <Pill status={r.status} /> {r.due_date ? `Due ${date(r.due_date)}` : ""} · liability {naira(String(r.totals.liability ?? "0"))}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        );
      }}
    </OrgFrame>
  );
}

// ---------------------------------------------------------------- profile and facts
const FLAG_FACTS: [string, string][] = [
  ["has_employees", "Has employees"],
  ["sells_taxable_supplies", "Sells goods or services subject to VAT"],
  ["makes_wht_payments", "Makes payments subject to withholding tax"],
  ["has_rental_income", "Has rental income"],
  ["has_foreign_income", "Has foreign income"],
  ["has_capital_gains", "Has capital gains"],
  ["is_professional_services", "Provides professional services"],
  ["non_resident", "Non-resident"],
];

export function Profile({ ctx }: { ctx: AppContext }) {
  return (
    <OrgFrame ctx={ctx} tab="profile" title="Organisation profile">
      {(org, reload) => <ProfileForms org={org} reload={reload} ctx={ctx} />}
    </OrgFrame>
  );
}

function ProfileForms({ org, reload, ctx }: { org: Org; reload: () => void; ctx: AppContext }) {
  const isOwner = org.role === "owner";
  const canEditFacts = isOwner || org.role === "preparer";
  const [details, setDetails] = useState({ name: org.name, entity_type: org.entity_type, tin: org.tin ?? "", cac_number: org.cac_number ?? "", state: org.state ?? "" });
  const [facts, setFacts] = useState<Facts>(org.facts);
  const [msg, setMsg] = useState<{ tone: "info" | "error"; text: string }>();

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(undefined);
    try {
      await fn();
      setMsg({ tone: "info", text: ok });
      await ctx.refreshMe();
      reload();
    } catch (err) {
      setMsg({ tone: "error", text: errorText(err) });
    }
  };
  const saveFacts = (e: FormEvent) => {
    e.preventDefault();
    const body: Facts = {};
    FLAG_FACTS.forEach(([k]) => (body[k] = Boolean(facts[k])));
    for (const k of ["annual_turnover", "fixed_assets", "employee_count"]) if (facts[k] !== undefined && facts[k] !== "") body[k] = facts[k];
    void run(() => ws.updateFacts(org.id, body), "Tax profile saved. The calendar now uses it.");
  };

  return (
    <>
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      <div className="grid-2">
        <form
          className="card"
          onSubmit={(e) => {
            e.preventDefault();
            void run(() => ws.updateOrg(org.id, details), "Details saved.");
          }}
        >
          <h2>Details</h2>
          {!isOwner && <p className="small muted">Only an owner can change these.</p>}
          <fieldset disabled={!isOwner} className="ws-fieldset">
            <TextField label="Name" value={details.name} onChange={(v) => setDetails({ ...details, name: v })} required />
            <SelectField label="Entity type" value={details.entity_type} options={ENTITY_OPTIONS} onChange={(v) => setDetails({ ...details, entity_type: v })} />
            <TextField label="TIN" value={details.tin} onChange={(v) => setDetails({ ...details, tin: v })} inputMode="numeric" />
            <TextField label="CAC number" value={details.cac_number} onChange={(v) => setDetails({ ...details, cac_number: v })} />
            <TextField label="State" value={details.state} onChange={(v) => setDetails({ ...details, state: v })} />
            <button className="btn">Save details</button>
          </fieldset>
          <h3>Verification</h3>
          <p className="small">Checks the TIN or CAC number on file. Only a masked form is stored.</p>
          {isOwner && (
            <div className="row-actions">
              <button type="button" className="btn btn--ghost btn--small" disabled={!org.tin} onClick={() => void run(() => ws.verify(org.id, "tin"), "TIN checked.")}>
                Verify TIN
              </button>
              <button type="button" className="btn btn--ghost btn--small" disabled={!org.cac_number} onClick={() => void run(() => ws.verify(org.id, "cac"), "CAC number checked.")}>
                Verify CAC number
              </button>
            </div>
          )}
          <ul className="list list--tight">
            {org.verifications.map((v) => (
              <li key={v.id}>
                <strong>
                  {v.id_type.toUpperCase()} {v.id_masked}: {v.result.replace("_", " ")}
                </strong>
                <span>
                  {v.mode === "sandbox" ? "Sandbox check, not a real verification" : v.mode} · {date(v.checked_at)}
                </span>
              </li>
            ))}
          </ul>
        </form>
        <form className="card" onSubmit={saveFacts}>
          <h2>Tax profile</h2>
          <p className="small muted">These facts decide which obligations appear in the compliance calendar.</p>
          <fieldset disabled={!canEditFacts} className="ws-fieldset">
            {FLAG_FACTS.map(([k, label]) => (
              <CheckField key={k} label={label} checked={Boolean(facts[k])} onChange={(v) => setFacts({ ...facts, [k]: v })} />
            ))}
            <TextField
              label="Number of employees"
              inputMode="numeric"
              value={facts.employee_count === undefined ? "" : String(facts.employee_count)}
              onChange={(v) => setFacts({ ...facts, employee_count: v.replace(/\D/g, "") === "" ? "" : Number(v.replace(/\D/g, "")) })}
            />
            <MoneyField label="Annual turnover" value={String(facts.annual_turnover ?? "")} onChange={(v) => setFacts({ ...facts, annual_turnover: v })} />
            <MoneyField label="Total fixed assets" value={String(facts.fixed_assets ?? "")} onChange={(v) => setFacts({ ...facts, fixed_assets: v })} />
            <button className="btn">Save tax profile</button>
          </fieldset>
        </form>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- members
export function Members({ ctx }: { ctx: AppContext }) {
  const orgId = ctx.params.orgId;
  const [version, setVersion] = useState(0);
  const members = useLoad(() => ws.members(orgId), [orgId, version]);
  const isOwner = ctx.me.memberships[orgId] === "owner";
  const invites = useLoad(() => (isOwner ? ws.invitations(orgId) : Promise.resolve({ items: [] })), [orgId, version, isOwner]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("preparer");
  const [msg, setMsg] = useState<{ tone: "info" | "error"; text: string }>();

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(undefined);
    try {
      await fn();
      setMsg({ tone: "info", text: ok });
      await ctx.refreshMe();
    } catch (err) {
      setMsg({ tone: "error", text: errorText(err) });
    } finally {
      setVersion((v) => v + 1);
    }
  };

  return (
    <OrgFrame ctx={ctx} tab="members" title="Members">
      {() => (
        <>
          {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
          <p className="small muted">
            Owners manage members. Preparers draft and submit returns. Reviewers approve or send back returns prepared by someone
            else. Read only members can view.
          </p>
          {!members.data ? (
            <Loading error={members.error} />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Member</th>
                    <th scope="col">Role</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {members.data.items.map((m) => (
                    <tr key={m.user_id}>
                      <th scope="row">
                        {m.name || m.email}
                        <span className="step-note">{m.email}</span>
                      </th>
                      <td>
                        {isOwner ? (
                          <>
                            <label className="sr-only" htmlFor={`role-${m.user_id}`}>
                              Role for {m.email}
                            </label>
                            <select
                              id={`role-${m.user_id}`}
                              value={m.role}
                              onChange={(e) => void run(() => ws.changeRole(orgId, m.user_id, e.target.value as Role), "Role updated.")}
                            >
                              {ROLE_OPTIONS.map((r) => (
                                <option key={r.value} value={r.value}>
                                  {r.label}
                                </option>
                              ))}
                            </select>
                          </>
                        ) : (
                          ROLE_LABEL[m.role]
                        )}
                      </td>
                      <td>
                        {(isOwner || m.user_id === ctx.me.id) && (
                          <button
                            type="button"
                            className="btn btn--small btn--ghost"
                            onClick={() => {
                              if (window.confirm(m.user_id === ctx.me.id ? "Leave this organisation?" : `Remove ${m.email}?`))
                                void run(() => ws.removeMember(orgId, m.user_id), m.user_id === ctx.me.id ? "You left the organisation." : "Member removed.");
                            }}
                          >
                            {m.user_id === ctx.me.id ? "Leave" : "Remove"}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {isOwner && (
            <div className="grid-2">
              <form
                className="card"
                onSubmit={(e) => {
                  e.preventDefault();
                  void run(async () => {
                    await ws.invite(orgId, email, role);
                    setEmail("");
                  }, "Invitation sent. It expires in seven days.");
                }}
              >
                <h2>Invite someone</h2>
                <TextField label="Email address" type="email" inputMode="email" value={email} onChange={setEmail} required />
                <SelectField label="Role" value={role} options={ROLE_OPTIONS} onChange={setRole} />
                <button className="btn" disabled={!email}>
                  Send invitation
                </button>
              </form>
              <section className="card">
                <h2>Pending invitations</h2>
                {!invites.data ? (
                  <Loading error={invites.error} />
                ) : invites.data.items.length === 0 ? (
                  <p className="muted">None.</p>
                ) : (
                  <ul className="list list--tight">
                    {invites.data.items.map((i) => (
                      <li key={i.id}>
                        <strong>
                          {i.email} · {ROLE_LABEL[i.role]}
                        </strong>
                        <span>
                          Expires {date(i.expires_at)}{" "}
                          <button type="button" className="btn btn--small btn--ghost" onClick={() => void run(() => ws.revokeInvitation(orgId, i.id), "Invitation revoked.")}>
                            Revoke
                          </button>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          )}
        </>
      )}
    </OrgFrame>
  );
}

// ---------------------------------------------------------------- documents
const DOC_CATEGORIES = [
  { value: "invoice", label: "Invoice" },
  { value: "receipt", label: "Remittance receipt" },
  { value: "contract", label: "Contract" },
  { value: "payroll", label: "Payroll record" },
  { value: "financial_statement", label: "Financial statement" },
  { value: "general", label: "Other" },
];

export function Documents({ ctx }: { ctx: AppContext }) {
  const orgId = ctx.params.orgId;
  const [version, setVersion] = useState(0);
  const files = useLoad(() => ws.files(orgId), [orgId, version]);
  const links = useLoad(() => ws.documentLinks(orgId), [orgId, version]);
  const rets = useLoad(() => ws.returns(orgId), [orgId]);
  const [file, setFile] = useState<File | null>(null);
  const [category, setCategory] = useState("invoice");
  const [linkTo, setLinkTo] = useState("");
  const [msg, setMsg] = useState<{ tone: "info" | "error"; text: string }>();
  const role = ctx.me.memberships[orgId];
  const canEdit = role === "owner" || role === "preparer";

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(undefined);
    try {
      await fn();
      setMsg({ tone: "info", text: ok });
    } catch (err) {
      setMsg({ tone: "error", text: errorText(err) });
    } finally {
      setVersion((v) => v + 1);
    }
  };
  const upload = (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    void run(async () => {
      const record = await ws.upload(orgId, { name: file.name, content_type: file.type, data_base64: await fileToBase64(file), category });
      if (linkTo) await ws.linkDocument(orgId, linkTo, record.id);
      setFile(null);
    }, "Uploaded.");
  };
  const download = (fileId: string) =>
    void run(async () => {
      const link = await ws.fileLink(fileId);
      window.location.assign(link.url);
    }, "Download started. The link expires in a few minutes.");

  return (
    <OrgFrame ctx={ctx} tab="documents" title="Document vault">
      {() => (
        <>
          {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
          {canEdit && (
            <form className="card" onSubmit={upload}>
              <h2>Upload a document</h2>
              <div className="field">
                <label htmlFor="ws-file">File (PDF, image, CSV, JSON, XLSX or DOCX, up to 10 MB)</label>
                <input id="ws-file" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </div>
              <SelectField label="Category" value={category} options={DOC_CATEGORIES} onChange={setCategory} />
              <SelectField
                label="Evidence for return (optional)"
                value={linkTo}
                options={[{ value: "", label: "Not linked" }, ...(rets.data?.items ?? []).map((r) => ({ value: r.id, label: r.title }))]}
                onChange={setLinkTo}
              />
              <button className="btn" disabled={!file}>
                Upload
              </button>
            </form>
          )}
          {!files.data ? (
            <Loading error={files.error} />
          ) : files.data.items.length === 0 ? (
            <p className="muted">No documents yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Document</th>
                    <th scope="col">Evidence for</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {files.data.items.map((f) => (
                    <tr key={f.id}>
                      <th scope="row">
                        {f.name}
                        <span className="step-note">
                          {f.category.replace("_", " ")} · {Math.ceil(f.size / 1024)} KB · {date(f.created_at)}
                        </span>
                      </th>
                      <td>
                        {(links.data?.links[f.id] ?? []).map((l) => (
                          <div key={l.return_id}>
                            <Link to={`/workspaces/${orgId}/returns/${l.return_id}`}>{l.title}</Link>
                          </div>
                        ))}
                      </td>
                      <td>
                        <div className="row-actions">
                          <button type="button" className="btn btn--small btn--ghost" onClick={() => download(f.id)}>
                            Download
                          </button>
                          {canEdit && (
                            <button
                              type="button"
                              className="btn btn--small btn--ghost"
                              onClick={() => window.confirm(`Delete ${f.name}?`) && void run(() => ws.deleteFile(f.id), "Deleted.")}
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      </td>
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

// ---------------------------------------------------------------- payments
export function Payments({ ctx }: { ctx: AppContext }) {
  const orgId = ctx.params.orgId;
  const data = useLoad(() => ws.payments(orgId), [orgId]);
  return (
    <OrgFrame ctx={ctx} tab="payments" title="Payment reconciliation">
      {() => (
        <>
          <Notice>
            tax.ng never holds or sends tax payments. Pay through the authority's own channels, then record the receipt reference on
            the return so differences are flagged.
          </Notice>
          {!data.data ? (
            <Loading error={data.error} />
          ) : data.data.items.length === 0 ? (
            <p className="muted">No approved returns or receipts yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Return</th>
                    <th scope="col" className="num">
                      Liability
                    </th>
                    <th scope="col" className="num">
                      Remitted
                    </th>
                    <th scope="col" className="num">
                      Difference
                    </th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.data.items.map((i) => (
                    <tr key={i.return_id}>
                      <th scope="row">
                        <Link to={`/workspaces/${orgId}/returns/${i.return_id}`}>{i.title}</Link>
                        <span className="step-note">
                          {i.payments.length} receipt{i.payments.length === 1 ? "" : "s"}
                        </span>
                      </th>
                      <td className="num">{naira(i.reconciliation.liability)}</td>
                      <td className="num">{naira(i.reconciliation.remitted)}</td>
                      <td className="num">{naira(i.reconciliation.difference)}</td>
                      <td>
                        <Pill status={i.reconciliation.status} />
                        {i.reconciliation.flag && <span className="step-note">{i.reconciliation.flag}</span>}
                      </td>
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

// ---------------------------------------------------------------- audit trail
export function Audit({ ctx }: { ctx: AppContext }) {
  const orgId = ctx.params.orgId;
  const role = ctx.me.memberships[orgId];
  const data = useLoad(() => (role === "owner" || role === "reviewer" ? ws.audit(orgId) : Promise.resolve({ items: [] })), [orgId, role]);
  return (
    <OrgFrame ctx={ctx} tab="audit" title="Audit trail">
      {() =>
        role !== "owner" && role !== "reviewer" ? (
          <Notice tone="warn">The audit trail is available to owners and reviewers.</Notice>
        ) : !data.data ? (
          <Loading error={data.error} />
        ) : (
          <>
            <p className="small muted">Append-only and hash-chained. Each event shows the first characters of its hash.</p>
            <div className="table-wrap">
              <table className="table table--compact">
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">Action</th>
                    <th scope="col">By</th>
                    <th scope="col">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {data.data.items.map((e) => (
                    <tr key={e.seq}>
                      <td>{e.at.replace("T", " ").slice(0, 16)}</td>
                      <th scope="row">
                        {e.action}
                        <span className="step-note">
                          {e.entity} {e.entity_id ?? ""}
                        </span>
                      </th>
                      <td>{e.actor ?? "system"}</td>
                      <td className="small">
                        {Object.entries(e.data)
                          .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
                          .join(", ")}
                        <span className="step-note">#{e.hash.slice(0, 10)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )
      }
    </OrgFrame>
  );
}

// ---------------------------------------------------------------- filing (across the active org)
export function SubmissionRows({ orgId, items, canReconcile, onChange }: { orgId: string; items: Submission[]; canReconcile: boolean; onChange: () => void }) {
  const [error, setError] = useState<string>();
  const reconcile = async (id: string) => {
    const note = window.prompt("Reconciliation note (what you checked)") ?? "";
    try {
      await ws.reconcile(orgId, id, note);
      onChange();
    } catch (err) {
      setError(errorText(err));
    }
  };
  if (!items.length) return <p className="muted">No submissions yet.</p>;
  return (
    <>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="table-wrap">
        <table className="table table--compact">
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Return</th>
              <th scope="col">Mode</th>
              <th scope="col">Status</th>
              <th scope="col">Acknowledgement</th>
            </tr>
          </thead>
          <tbody>
            {items.map((s) => (
              <tr key={s.id}>
                <td>{s.created_at.replace("T", " ").slice(0, 16)}</td>
                <th scope="row">
                  {s.return_title ? <Link to={`/workspaces/${orgId}/returns/${s.return_id}`}>{s.return_title}</Link> : s.return_id}
                  {s.message && <span className="step-note">{s.message}</span>}
                </th>
                <td>
                  <SandboxLabel mode={s.mode} />
                </td>
                <td>
                  <Pill status={s.status} />
                </td>
                <td>
                  {s.ack_reference ? (
                    <>
                      <code>{s.ack_reference}</code>
                      <span className="step-note">
                        {s.ack_verified ? "Signature verified" : "Not verified"}
                        {s.sandbox ? " · sandbox reference, not issued by NRS" : ""}
                      </span>
                    </>
                  ) : (
                    "None"
                  )}
                  {canReconcile && s.status === "acknowledged" && (
                    <button type="button" className="btn btn--small btn--ghost" onClick={() => void reconcile(s.id)}>
                      Mark reconciled
                    </button>
                  )}
                  {s.reconcile_note && <span className="step-note">Reconciled: {s.reconcile_note}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function Filing({ ctx }: { ctx: AppContext }) {
  const [version, setVersion] = useState(0);
  const orgId = ctx.orgId;
  const data = useLoad(() => (orgId ? ws.submissions(orgId) : Promise.resolve(null)), [orgId, version]);
  if (!orgId || !ctx.org)
    return (
      <>
        <PageHead title="Filing" intro="Filing submissions for a business workspace." />
        <Notice>
          Choose an organisation in the switcher at the top, or <Link to="/workspaces">open your workspaces</Link>.
        </Notice>
      </>
    );
  const canReconcile = ctx.org.role === "owner" || ctx.org.role === "reviewer";
  return (
    <>
      <PageHead title="Filing" intro={`Submissions for ${ctx.org.name}.`}>
        <Link to={`/workspaces/${orgId}/returns`} className="btn btn--ghost btn--small">
          Returns
        </Link>
      </PageHead>
      {!data.data ? (
        <Loading error={data.error} />
      ) : (
        <>
          {data.data.filing.mode === "sandbox" || !data.data.filing.authorised ? (
            <Notice tone="warn">
              Filing runs in sandbox mode. A sandbox acknowledgement is not a filing: nothing reaches the Nigeria Revenue Service.
              Submit exported returns through official channels. Direct filing needs {data.data.filing.needs ?? "authorisation"}.
            </Notice>
          ) : (
            <Notice>Direct filing is authorised. Acknowledgements are verified before a return is marked filed.</Notice>
          )}
          <SubmissionRows orgId={orgId} items={data.data.items} canReconcile={canReconcile} onChange={() => setVersion((v) => v + 1)} />
        </>
      )}
    </>
  );
}
