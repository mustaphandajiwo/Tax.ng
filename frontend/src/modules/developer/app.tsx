// Signed-in Integrations page (/integrations): API keys, webhooks, ERP import and reconciliation.
import { useState, type FormEvent } from "react";
import { PageHead } from "../../app/core";
import { CheckField, Loading, Notice, SelectField, errorText, useLoad } from "../../components/ui";
import { fileToBase64 } from "../../http";
import { Link } from "../../router";
import { einvoicingApi } from "../einvoicing/api";
import type { AppContext, AppModule } from "../types";
import { developerApi as api, type ApiKey, type Catalogue, type Endpoint, type ImportResult } from "./api";

type Tab = "keys" | "webhooks" | "import" | "reconciliation";
const TABS: [Tab, string][] = [
  ["keys", "API keys"],
  ["webhooks", "Webhooks"],
  ["import", "ERP import"],
  ["reconciliation", "Reconciliation"],
];

function SandboxPill({ mode }: { mode?: string }) {
  if (!mode) return null;
  return <span className={`pill ${mode === "sandbox" ? "pill--warn" : "pill--ok"}`}>{mode === "sandbox" ? "Sandbox" : mode}</span>;
}

function OwnerOnly({ ctx }: { ctx: AppContext }) {
  return <Notice tone="warn">Only an owner of {ctx.org?.name} can manage this.</Notice>;
}

