// Staff pages for channels: WhatsApp operations and the translation review workflow.
import { useState, type FormEvent, type ReactNode } from "react";
import { api } from "../../api";
import { Loading, Notice, errorText, useLoad } from "../../components/ui";
import { PageHead } from "../../app/core";
import { Link } from "../../router";
import type { AppContext, AppModule } from "../types";
import { channelsApi, type StaffStrings } from "./api";
import { WhatsAppSimulator } from "./shared";

const WA_ROLES = ["support", "admin"];
const REVIEW_ROLES = ["editor", "legal_reviewer", "admin"];

function StaffOnly({ ctx, roles, children }: { ctx: AppContext; roles?: string[]; children: ReactNode }) {
  if (ctx.me.staff_role === "none" || (roles && !roles.includes(ctx.me.staff_role))) {
    return <Notice tone="error">This area is for tax.ng staff{roles ? ` with one of these roles: ${roles.join(", ").replace(/_/g, " ")}` : ""}.</Notice>;
  }
  return <>{children}</>;
}

// ---------------------------------------------------------------- WhatsApp
function AlertForm() {
  const [phone, setPhone] = useState("");
  const [text, setText] = useState("");
  const [msg, setMsg] = useState<{ tone: "info" | "warn" | "error"; text: string }>();
  const LABEL: Record<string, string> = {
    sent: "Alert sent (sandbox outbox).",
    suppressed_opted_out: "Not sent: this number has opted out with STOP.",
    not_opted_in: "Not sent: this number has never messaged tax.ng, so it has not opted in.",
  };
  const send = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const r = await channelsApi.alert(phone, text);
      setMsg({ tone: r.status === "sent" ? "info" : "warn", text: LABEL[r.status] ?? r.status });
    } catch (err) {
      setMsg({ tone: "error", text: errorText(err) });
    }
  };
  return (
    <form className="card" onSubmit={send}>
      <h2>Send an alert</h2>
      <p className="small">Alerts go only to numbers that wrote to us first and have not sent STOP. Alerts may not state figures; link to a guide instead.</p>
      <div className="field">
        <label htmlFor="alert-phone">Phone number</label>
        <input id="alert-phone" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="alert-text">Message</label>
        <textarea id="alert-text" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      <div aria-live="polite">{msg && <Notice tone={msg.tone}>{msg.text}</Notice>}</div>
      <button className="btn" disabled={!phone || text.trim().length < 3}>
        Send alert
      </button>
    </form>
  );
}

