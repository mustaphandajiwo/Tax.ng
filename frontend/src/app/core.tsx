// Core app pages: dashboard, account (profile, identity, AI consent) and staff tools.
import { useState, type FormEvent, type ReactNode } from "react";
import { Loading, Notice, useLoad } from "../components/ui";
import { ApiError, http } from "../http";
import { appModules } from "../modules/registry";
import type { AppContext } from "../modules/types";
import { Link } from "../router";

export function PageHead({ title, intro, children }: { title: string; intro?: string; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {intro && <p className="lede">{intro}</p>}
      </div>
      {children && <div className="page-head__actions">{children}</div>}
    </div>
  );
}

export function Dashboard({ ctx }: { ctx: AppContext }) {
  const cards = appModules.map((m) => m.dashboard?.(ctx)).filter(Boolean);
  return (
    <>
      <PageHead
        title={`Welcome${ctx.me.name ? `, ${ctx.me.name}` : ""}`}
        intro={ctx.org ? `Working in ${ctx.org.name} as ${ctx.org.role.replace("_", " ")}.` : "Personal account. Choose a business workspace above to work for an organisation."}
      />
      {cards.length ? (
        <div className="cards cards--app">{cards}</div>
      ) : (
        <div className="cards cards--app">
          <Link to="/compliance" className="card card--link">
            <h2>Check my tax health</h2>
            <p>Find which taxes apply to you and what evidence you need.</p>
          </Link>
          <Link to="/workspaces" className="card card--link">
            <h2>Business workspaces</h2>
            <p>Returns, approvals, documents and filing for your organisation.</p>
          </Link>
        </div>
      )}
    </>
  );
}

interface Verification {
  id: string;
  id_type: string;
  id_masked: string;
  result: string;
  mode: string;
  checked_at: string;
}

export function Account({ ctx }: { ctx: AppContext }) {
  const [name, setName] = useState(ctx.me.name);
  const [saved, setSaved] = useState<string>();
  const [idType, setIdType] = useState("nin");
  const [idNumber, setIdNumber] = useState("");
  const [idError, setIdError] = useState<string>();
  const [version, setVersion] = useState(0);
  const checks = useLoad(() => http.get<{ items: Verification[] }>("/api/me/identity"), [version]);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    await http.post("/api/me", { name });
    await ctx.refreshMe();
    setSaved("Saved.");
  };
  const toggleAi = async () => {
    await http.post("/api/me", { ai_account_access: !ctx.me.ai_account_access });
    await ctx.refreshMe();
  };
  const verify = async (e: FormEvent) => {
    e.preventDefault();
    setIdError(undefined);
    try {
      await http.post("/api/me/identity", { id_type: idType, number: idNumber });
      setIdNumber("");
      setVersion(version + 1);
    } catch (err) {
      setIdError(err instanceof ApiError ? err.message : "Check failed");
    }
  };

  return (
    <>
      <PageHead title="Account" intro={ctx.me.email} />
      <div className="grid-2">
        <form className="card" onSubmit={save}>
          <h2>Profile</h2>
          <div className="field">
            <label htmlFor="acct-name">Name</label>
            <input id="acct-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <button className="btn">Save</button> {saved && <span className="muted small">{saved}</span>}
        </form>
        <div className="card">
          <h2>Tax AI access to my account</h2>
          <p className="small">
            When on, Tax AI may read your saved tax profile and health-check findings to answer questions about your own position. Every
            access is logged. You can turn it off at any time.
          </p>
          <button type="button" className={`btn${ctx.me.ai_account_access ? " btn--ghost" : ""}`} onClick={() => void toggleAi()}>
            {ctx.me.ai_account_access ? "Turn off access" : "Allow access"}
          </button>
          <p className="muted small">Currently: {ctx.me.ai_account_access ? "allowed" : "not allowed"}</p>
        </div>
        <form className="card" onSubmit={verify}>
          <h2>Verify my identity</h2>
          <p className="small">Only the last four digits are stored, alongside a one-way fingerprint.</p>
          <div className="field">
            <label htmlFor="idv-type">Identifier</label>
            <select id="idv-type" value={idType} onChange={(e) => setIdType(e.target.value)}>
              <option value="nin">NIN (National Identification Number)</option>
              <option value="tin">TIN (Tax Identification Number)</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="idv-number">Number</label>
            <input id="idv-number" inputMode="numeric" value={idNumber} onChange={(e) => setIdNumber(e.target.value)} />
          </div>
          {idError && <Notice tone="error">{idError}</Notice>}
          <button className="btn" disabled={!idNumber}>
            Verify
          </button>
          {checks.data ? (
            <ul className="list list--tight">
              {checks.data.items.map((c) => (
                <li key={c.id}>
                  <strong>
                    {c.id_type.toUpperCase()} {c.id_masked}
                  </strong>
                  <span>
                    {c.result} · {c.mode === "sandbox" ? "sandbox check, not a real verification" : c.mode} · {c.checked_at.slice(0, 10)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <Loading error={checks.error} />
          )}
        </form>
      </div>
    </>
  );
}

interface AdapterInfo {
  kind: string;
  name: string;
  mode: string;
  authorised: boolean;
  description: string;
}

export function Staff({ ctx }: { ctx: AppContext }) {
  const metrics = useLoad(
    () => http.get<{ users: number; organisations: number; audit_events: number; subscribers: number; routes: number; audit_chain: { ok: boolean; checked: number }; adapters: AdapterInfo[] }>("/api/admin/metrics"),
    [],
  );
  if (ctx.me.staff_role === "none") return <Notice tone="error">This area is for tax.ng staff.</Notice>;
  return (
    <>
      <PageHead title="Staff" intro={`Signed in as ${ctx.me.staff_role.replace("_", " ")}.`} />
      {!metrics.data ? (
        <Loading error={metrics.error} />
      ) : (
        <>
          <div className="result__head">
            {(
              [
                ["Users", metrics.data.users],
                ["Organisations", metrics.data.organisations],
                ["Subscribers", metrics.data.subscribers],
                ["API routes", metrics.data.routes],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="stat">
                <span className="stat__label">{label}</span>
                <span className="stat__value">{value}</span>
              </div>
            ))}
          </div>
          <Notice tone={metrics.data.audit_chain.ok ? "info" : "error"}>
            Audit chain {metrics.data.audit_chain.ok ? "verified" : "BROKEN"} across {metrics.data.audit_chain.checked} events.
          </Notice>
          <h2>Integrations</h2>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Integration</th>
                <th scope="col">Mode</th>
                <th scope="col">Authorised</th>
              </tr>
            </thead>
            <tbody>
              {metrics.data.adapters.map((a) => (
                <tr key={a.kind}>
                  <th scope="row">
                    {a.kind}
                    <span className="step-note">{a.description}</span>
                  </th>
                  <td>{a.mode}</td>
                  <td>{a.authorised ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}