// ------------------------------------------------------------- API keys
function Keys({ ctx, cat }: { ctx: AppContext; cat: Catalogue }) {
  const orgId = ctx.orgId as string;
  const [version, setVersion] = useState(0);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["calculators:read", "rules:read"]);
  const [rate, setRate] = useState("60");
  const [created, setCreated] = useState<ApiKey>();
  const [error, setError] = useState<string>();
  const keys = useLoad(() => api.keys(orgId), [orgId, version]);
  if (ctx.org?.role !== "owner") return <OwnerOnly ctx={ctx} />;

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      setCreated(await api.createKey(orgId, name, scopes, Number(rate) || 60));
      setName("");
      setVersion(version + 1);
    } catch (err) {
      setError(errorText(err));
    }
  };
  const revoke = async (id: string) => {
    setError(undefined);
    try {
      await api.revokeKey(orgId, id);
      setVersion(version + 1);
    } catch (err) {
      setError(errorText(err));
    }
  };
  const toggle = (s: string, on: boolean) => setScopes(on ? [...scopes, s] : scopes.filter((x) => x !== s));

  return (
    <div className="grid-2">
      <form className="card" onSubmit={create}>
        <h2>Create an API key</h2>
        <div className="field">
          <label htmlFor="key-name">Name</label>
          <input id="key-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="For example: ERP connector" />
        </div>
        <fieldset>
          <legend>Scopes</legend>
          {cat.scopes.map((s) => (
            <CheckField key={s.id} label={s.id} hint={s.description} checked={scopes.includes(s.id)} onChange={(on) => toggle(s.id, on)} />
          ))}
        </fieldset>
        <div className="field">
          <label htmlFor="key-rate">Requests per minute</label>
          <input id="key-rate" inputMode="numeric" value={rate} onChange={(e) => setRate(e.target.value.replace(/\D/g, ""))} />
        </div>
        <button className="btn" disabled={!name || scopes.length === 0}>
          Create key
        </button>
        <div aria-live="polite">
          {error && <Notice tone="error">{error}</Notice>}
          {created?.token && (
            <Notice tone="warn">
              {created.token_notice}
              <code className="dev-code dev-code--inline">{created.token}</code>
            </Notice>
          )}
        </div>
      </form>
      <div className="card">
        <h2>Keys</h2>
        {!keys.data ? (
          <Loading error={keys.error} />
        ) : keys.data.items.length === 0 ? (
          <p className="muted">No keys yet.</p>
        ) : (
          <ul className="list">
            {keys.data.items.map((k) => (
              <li key={k.id}>
                <strong>
                  {k.name} <SandboxPill mode={k.mode} /> {k.revoked_at && <span className="pill pill--bad">revoked</span>}
                </strong>
                <span>
                  <code>{k.prefix}_...</code> · {k.scopes.join(", ")} · {k.rate_per_minute} per minute
                </span>
                <span>Last used: {k.last_used_at ? new Date(k.last_used_at).toLocaleString("en-NG") : "never"}</span>
                {!k.revoked_at && (
                  <div className="row-actions">
                    <button type="button" className="btn btn--small btn--danger" onClick={() => void revoke(k.id)}>
                      Revoke
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="small">
          See the <a href="/#/developers">developer page</a> and the <a href="/api/v1/openapi.json">OpenAPI document</a>.
        </p>
      </div>
    </div>
  );
}

// ------------------------------------------------------------- webhooks
function Webhooks({ ctx, cat }: { ctx: AppContext; cat: Catalogue }) {
  const orgId = ctx.orgId as string;
  const [version, setVersion] = useState(0);
  const [url, setUrl] = useState("https://");
  const [events, setEvents] = useState<string[]>(["einvoice.accepted", "einvoice.rejected"]);
  const [created, setCreated] = useState<Endpoint>();
  const [error, setError] = useState<string>();
  const endpoints = useLoad(() => api.endpoints(orgId), [orgId, version]);
  const deliveries = useLoad(() => api.deliveries(orgId), [orgId, version]);
  if (ctx.org?.role !== "owner") return <OwnerOnly ctx={ctx} />;

  const run = async (fn: () => Promise<unknown>) => {
    setError(undefined);
    try {
      await fn();
      setVersion(version + 1);
    } catch (err) {
      setError(errorText(err));
    }
  };
  const add = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => setCreated(await api.addEndpoint(orgId, url, events)));
  };

  return (
    <>
      <Notice>
        Sandbox: deliveries are signed and recorded as "would deliver". Nothing is sent over the network. Use replay to see a fresh signature.
      </Notice>
      <div className="grid-2">
        <form className="card" onSubmit={add}>
          <h2>Add an endpoint</h2>
          <div className="field">
            <label htmlFor="wh-url">HTTPS URL</label>
            <input id="wh-url" type="url" value={url} onChange={(e) => setUrl(e.target.value)} />
          </div>
          <fieldset>
            <legend>Events</legend>
            {cat.events.map((ev) => (
              <CheckField
                key={ev.id}
                label={ev.id}
                hint={ev.description}
                checked={events.includes(ev.id)}
                onChange={(on) => setEvents(on ? [...events, ev.id] : events.filter((x) => x !== ev.id))}
              />
            ))}
          </fieldset>
          <button className="btn" disabled={events.length === 0}>
            Add endpoint
          </button>
          <div aria-live="polite">
            {error && <Notice tone="error">{error}</Notice>}
            {created?.secret && (
              <Notice tone="warn">
                {created.secret_notice}
                <code className="dev-code dev-code--inline">{created.secret}</code>
              </Notice>
            )}
          </div>
        </form>
        <div className="card">
          <h2>Endpoints</h2>
          {!endpoints.data ? (
            <Loading error={endpoints.error} />
          ) : endpoints.data.items.length === 0 ? (
            <p className="muted">No endpoints yet.</p>
          ) : (
            <ul className="list">
              {endpoints.data.items.map((ep) => (
                <li key={ep.id}>
                  <strong>
                    {ep.url} {!ep.active && <span className="pill pill--muted">disabled</span>}
                  </strong>
                  <span>
                    {ep.events.join(", ")} · secret {ep.secret_hint}
                  </span>
                  {ep.active && (
                    <div className="row-actions">
                      <button type="button" className="btn btn--small btn--ghost" onClick={() => void run(() => api.disableEndpoint(orgId, ep.id))}>
                        Disable
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <h2>Deliveries</h2>
      {!deliveries.data ? (
        <Loading error={deliveries.error} />
      ) : deliveries.data.items.length === 0 ? (
        <p className="muted">No deliveries yet. Submit and sync an e-invoice to see one.</p>
      ) : (
        <ul className="list">
          {deliveries.data.items.map((d) => (
            <li key={d.id}>
              <strong>
                {d.event} <span className="pill pill--warn">{d.status.replace("_", " ")}</span> <SandboxPill mode={d.mode} />
              </strong>
              <span>
                {d.endpoint_url} · attempt {d.attempts} · {d.last_attempt_at ? new Date(d.last_attempt_at).toLocaleString("en-NG") : ""}
              </span>
              <details>
                <summary>Headers and body</summary>
                <pre className="dev-code">
                  {Object.entries(d.headers)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join("\n")}
                  {"\n\n"}
                  {d.body}
                </pre>
              </details>
              <div className="row-actions">
                <button type="button" className="btn btn--small" onClick={() => void run(() => api.replay(orgId, d.id))}>
                  Replay
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

// ------------------------------------------------------------ ERP import
function ErpImport({ ctx, cat }: { ctx: AppContext; cat: Catalogue }) {
  const orgId = ctx.orgId as string;
  const [profile, setProfile] = useState(cat.erp_profiles[0]?.id ?? "taxng");
  const [format, setFormat] = useState<"csv" | "json">("csv");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [result, setResult] = useState<ImportResult>();
  const [message, setMessage] = useState<string>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const canImport = ctx.org?.role === "owner" || ctx.org?.role === "preparer";
  const selected = cat.erp_profiles.find((p) => p.id === profile);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    setMessage(undefined);
    try {
      const body = file
        ? { profile, format: file.name.toLowerCase().endsWith(".json") ? "json" : "csv", filename: file.name, data_base64: await fileToBase64(file) }
        : { profile, format, content: text };
      setResult(await api.importFile(orgId, body));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const submitValidated = async () => {
    if (!result) return;
    setError(undefined);
    try {
      const r = await einvoicingApi.submitValidated(orgId, result.source);
      setMessage(
        r.submitted.length
          ? `Submitted ${r.submitted.length} invoice(s) (${r.mode}). Run the status sync on the Reconciliation tab.`
          : "No validated invoices to submit.",
      );
    } catch (err) {
      setError(errorText(err));
    }
  };

  if (!canImport) return <Notice tone="warn">Your role can view the reconciliation but cannot import invoices.</Notice>;
  return (
    <div className="grid-2">
      <form className="card" onSubmit={submit}>
        <h2>Import from an ERP export</h2>
        <SelectField label="Mapping profile" value={profile} options={cat.erp_profiles.map((p) => ({ value: p.id, label: p.label }))} onChange={setProfile} />
        {selected && (
          <p className="small muted">
            Mapping {selected.mapping_status}. {selected.live_sync ? `Live sync: ${selected.live_sync}` : "Reference format."}
          </p>
        )}
        <div className="field">
          <label htmlFor="erp-file">Export file (CSV or JSON, up to 2 MB)</label>
          <input id="erp-file" type="file" accept=".csv,.json,text/csv,application/json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>
        {!file && (
          <>
            <SelectField
              label="Or paste rows as"
              value={format}
              options={[
                { value: "csv", label: "CSV" },
                { value: "json", label: "JSON (array of rows)" },
              ]}
              onChange={setFormat}
            />
            <div className="field">
              <label htmlFor="erp-text">Rows</label>
              <textarea id="erp-text" value={text} onChange={(e) => setText(e.target.value)} />
            </div>
          </>
        )}
        <button className="btn" disabled={busy || (!file && !text.trim())}>
          Import
        </button>
        <div aria-live="polite">{error && <Notice tone="error">{error}</Notice>}</div>
      </form>
      <div className="card" aria-live="polite">
        <h2>Result</h2>
        {!result ? (
          selected && (
            <>
              <p className="small">Expected columns for this profile:</p>
              <ul className="small">
                {Object.entries(selected.columns).map(([field, col]) => (
                  <li key={field}>
                    <code>{col}</code> to {field.replace(/_/g, " ")}
                  </li>
                ))}
              </ul>
            </>
          )
        ) : (
          <>
            <p>
              {result.rows} rows read. {result.counts.created} created, {result.counts.validated} validated, {result.counts.duplicate} already
              imported, {result.counts.failed} failed. <SandboxPill mode={result.mode} />
            </p>
            <ul className="list list--tight">
              {result.items.map((i) => (
                <li key={i.index}>
                  <strong>
                    {i.invoice_id ? <Link to={`/einvoicing/${i.invoice_id}`}>{i.external_id}</Link> : i.external_id ?? `Row group ${i.index + 1}`}{" "}
                    <span className={`pill pill--${i.status === "validated" ? "ok" : i.status === "failed" ? "bad" : i.status === "duplicate" ? "muted" : "warn"}`}>
                      {i.status}
                    </span>
                  </strong>
                  {i.errors && (
                    <span>
                      {Object.entries(i.errors)
                        .map(([k, v]) => `${k}: ${v}`)
                        .join("; ")}
                    </span>
                  )}
                </li>
              ))}
            </ul>
            {result.counts.validated > 0 && (
              <button type="button" className="btn" onClick={() => void submitValidated()}>
                Submit validated invoices
              </button>
            )}
            {message && <Notice>{message}</Notice>}
          </>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------- reconciliation
function ReconciliationView({ ctx }: { ctx: AppContext }) {
  const orgId = ctx.orgId as string;
  const [version, setVersion] = useState(0);
  const [message, setMessage] = useState<string>();
  const rec = useLoad(() => api.reconciliation(orgId), [orgId, version]);
  const canEdit = ctx.org?.role === "owner" || ctx.org?.role === "preparer";
  const sync = async () => {
    try {
      const r = await einvoicingApi.sync(orgId);
      setMessage(`Status sync applied ${r.processed} callback(s) (${r.mode}).`);
      setVersion(version + 1);
    } catch (err) {
      setMessage(errorText(err));
    }
  };
  if (!rec.data) return <Loading error={rec.error} />;
  return (
    <>
      <div className="row-actions">
        <SandboxPill mode={rec.data.mode} />
        {canEdit && (
          <button type="button" className="btn btn--small btn--ghost" onClick={() => void sync()}>
            Run status sync
          </button>
        )}
      </div>
      <div aria-live="polite">{message && <Notice>{message}</Notice>}</div>
      {rec.data.sources.length === 0 ? (
        <p className="muted">Nothing imported yet.</p>
      ) : (
        rec.data.sources.map((s) => (
          <section key={s.source} className="card dev-recon">
            <h2>{s.source}</h2>
            <div className="result__head">
              {(
                [
                  ["Imported", s.imported],
                  ["Submitted", s.submitted],
                  ["Accepted", s.accepted],
                  ["Rejected", s.rejected],
                ] as const
              ).map(([label, value]) => (
                <div key={label} className="stat">
                  <span className="stat__label">{label}</span>
                  <span className="stat__value">{value}</span>
                </div>
              ))}
            </div>
            {s.mismatched_totals.length > 0 && (
              <>
                <h3>Totals that do not match the ERP</h3>
                <ul className="list list--tight">
                  {s.mismatched_totals.map((m) => (
                    <li key={m.invoice_id}>
                      <strong>
                        <Link to={`/einvoicing/${m.invoice_id}`}>{m.external_id}</Link>
                      </strong>
                      <span>
                        {Object.entries(m.differences)
                          .map(([k, d]) => `${k}: ERP ${d.declared}, tax.ng ${d.computed}`)
                          .join("; ")}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {s.invalid.length > 0 && (
              <>
                <h3>Imported but not valid</h3>
                <ul className="list list--tight">
                  {s.invalid.map((m) => (
                    <li key={m.invoice_id}>
                      <strong>
                        <Link to={`/einvoicing/${m.invoice_id}`}>{m.external_id}</Link>
                      </strong>
                      <span>{Object.keys(m.errors).join(", ")}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        ))
      )}
      <h2>Import history</h2>
      {rec.data.imports.length === 0 ? (
        <p className="muted">No imports yet.</p>
      ) : (
        <ul className="list list--tight">
          {rec.data.imports.map((i) => (
            <li key={i.id}>
              <strong>
                {i.profile} {i.filename ? `· ${i.filename}` : ""}
              </strong>
              <span>
                {new Date(i.created_at).toLocaleString("en-NG")} · {i.rows} rows · {i.counts.created} created, {i.counts.duplicate} duplicates,{" "}
                {i.counts.failed} failed
              </span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function Integrations({ ctx }: { ctx: AppContext }) {
  const [tab, setTab] = useState<Tab>("keys");
  const cat = useLoad(() => api.catalogue(), []);
  if (!ctx.orgId)
    return (
      <>
        <PageHead title="Integrations and API" />
        <Notice tone="warn">
          API keys, webhooks and ERP imports belong to a business workspace. Choose one in the switcher above, or{" "}
          <Link to="/workspaces">create one</Link>.
        </Notice>
      </>
    );
  return (
    <>
      <PageHead title="Integrations and API" intro={`Connect ${ctx.org?.name} to your ERP and your own systems.`} />
      <div className="tabs" role="tablist" aria-label="Integrations">
        {TABS.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      {!cat.data ? (
        <Loading error={cat.error} />
      ) : tab === "keys" ? (
        <Keys ctx={ctx} cat={cat.data} />
      ) : tab === "webhooks" ? (
        <Webhooks ctx={ctx} cat={cat.data} />
      ) : tab === "import" ? (
        <ErpImport ctx={ctx} cat={cat.data} />
      ) : (
        <ReconciliationView ctx={ctx} />
      )}
    </>
  );
}

export const appModule: AppModule = {
  id: "developer",
  routes: [["/integrations", (ctx) => <Integrations ctx={ctx} />]],
};