function ChannelsPage({ ctx }: { ctx: AppContext }) {
  const [version, setVersion] = useState(0);
  const log = useLoad(() => channelsApi.log(), [version]);
  return (
    <StaffOnly ctx={ctx} roles={WA_ROLES}>
      <PageHead title="Channels" intro="WhatsApp bot operations. Phone numbers are never shown or stored; senders appear as hash prefixes.">
        <Link to="/staff/translations" className="btn btn--ghost">
          Translations
        </Link>
      </PageHead>
      {log.data && (
        <div className="result__head">
          <div className="stat">
            <span className="stat__label">Contacts</span>
            <span className="stat__value">{log.data.contacts}</span>
          </div>
          <div className="stat">
            <span className="stat__label">Opted out</span>
            <span className="stat__value">{log.data.opted_out}</span>
          </div>
          <div className="stat">
            <span className="stat__label">Delivery</span>
            <span className="stat__value">{log.data.adapter.mode}</span>
          </div>
        </div>
      )}
      <div className="grid-2">
        <section className="card">
          <h2>Simulator</h2>
          {ctx.meta.demo_mode ? <WhatsAppSimulator onSent={() => setVersion((v) => v + 1)} /> : <Notice>The simulator runs only in demo mode.</Notice>}
        </section>
        <AlertForm />
      </div>
      <h2>Recent messages</h2>
      {!log.data ? (
        <Loading error={log.error} />
      ) : (
        <>
          <p className="muted small">{log.data.retention_note}</p>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Sender</th>
                  <th scope="col">Direction</th>
                  <th scope="col">Type</th>
                  <th scope="col">Snippet</th>
                </tr>
              </thead>
              <tbody>
                {log.data.items.map((m, i) => (
                  <tr key={i}>
                    <td>{m.created_at.replace("T", " ").slice(0, 19)}</td>
                    <td>
                      <code>{m.sender}</code>
                    </td>
                    <td>{m.direction === "in" ? "Inbound" : "Reply"}</td>
                    <td>
                      <span className={`pill ${m.kind === "rate_limited" ? "pill--bad" : m.kind === "stop" ? "pill--warn" : "pill--muted"}`}>{m.kind}</span>
                    </td>
                    <td className="small">{m.snippet}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </StaffOnly>
  );
}

// ------------------------------------------------------------ translations
function StringRow({ item, lang, ctx, onChange }: { item: StaffStrings["items"][number]; lang: string; ctx: AppContext; onChange: () => void }) {
  const [text, setText] = useState(item.approved ?? item.draft ?? "");
  const [error, setError] = useState<string>();
  const reviewer = REVIEW_ROLES.includes(ctx.me.staff_role);
  const act = async (fn: () => Promise<unknown>) => {
    setError(undefined);
    try {
      await fn();
      onChange();
    } catch (err) {
      setError(errorText(err));
    }
  };
  const id = `tr-${lang}-${item.key}`;
  return (
    <tr>
      <th scope="row">
        <code>{item.key}</code>
        <span className="step-note">{item.english}</span>
      </th>
      <td>
        {item.approved ? <span lang={lang}>{item.approved}</span> : <span className="pill pill--muted">English shown</span>}
        {item.draft && !item.approved && <span className="step-note">Draft in content: {item.draft}</span>}
      </td>
      <td>
        {item.pending ? (
          <>
            <span lang={lang}>{item.pending.text}</span>
            <span className="step-note">{item.pending.submitted_by === ctx.me.id ? "Submitted by you" : "Awaiting review"}</span>
            {reviewer && item.pending.submitted_by !== ctx.me.id && (
              <span className="row-actions">
                <button type="button" className="btn btn--small" onClick={() => void act(() => channelsApi.reviewString(item.pending!.id, "approve"))}>
                  Approve
                </button>
                <button type="button" className="btn btn--small btn--ghost" onClick={() => void act(() => channelsApi.reviewString(item.pending!.id, "reject"))}>
                  Reject
                </button>
              </span>
            )}
          </>
        ) : (
          <div className="row-actions">
            <label htmlFor={id} className="sr-only">
              Translation of {item.key}
            </label>
            <input id={id} lang={lang} value={text} onChange={(e) => setText(e.target.value)} />
            <button type="button" className="btn btn--small" disabled={!text.trim()} onClick={() => void act(() => channelsApi.submitString(lang, item.key, text))}>
              Submit
            </button>
          </div>
        )}
        {error && <span className="field__hint" role="alert">{error}</span>}
      </td>
    </tr>
  );
}

function StringsTab({ ctx }: { ctx: AppContext }) {
  const langs = useLoad(() => channelsApi.languages(), []);
  const [lang, setLang] = useState("ha");
  const [version, setVersion] = useState(0);
  const view = useLoad(() => channelsApi.staffStrings(lang), [lang, version]);
  return (
    <>
      <div className="field">
        <label htmlFor="tr-lang">Language</label>
        <select id="tr-lang" value={lang} onChange={(e) => setLang(e.target.value)}>
          {langs.data?.in_review.map((l) => (
            <option key={l.lang} value={l.lang}>
              {l.name} ({l.native_name})
            </option>
          ))}
        </select>
      </div>
      {!view.data ? (
        <Loading error={view.error} />
      ) : (
        <>
          {view.data.note && <Notice tone="warn">{view.data.note}</Notice>}
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">String (English)</th>
                  <th scope="col">Served now</th>
                  <th scope="col">Submission</th>
                </tr>
              </thead>
              <tbody>
                {view.data.items.map((item) => (
                  <StringRow key={`${lang}-${item.key}-${version}`} item={item} lang={lang} ctx={ctx} onChange={() => setVersion((v) => v + 1)} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

function GuidesTab({ ctx }: { ctx: AppContext }) {
  const guides = useLoad(() => api.guides(), []);
  const langs = useLoad(() => channelsApi.languages(), []);
  const [version, setVersion] = useState(0);
  const queue = useLoad(() => channelsApi.guideQueue(), [version]);
  const [guideId, setGuideId] = useState("");
  const [lang, setLang] = useState("ha");
  const [summary, setSummary] = useState("");
  const [msg, setMsg] = useState<{ tone: "info" | "error"; text: string }>();
  const reviewer = REVIEW_ROLES.includes(ctx.me.staff_role);
  const target = guideId || guides.data?.items[0]?.id || "";
  const english = guides.data?.items.find((g) => g.id === target)?.summary;

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      setMsg({ tone: "info", text: ok });
      setVersion((v) => v + 1);
    } catch (err) {
      setMsg({ tone: "error", text: errorText(err) });
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await channelsApi.submitGuide(target, lang, summary);
      setSummary("");
    }, "Submitted for review.");
  };

  return (
    <div className="grid-2">
      <form className="card" onSubmit={submit}>
        <h2>Translate a guide summary</h2>
        <div className="field">
          <label htmlFor="gt-guide">Guide</label>
          <select id="gt-guide" value={target} onChange={(e) => setGuideId(e.target.value)}>
            {guides.data?.items.map((g) => (
              <option key={g.id} value={g.id}>
                {g.title}
              </option>
            ))}
          </select>
        </div>
        {english && <p className="small">English: {english}</p>}
        <div className="field">
          <label htmlFor="gt-lang">Language</label>
          <select id="gt-lang" value={lang} onChange={(e) => setLang(e.target.value)}>
            {langs.data?.in_review.map((l) => (
              <option key={l.lang} value={l.lang}>
                {l.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="gt-summary">Translated summary</label>
          <textarea id="gt-summary" rows={4} lang={lang} value={summary} onChange={(e) => setSummary(e.target.value)} />
          <p className="field__hint">No figures: rates and amounts are shown from the rules engine.</p>
        </div>
        <div aria-live="polite">{msg && <Notice tone={msg.tone}>{msg.text}</Notice>}</div>
        <button className="btn" disabled={summary.trim().length < 3}>
          Submit for review
        </button>
      </form>
      <section className="card">
        <h2>Submissions</h2>
        {!queue.data ? (
          <Loading error={queue.error} />
        ) : queue.data.items.length === 0 ? (
          <p className="muted small">Nothing submitted yet.</p>
        ) : (
          <ul className="list">
            {queue.data.items.map((s) => (
              <li key={s.id}>
                <strong>
                  {s.guide_title} · {s.lang}
                </strong>
                <span lang={s.lang}>{s.summary}</span>
                <span className="row-actions">
                  <span className={`pill ${s.status === "approved" ? "pill--ok" : s.status === "rejected" ? "pill--bad" : "pill--warn"}`}>{s.status}</span>
                  {s.status === "submitted" && reviewer && s.submitted_by !== ctx.me.id && (
                    <>
                      <button type="button" className="btn btn--small" onClick={() => void run(() => channelsApi.reviewGuide(s.id, "approve"), "Approved. It is now served.")}>
                        Approve
                      </button>
                      <button type="button" className="btn btn--small btn--ghost" onClick={() => void run(() => channelsApi.reviewGuide(s.id, "reject"), "Rejected.")}>
                        Reject
                      </button>
                    </>
                  )}
                  {s.status === "submitted" && s.submitted_by === ctx.me.id && <span className="muted small">Another reviewer must approve</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function TranslationsPage({ ctx }: { ctx: AppContext }) {
  const [tab, setTab] = useState<"strings" | "guides">("strings");
  return (
    <StaffOnly ctx={ctx}>
      <PageHead
        title="Translations"
        intro="Staff submit translations; an editor or legal reviewer who did not submit approves them. Nothing is shown to the public until approved."
      />
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "strings"} onClick={() => setTab("strings")}>
          Interface strings
        </button>
        <button type="button" role="tab" aria-selected={tab === "guides"} onClick={() => setTab("guides")}>
          Guide summaries
        </button>
      </div>
      {tab === "strings" ? <StringsTab ctx={ctx} /> : <GuidesTab ctx={ctx} />}
    </StaffOnly>
  );
}

export const appModule: AppModule = {
  id: "channels",
  routes: [
    ["/channels", (ctx) => <ChannelsPage ctx={ctx} />],
    ["/staff/translations", (ctx) => <TranslationsPage ctx={ctx} />],
  ],
};
