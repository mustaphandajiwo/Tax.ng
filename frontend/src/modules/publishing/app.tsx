// Signed-in pages for the publishing module: contributor portal and staff desks
// (editor, legal reviewer, sales, support). No ads are rendered here.
import { useState, type FormEvent, type ReactNode } from "react";
import { PageHead } from "../../app/core";
import { CheckField, Loading, Notice, SelectField, errorText, useLoad } from "../../components/ui";
import { Link } from "../../router";
import type { AppContext, AppModule, Me } from "../types";
import {
  ACTION_LABEL,
  STATE_LABEL,
  pub,
  stateTone,
  type Campaign,
  type CheckoutResult,
  type Citation,
  type Edition,
  type RenderedEdition,
  type Submission,
  type SubmissionFields,
} from "./api";

type Role = Me["staff_role"];
const isEditor = (r: Role) => r === "editor" || r === "admin";
const isLegal = (r: Role) => r === "legal_reviewer" || r === "admin";
const isSales = (r: Role) => r === "sales" || r === "admin";
const isSupport = (r: Role) => r === "support" || r === "admin";

function State({ s }: { s: string }) {
  return <span className={stateTone(s)}>{STATE_LABEL[s] ?? s}</span>;
}

function useAction() {
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>, after?: () => void) => {
    setError(undefined);
    setBusy(true);
    try {
      await fn();
      after?.();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return { error, busy, run };
}

function TextArea({ id, label, value, onChange, rows = 3, hint }: { id: string; label: string; value: string; onChange: (v: string) => void; rows?: number; hint?: string }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <textarea id={id} rows={rows} value={value} onChange={(e) => onChange(e.target.value)} aria-describedby={hint ? `${id}-hint` : undefined} />
      {hint && (
        <p id={`${id}-hint`} className="field__hint">
          {hint}
        </p>
      )}
    </div>
  );
}

function Input({ id, label, value, onChange, type = "text", hint }: { id: string; label: string; value: string; onChange: (v: string) => void; type?: string; hint?: string }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} type={type} value={value} onChange={(e) => onChange(e.target.value)} aria-describedby={hint ? `${id}-hint` : undefined} />
      {hint && (
        <p id={`${id}-hint`} className="field__hint">
          {hint}
        </p>
      )}
    </div>
  );
}

// ------------------------------------------------------------- contributor
const EMPTY: SubmissionFields = {
  title: "",
  summary: "",
  body: "",
  author_name: "",
  author_credentials: "",
  affiliation: "",
  citations: [],
  jurisdiction: "Nigeria",
  rights_warranty: false,
  conflicts: "",
  ai_disclosure: "",
  sponsorship_declaration: "none",
};

function citationsText(c: Citation[]): string {
  return c.map((x) => (x.url ? `${x.text} | ${x.url}` : x.text)).join("\n");
}

function parseCitations(text: string): Citation[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const [t, u] = l.split("|").map((s) => s.trim());
      return { text: t, url: u ?? "" };
    });
}

function SubmissionForm({ initial, staff, onSave }: { initial: SubmissionFields; staff: boolean; onSave: (f: SubmissionFields) => Promise<void> }) {
  const [f, setF] = useState<SubmissionFields>(initial);
  const [cites, setCites] = useState(citationsText(initial.citations));
  const { error, busy, run } = useAction();
  const set = <K extends keyof SubmissionFields>(k: K) => (v: SubmissionFields[K]) => setF({ ...f, [k]: v });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(() => onSave({ ...f, citations: parseCitations(cites) }));
  };
  return (
    <form className="card" onSubmit={submit}>
      <Input id="pub-title" label="Title" value={f.title} onChange={set("title")} />
      <TextArea id="pub-summary" label="Summary" value={f.summary} onChange={set("summary")} rows={2} />
      <TextArea id="pub-body" label="Full text" value={f.body} onChange={set("body")} rows={12} hint="Separate paragraphs with a blank line." />
      <div className="grid-2">
        <Input id="pub-author" label="Author name as published" value={f.author_name} onChange={set("author_name")} />
        <Input id="pub-cred" label="Credentials" value={f.author_credentials} onChange={set("author_credentials")} hint="For example: chartered tax adviser, lecturer in tax law." />
        <Input id="pub-aff" label="Affiliation" value={f.affiliation} onChange={set("affiliation")} />
        <Input id="pub-jur" label="Jurisdiction" value={f.jurisdiction} onChange={set("jurisdiction")} />
      </div>
      <TextArea id="pub-cites" label="Citations" value={cites} onChange={setCites} rows={4} hint="One per line. Add a link after a vertical bar: Nigeria Tax Act 2025, s. 20 | https://..." />
      <TextArea id="pub-conflicts" label="Conflicts of interest" value={f.conflicts} onChange={set("conflicts")} rows={2} hint='Write "None" if you have none.' />
      <TextArea id="pub-ai" label="Use of AI tools" value={f.ai_disclosure} onChange={set("ai_disclosure")} rows={2} hint="Say which tools you used and for what, or that you used none." />
      <SelectField
        label="Sponsorship declaration"
        value={f.sponsorship_declaration}
        onChange={set("sponsorship_declaration")}
        options={[
          { value: "none", label: "Nobody paid for or funded this piece" },
          { value: "paid", label: "Someone paid for this piece" },
          { value: "in_kind", label: "Someone funded this piece in kind" },
        ]}
      />
      {f.sponsorship_declaration !== "none" && <Notice tone="warn">This piece will be labelled Sponsored and needs a disclosure record before it can be published.</Notice>}
      {staff && (
        <SelectField
          label="Article type"
          value={f.article_type ?? "commentary"}
          onChange={set("article_type")}
          options={[
            { value: "commentary", label: "Explanatory commentary" },
            { value: "news", label: "News" },
            { value: "opinion", label: "Opinion" },
            { value: "submission", label: "User submission" },
          ]}
        />
      )}
      <CheckField
        label="I warrant that I hold the rights to publish this work and grant tax.ng a licence to publish it."
        checked={f.rights_warranty}
        onChange={set("rights_warranty")}
      />
      {error && <Notice tone="error">{error}</Notice>}
      <button className="btn" disabled={busy}>
        Save draft
      </button>
    </form>
  );
}

function MySubmissions({ ctx }: { ctx: AppContext }) {
  const { data, error } = useLoad(() => pub.mine(), []);
  const role = ctx.me.staff_role;
  return (
    <>
      <PageHead title="Publishing" intro="Write for tax.ng. Save drafts, respond to editors and track your submissions.">
        <Link to="/publishing/new" className="btn">
          New submission
        </Link>
      </PageHead>
      {role !== "none" && <DeskTabs role={role} current="" />}
      <h2>My submissions</h2>
      {!data ? (
        <Loading error={error} />
      ) : data.items.length === 0 ? (
        <p className="muted">Nothing yet. Read the <a href="/#/contribute">contributor guidance</a>, then start a submission.</p>
      ) : (
        <ul className="list">
          {data.items.map((s) => (
            <li key={s.id}>
              <Link to={`/publishing/${s.id}`}>
                <strong>{s.title}</strong>
              </Link>
              <span>
                <State s={s.state} /> {s.badge} · version {s.version} · updated {s.updated_at.slice(0, 10)}
              </span>
              {s.state === "revision_requested" && s.feedback && <span>Editor feedback: {s.feedback}</span>}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function NewSubmission({ ctx }: { ctx: AppContext }) {
  const staff = isEditor(ctx.me.staff_role);
  return (
    <>
      <PageHead title="New submission" intro="Your draft is private until you submit it for review." />
      <SubmissionForm
        initial={{ ...EMPTY, author_name: ctx.me.name, article_type: staff ? "commentary" : undefined }}
        staff={staff}
        onSave={async (f) => {
          const created = await pub.create(staff ? f : { ...f, article_type: undefined });
          window.location.hash = `#/publishing/${created.id}`;
        }}
      />
    </>
  );
}

function ActionPanel({ s, onDone }: { s: Submission; onDone: (n: Submission) => void }) {
  const [note, setNote] = useState("");
  const [when, setWhen] = useState("");
  const [body, setBody] = useState(s.body);
  const { error, busy, run } = useAction();
  if (!s.allowed_actions.length) return null;
  const needsNote = (a: string) => ["request_revision", "reject", "correct", "withdraw"].includes(a);
  const go = (action: string) =>
    run(async () => {
      const payload: Record<string, unknown> = {};
      if (note) payload.note = note;
      if (action === "schedule") payload.scheduled_for = when;
      if (action === "correct" && body !== s.body) payload.body = body;
      onDone(await pub.act(s.id, action, payload));
      setNote("");
    });
  return (
    <section className="card" aria-live="polite">
      <h2>Next steps</h2>
      {s.publish_blockers.length > 0 && (
        <Notice tone="warn">
          Cannot publish yet: {s.publish_blockers.join(" ")}
        </Notice>
      )}
      <TextArea id="act-note" label="Note (feedback, correction note or withdrawal reason)" value={note} onChange={setNote} rows={2} />
      {s.allowed_actions.includes("schedule") && <Input id="act-when" type="datetime-local" label="Publish at (UTC)" value={when} onChange={setWhen} />}
      {s.allowed_actions.includes("correct") && <TextArea id="act-body" label="Corrected text (optional)" value={body} onChange={setBody} rows={6} />}
      <div className="row-actions">
        {s.allowed_actions.map((a) => (
          <button
            key={a}
            type="button"
            className={`btn btn--small${["reject", "withdraw"].includes(a) ? " btn--danger" : a === "request_revision" ? " btn--ghost" : ""}`}
            disabled={busy || (needsNote(a) && !note.trim()) || (a === "schedule" && !when)}
            onClick={() => void go(a)}
          >
            {ACTION_LABEL[a] ?? a}
          </button>
        ))}
      </div>
      {error && <Notice tone="error">{error}</Notice>}
    </section>
  );
}

function DisclosurePanel({ s, onDone }: { s: Submission; onDone: (n: Submission) => void }) {
  const d = s.disclosure;
  const [name, setName] = useState(d?.sponsor_name ?? "");
  const [rel, setRel] = useState(d?.funding_relationship ?? "");
  const [label, setLabel] = useState<"Sponsored" | "Paid Partnership">(d?.label ?? "Sponsored");
  const [arconReq, setArconReq] = useState(Boolean(d?.arcon_required));
  const [arcon, setArcon] = useState(d?.arcon_reference ?? "");
  const { error, busy, run } = useAction();
  const save = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => onDone(await pub.disclose(s.id, { sponsor_name: name, funding_relationship: rel, label, arcon_required: arconReq, arcon_reference: arcon })));
  };
  return (
    <form className="card" onSubmit={save}>
      <h2>Sponsorship disclosure</h2>
      <p className="small">Paid content cannot be published until this record names the sponsor and the funding relationship.</p>
      <Input id="dis-name" label="Sponsor" value={name} onChange={setName} />
      <Input id="dis-rel" label="Funding relationship" value={rel} onChange={setRel} hint="For example: paid sponsorship; sponsor had no editorial control." />
      <SelectField label="Label" value={label} onChange={setLabel} options={[{ value: "Sponsored", label: "Sponsored" }, { value: "Paid Partnership", label: "Paid Partnership" }]} />
      <CheckField label="ARCON vetting required" checked={arconReq} onChange={setArconReq} />
      {arconReq && <Input id="dis-arcon" label="ARCON vetting reference" value={arcon} onChange={setArcon} />}
      {error && <Notice tone="error">{error}</Notice>}
      <button className="btn btn--small" disabled={busy}>
        Save disclosure
      </button>
    </form>
  );
}

function SubmissionPage({ ctx }: { ctx: AppContext }) {
  const id = ctx.params.id;
  const [version, setVersion] = useState(0);
  const [fresh, setFresh] = useState<Submission>();
  const loaded = useLoad(() => pub.get(id), [id, version]);
  const s = fresh && fresh.id === id ? fresh : loaded.data;
  const role = ctx.me.staff_role;
  const { error, run } = useAction();
  if (!s) return <Loading error={loaded.error} />;
  const update = (n: Submission) => setFresh(n);
  const canEdit = s.allowed_actions.includes("submit");
  const prePublish = ["submitted", "screening", "fact_legal_review", "approved", "scheduled"].includes(s.state);
  return (
    <>
      <p className="crumbs">
        <Link to="/publishing">Publishing</Link>
      </p>
      <PageHead title={s.title} intro={`${s.badge} · version ${s.version}`}>
        <State s={s.state} />
        {s.labels.sponsored && <span className="sponsored-label">{s.labels.label}</span>}
      </PageHead>
      {s.state === "revision_requested" && s.feedback && <Notice tone="warn">Editor feedback: {s.feedback}</Notice>}
      {(s.state === "published" || s.state === "corrected" || s.state === "withdrawn") && (
        <p>
          <a href={`/#/insights/${s.slug}`}>View the public page</a>
        </p>
      )}
      <ActionPanel s={s} onDone={update} />
      {canEdit ? (
        <SubmissionForm
          key={s.version}
          initial={{ ...s, section: s.section ?? null }}
          staff={false}
          onSave={async (f) => {
            const { article_type: _ignored, ...rest } = f;
            update(await pub.save(s.id, rest));
          }}
        />
      ) : (
        <section className="card">
          <h2>Summary</h2>
          <p>{s.summary}</p>
          <details>
            <summary>Full text</summary>
            {s.body.split(/\n{2,}/).map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </details>
          <p className="small">
            {s.author_name}, {s.author_credentials} ({s.affiliation}) · {s.jurisdiction}
          </p>
          <p className="small">Conflicts: {s.conflicts || "none"} · AI use: {s.ai_disclosure || "none"} · Rights warranty: {s.rights_warranty ? "given" : "not given"}</p>
          <p className="small">Legal sign-off: {s.legal_signoff_by ? "signed off" : "not yet"}</p>
        </section>
      )}
      {isEditor(role) && prePublish && (
        <section className="card">
          <h2>Classification</h2>
          <div className="row-actions">
            {(["commentary", "news", "opinion", "submission"] as const).map((t) => (
              <button key={t} type="button" className="btn btn--small btn--ghost" disabled={s.article_type === t} onClick={() => void run(async () => update(await pub.classify(s.id, { article_type: t })))}>
                {t}
              </button>
            ))}
            {(["nigeria", "africa", "global"] as const).map((sec) => (
              <button key={sec} type="button" className="btn btn--small btn--ghost" disabled={s.section === sec} onClick={() => void run(async () => update(await pub.classify(s.id, { section: sec })))}>
                Section: {sec}
              </button>
            ))}
          </div>
          {error && <Notice tone="error">{error}</Notice>}
        </section>
      )}
      {(isEditor(role) || isSales(role)) && s.labels.sponsored && prePublish && <DisclosurePanel s={s} onDone={update} />}
      <div className="grid-2">
        <section className="card">
          <h2>Workflow history</h2>
          <ul className="list list--tight">
            {s.history.map((h, i) => (
              <li key={i}>
                <strong>
                  {ACTION_LABEL[h.action] ?? h.action} ({h.actor_role})
                </strong>
                <span>
                  {STATE_LABEL[h.from_state]} to {STATE_LABEL[h.to_state]} · {h.created_at.slice(0, 16).replace("T", " ")}
                  {h.note ? ` · ${h.note}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
        <section className="card">
          <h2>Revisions</h2>
          <p className="small muted">Every saved version is kept and cannot be changed.</p>
          <ul className="list list--tight">
            {s.revisions.map((r) => (
              <li key={r.version}>
                <strong>Version {r.version}</strong>
                <span>
                  {r.reason} · {r.created_at.slice(0, 10)}
                </span>
              </li>
            ))}
          </ul>
          {s.corrections.length > 0 && (
            <>
              <h3>Public corrections</h3>
              <ul className="list list--tight">
                {s.corrections.map((c, i) => (
                  <li key={i}>
                    <span>{c.note}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      </div>
      <button type="button" className="btn btn--ghost btn--small" onClick={() => setVersion(version + 1)}>
        Refresh
      </button>
    </>
  );
}

// ------------------------------------------------------------- staff desks
const TABS: { id: string; label: string; show: (r: Role) => boolean }[] = [
  { id: "queue", label: "Editorial queue", show: isEditor },
  { id: "signoff", label: "Legal sign-off", show: isLegal },
  { id: "corrections", label: "Corrections", show: isEditor },
  { id: "complaints", label: "Complaints", show: (r) => isEditor(r) || isLegal(r) || isSupport(r) },
  { id: "editions", label: "Newsletter editions", show: (r) => isEditor(r) || isLegal(r) },
  { id: "sponsorships", label: "Sponsorship orders", show: (r) => isSales(r) || isEditor(r) },
  { id: "ads", label: "Ad campaigns", show: (r) => isSales(r) || isEditor(r) || isSupport(r) },
  { id: "reports", label: "Reporting", show: isSales },
];

function DeskTabs({ role, current }: { role: Role; current: string }) {
  const tabs = TABS.filter((t) => t.show(role));
  if (!tabs.length) return null;
  return (
    <nav className="tabs" aria-label="Publishing desks">
      <Link to="/publishing" aria-current={current === "" ? "page" : undefined}>
        My submissions
      </Link>
      {tabs.map((t) => (
        <Link key={t.id} to={`/publishing/desk/${t.id}`} aria-current={current === t.id ? "page" : undefined}>
          {t.label}
        </Link>
      ))}
    </nav>
  );
}

function Desk({ ctx }: { ctx: AppContext }) {
  const tab = ctx.params.tab;
  const role = ctx.me.staff_role;
  const def = TABS.find((t) => t.id === tab);
  let view: ReactNode;
  if (!def || !def.show(role)) view = <Notice tone="error">This desk is not available for your role.</Notice>;
  else if (tab === "queue") view = <QueueDesk />;
  else if (tab === "signoff") view = <QueueDesk legal />;
  else if (tab === "corrections") view = <CorrectionsDesk />;
  else if (tab === "complaints") view = <ComplaintsDesk />;
  else if (tab === "editions") view = <EditionsDesk role={role} />;
  else if (tab === "sponsorships") view = <SponsorshipDesk role={role} />;
  else if (tab === "ads") view = <AdsDesk role={role} />;
  else view = <ReportsDesk />;
  return (
    <>
      <PageHead title="Publishing desk" intro={`Signed in as ${role.replace("_", " ")}.`} />
      <DeskTabs role={role} current={tab} />
      {view}
    </>
  );
}

function QueueDesk({ legal = false }: { legal?: boolean }) {
  const [state, setState] = useState(legal ? "" : "submitted");
  const [v, setV] = useState(0);
  const { data, error } = useLoad(() => pub.queue(legal ? undefined : state || undefined), [state, v]);
  const act = useAction();
  return (
    <>
      {!legal && (
        <div className="row-actions">
          <SelectField
            label="State"
            value={state}
            onChange={setState}
            options={[{ value: "", label: "All except drafts" }, ...["submitted", "screening", "revision_requested", "fact_legal_review", "approved", "scheduled", "published", "corrected", "withdrawn", "rejected"].map((s) => ({ value: s, label: STATE_LABEL[s] }))]}
          />
          <button type="button" className="btn btn--ghost btn--small" onClick={() => void act.run(() => pub.runScheduled(), () => setV(v + 1))}>
            Run scheduled publishing
          </button>
        </div>
      )}
      {act.error && <Notice tone="error">{act.error}</Notice>}
      {!data ? (
        <Loading error={error} />
      ) : data.items.length === 0 ? (
        <p className="muted">Nothing waiting.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Article</th>
                <th scope="col">State</th>
                <th scope="col">Legal sign-off</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((i) => (
                <tr key={i.id}>
                  <th scope="row">
                    <Link to={`/publishing/${i.id}`}>{i.title}</Link>
                    <span className="step-note">
                      {i.badge} · {i.author_name}
                      {i.sponsored ? " · Sponsored" : ""}
                    </span>
                  </th>
                  <td>
                    <State s={i.state} />
                  </td>
                  <td>{i.legal_signed_off ? "Signed off" : "Pending"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function CorrectionsDesk() {
  const { data, error } = useLoad(() => pub.queue("published"), []);
  const corrected = useLoad(() => pub.queue("corrected"), []);
  const items = [...(data?.items ?? []), ...(corrected.data?.items ?? [])];
  return (
    <>
      <p>Open a published article to publish a correction note or withdraw it. Corrections stay visible on the public page; withdrawals leave a tombstone.</p>
      {!data ? (
        <Loading error={error} />
      ) : (
        <ul className="list">
          {items.map((i) => (
            <li key={i.id}>
              <Link to={`/publishing/${i.id}`}>
                <strong>{i.title}</strong>
              </Link>
              <span>
                <State s={i.state} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function ComplaintsDesk() {
  const [v, setV] = useState(0);
  const { data, error } = useLoad(() => pub.complaints(), [v]);
  const [resolution, setResolution] = useState<Record<string, string>>({});
  const act = useAction();
  const move = (id: string, status: string) => act.run(() => pub.handleComplaint(id, { status, resolution: resolution[id] ?? "" }), () => setV(v + 1));
  if (!data) return <Loading error={error} />;
  return (
    <>
      {act.error && <Notice tone="error">{act.error}</Notice>}
      {data.items.length === 0 ? (
        <p className="muted">No complaints.</p>
      ) : (
        <ul className="list">
          {data.items.map((c) => (
            <li key={c.id}>
              <strong>
                {c.kind} · <State s={c.status} /> {c.article_title ? `· ${c.article_title}` : ""}
              </strong>
              <span>{c.details}</span>
              <span>
                {c.id} · received {c.created_at.slice(0, 10)}
                {c.contact_email ? ` · reply to ${c.contact_email}` : ""}
              </span>
              {c.resolution && <span>Outcome: {c.resolution}</span>}
              {(c.status === "received" || c.status === "investigating") && (
                <>
                  <Input id={`res-${c.id}`} label="Outcome" value={resolution[c.id] ?? ""} onChange={(val) => setResolution({ ...resolution, [c.id]: val })} />
                  <div className="row-actions">
                    {c.status === "received" && (
                      <button type="button" className="btn btn--small btn--ghost" onClick={() => void move(c.id, "investigating")}>
                        Investigate
                      </button>
                    )}
                    <button type="button" className="btn btn--small" onClick={() => void move(c.id, "resolved")}>
                      Resolve
                    </button>
                    <button type="button" className="btn btn--small btn--danger" onClick={() => void move(c.id, "rejected")}>
                      Reject
                    </button>
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

const EDITION_ACTIONS: Record<string, { label: string; roles: (r: Role) => boolean }> = {
  submit: { label: "Send to fact check", roles: isEditor },
  fact_checked: { label: "Mark fact checked", roles: (r) => isEditor(r) || isLegal(r) },
  approve: { label: "Approve", roles: isEditor },
  revise: { label: "Back to draft", roles: (r) => isEditor(r) || isLegal(r) },
  schedule: { label: "Schedule", roles: isEditor },
  send: { label: "Send now", roles: isEditor },
  archive: { label: "Archive", roles: isEditor },
};
const EDITION_FROM: Record<string, string[]> = {
  draft: ["submit"],
  fact_check: ["fact_checked", "revise"],
  fact_checked: ["approve", "revise"],
  approved: ["schedule", "send", "revise"],
  scheduled: ["send", "revise"],
  sent: ["archive"],
  archived: [],
};

function EditionsDesk({ role }: { role: Role }) {
  const [v, setV] = useState(0);
  const { data, error } = useLoad(() => pub.editions(), [v]);
  const articles = useLoad(() => pub.articles(), []);
  const news = useLoad(() => Promise.all((["nigeria", "africa", "global"] as const).map((sec) => pub.news(sec))).then((r) => r.flatMap((x) => x.items)), []);
  const [newsletter, setNewsletter] = useState<"nigerian_tax_brief" | "global_tax_watch">("nigerian_tax_brief");
  const [title, setTitle] = useState("");
  const [intro, setIntro] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [sponsor, setSponsor] = useState("");
  const [when, setWhen] = useState("");
  const [preview, setPreview] = useState<RenderedEdition>();
  const act = useAction();
  const create = (e: FormEvent) => {
    e.preventDefault();
    const items = picked.map((p) => {
      const [kind, id] = p.split(":");
      return { kind, id };
    });
    void act.run(() => pub.createEdition({ newsletter, title, intro, items, sponsorship_id: sponsor || undefined }), () => {
      setTitle("");
      setPicked([]);
      setV(v + 1);
    });
  };
  const options = [
    ...(articles.data?.items ?? []).map((a) => ({ key: `article:${a.id}`, label: `${a.sponsored ? `[${a.label}] ` : ""}${a.title}` })),
    ...(news.data ?? []).filter((n) => !n.url).map((n) => ({ key: `news:${n.id}`, label: `News (${n.section}): ${n.headline}` })),
  ];
  return (
    <>
      {isEditor(role) && (
        <form className="card" onSubmit={create}>
          <h2>New edition</h2>
          <SelectField label="Newsletter" value={newsletter} onChange={setNewsletter} options={[{ value: "nigerian_tax_brief", label: "Nigerian Tax Brief (weekly)" }, { value: "global_tax_watch", label: "Global Tax Watch" }]} />
          <Input id="ed-title" label="Edition title" value={title} onChange={setTitle} />
          <TextArea id="ed-intro" label="Introduction" value={intro} onChange={setIntro} rows={2} />
          <fieldset className="field">
            <legend>Stories</legend>
            {options.length === 0 && <p className="muted small">No published stories yet.</p>}
            {options.map((o) => (
              <CheckField key={o.key} label={o.label} checked={picked.includes(o.key)} onChange={(c) => setPicked(c ? [...picked, o.key] : picked.filter((p) => p !== o.key))} />
            ))}
          </fieldset>
          <Input id="ed-sponsor" label="Sponsor order id (optional)" value={sponsor} onChange={setSponsor} hint="An open newsletter sponsor order. The slot is labelled Sponsored." />
          <button className="btn" disabled={!title || !picked.length}>
            Create draft
          </button>
        </form>
      )}
      {act.error && <Notice tone="error">{act.error}</Notice>}
      {!data ? (
        <Loading error={error} />
      ) : (
        <ul className="list">
          {data.items.map((e: Edition) => (
            <li key={e.id}>
              <strong>
                {e.newsletter_name}: {e.title} <State s={e.state} />
              </strong>
              <span>
                {e.items.length} stories{e.sponsor ? ` · Sponsored by ${e.sponsor.sponsor}` : ""}
                {e.sent_at ? ` · sent to ${e.sent_count} on ${e.sent_at.slice(0, 10)}` : ""}
                {e.scheduled_for ? ` · scheduled ${e.scheduled_for.slice(0, 16).replace("T", " ")}` : ""}
              </span>
              {e.send_blockers.length > 0 && <span>Cannot send yet: {e.send_blockers.join(" ")}</span>}
              <div className="row-actions">
                <button type="button" className="btn btn--small btn--ghost" onClick={() => void act.run(async () => setPreview(await pub.previewEdition(e.id)))}>
                  Preview
                </button>
                {(EDITION_FROM[e.state] ?? [])
                  .filter((a) => EDITION_ACTIONS[a].roles(role))
                  .map((a) => (
                    <button
                      key={a}
                      type="button"
                      className="btn btn--small"
                      disabled={a === "schedule" && !when}
                      onClick={() => void act.run(() => pub.editionAct(e.id, a, a === "schedule" ? { scheduled_for: when } : {}), () => setV(v + 1))}
                    >
                      {EDITION_ACTIONS[a].label}
                    </button>
                  ))}
              </div>
            </li>
          ))}
        </ul>
      )}
      {isEditor(role) && <Input id="ed-when" type="datetime-local" label="Schedule time for the Schedule button (UTC)" value={when} onChange={setWhen} />}
      {preview && (
        <section className="card" aria-live="polite">
          <h2>Preview: {preview.subject}</h2>
          <pre className="pub-preview">{preview.text}</pre>
        </section>
      )}
    </>
  );
}

function CheckoutNote({ r }: { r?: CheckoutResult }) {
  if (!r) return null;
  if (!r.billing_available) return <Notice tone="warn">{r.message}</Notice>;
  return (
    <Notice>
      Checkout created ({r.mode === "sandbox" ? "sandbox: no real payment will be taken" : r.mode}). Send this payment link to the sponsor: <a href={r.checkout?.url}>{r.checkout?.url}</a>
    </Notice>
  );
}

function SponsorshipDesk({ role }: { role: Role }) {
  const [v, setV] = useState(0);
  const { data, error } = useLoad(() => pub.sponsorships(), [v]);
  const [form, setForm] = useState({ sponsor_name: "", funding_relationship: "", placement: "sponsored_article", label: "Sponsored", arcon_required: false, arcon_reference: "", amount_kobo: "", description: "" });
  const [attach, setAttach] = useState<Record<string, string>>({});
  const [arcon, setArcon] = useState<Record<string, string>>({});
  const [checkout, setCheckout] = useState<CheckoutResult>();
  const act = useAction();
  const refresh = () => setV(v + 1);
  const create = (e: FormEvent) => {
    e.preventDefault();
    void act.run(() => pub.createSponsorship({ ...form, amount_kobo: Number.parseInt(form.amount_kobo, 10) }), refresh);
  };
  if (!data) return <Loading error={error} />;
  return (
    <>
      <Notice tone={data.audience.open ? "info" : "warn"}>
        Audience {data.audience.subscribers} of {data.audience.threshold} subscribers. Sponsored publishing is {data.audience.open ? "open" : "closed until the threshold is reached"}.
      </Notice>
      <Notice>Payment state never affects editorial approval, and payment never publishes anything.</Notice>
      {isSales(role) && (
        <form className="card" onSubmit={create}>
          <h2>New sponsorship order</h2>
          <div className="grid-2">
            <Input id="sp-name" label="Sponsor" value={form.sponsor_name} onChange={(x) => setForm({ ...form, sponsor_name: x })} />
            <Input id="sp-rel" label="Funding relationship" value={form.funding_relationship} onChange={(x) => setForm({ ...form, funding_relationship: x })} />
            <SelectField label="Placement" value={form.placement} onChange={(x) => setForm({ ...form, placement: x })} options={[{ value: "sponsored_article", label: "Sponsored article" }, { value: "newsletter_sponsor", label: "Newsletter sponsor slot" }]} />
            <SelectField label="Label" value={form.label} onChange={(x) => setForm({ ...form, label: x })} options={[{ value: "Sponsored", label: "Sponsored" }, { value: "Paid Partnership", label: "Paid Partnership" }]} />
            <Input id="sp-amt" label="Agreed amount (kobo)" value={form.amount_kobo} onChange={(x) => setForm({ ...form, amount_kobo: x.replace(/\D/g, "") })} hint="Whole kobo. Rate card prices are still to be set." />
            <Input id="sp-desc" label="Description" value={form.description} onChange={(x) => setForm({ ...form, description: x })} />
          </div>
          <CheckField label="ARCON vetting required" checked={form.arcon_required} onChange={(x) => setForm({ ...form, arcon_required: x })} />
          {form.arcon_required && <Input id="sp-arcon" label="ARCON vetting reference" value={form.arcon_reference} onChange={(x) => setForm({ ...form, arcon_reference: x })} />}
          <button className="btn">Create order</button>
        </form>
      )}
      {act.error && <Notice tone="error">{act.error}</Notice>}
      <CheckoutNote r={checkout} />
      <ul className="list">
        {data.items.map((o) => (
          <li key={o.id}>
            <strong>
              {o.sponsor_name} · {o.placement.replace("_", " ")} · <State s={o.status} /> <span className="pill pill--muted">{o.payment_status.replace("_", " ")}</span>
            </strong>
            <span>
              {o.id} · {o.label} · {o.funding_relationship} · amount {o.amount}
              {o.arcon_required ? ` · ARCON ${o.arcon_reference ?? "reference missing"}` : ""}
            </span>
            {o.articles.map((a) => (
              <span key={a.id}>
                Article: <Link to={`/publishing/${a.id}`}>{a.title}</Link> ({STATE_LABEL[a.state] ?? a.state})
              </span>
            ))}
            {o.rejection_reason && <span>Rejected: {o.rejection_reason}</span>}
            {o.status === "open" && (
              <div className="row-actions">
                {isSales(role) && o.payment_status === "unpaid" && (
                  <button type="button" className="btn btn--small" onClick={() => void act.run(async () => setCheckout(await pub.checkout(o.id)), refresh)}>
                    Create payment link
                  </button>
                )}
                {isSales(role) && o.placement === "sponsored_article" && (
                  <>
                    <Input id={`att-${o.id}`} label="Article id to sponsor" value={attach[o.id] ?? ""} onChange={(x) => setAttach({ ...attach, [o.id]: x })} />
                    <button type="button" className="btn btn--small btn--ghost" disabled={!attach[o.id]} onClick={() => void act.run(() => pub.attach(o.id, attach[o.id]), refresh)}>
                      Attach
                    </button>
                  </>
                )}
                {isSales(role) && o.arcon_required && (
                  <>
                    <Input id={`arc-${o.id}`} label="ARCON reference" value={arcon[o.id] ?? o.arcon_reference ?? ""} onChange={(x) => setArcon({ ...arcon, [o.id]: x })} />
                    <button type="button" className="btn btn--small btn--ghost" onClick={() => void act.run(() => pub.updateSponsorship(o.id, { arcon_reference: arcon[o.id] ?? "" }), refresh)}>
                      Save reference
                    </button>
                  </>
                )}
                <button
                  type="button"
                  className="btn btn--small btn--danger"
                  onClick={() => {
                    const reason = window.prompt("Reason for rejection under the published terms");
                    if (reason) void act.run(() => pub.reject(o.id, reason), refresh);
                  }}
                >
                  Reject
                </button>
              </div>
            )}
            {isSales(role) && o.payment_status === "refund_due" && (
              <button type="button" className="btn btn--small" onClick={() => void act.run(() => pub.refunded(o.id), refresh)}>
                Record refund made
              </button>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

function AdsDesk({ role }: { role: Role }) {
  const [v, setV] = useState(0);
  const { data, error } = useLoad(() => pub.campaigns(), [v]);
  const [form, setForm] = useState({ advertiser: "", starts_on: "", ends_on: "", slots: ["home_sidebar"] as string[], amount_kobo: "" });
  const [creative, setCreative] = useState<Record<string, { headline: string; body: string; link_url: string }>>({});
  const [checkout, setCheckout] = useState<CheckoutResult>();
  const act = useAction();
  const refresh = () => setV(v + 1);
  const slots = ["home_sidebar", "article_inline", "news_sidebar", "newsletter"];
  const create = (e: FormEvent) => {
    e.preventDefault();
    const body: Record<string, unknown> = { advertiser: form.advertiser, starts_on: form.starts_on, ends_on: form.ends_on, slots: form.slots };
    if (form.amount_kobo) body.amount_kobo = Number.parseInt(form.amount_kobo, 10);
    void act.run(() => pub.createCampaign(body), refresh);
  };
  if (!data) return <Loading error={error} />;
  return (
    <>
      <Notice>Ads run only on public pages, never in the app or on sensitive screens, and are never targeted. Every creative needs staff approval.</Notice>
      {!data.audience.open && <Notice tone="warn">Display advertising opens once the newsletter reaches {data.audience.threshold} subscribers.</Notice>}
      {isSales(role) && (
        <form className="card" onSubmit={create}>
          <h2>New campaign</h2>
          <div className="grid-2">
            <Input id="ad-adv" label="Advertiser" value={form.advertiser} onChange={(x) => setForm({ ...form, advertiser: x })} />
            <Input id="ad-amt" label="Agreed amount (kobo, optional)" value={form.amount_kobo} onChange={(x) => setForm({ ...form, amount_kobo: x.replace(/\D/g, "") })} />
            <Input id="ad-start" type="date" label="Starts" value={form.starts_on} onChange={(x) => setForm({ ...form, starts_on: x })} />
            <Input id="ad-end" type="date" label="Ends" value={form.ends_on} onChange={(x) => setForm({ ...form, ends_on: x })} />
          </div>
          <fieldset className="field">
            <legend>Placements</legend>
            {slots.map((s) => (
              <CheckField key={s} label={s.replace("_", " ")} checked={form.slots.includes(s)} onChange={(c) => setForm({ ...form, slots: c ? [...form.slots, s] : form.slots.filter((x) => x !== s) })} />
            ))}
          </fieldset>
          <button className="btn">Create campaign</button>
        </form>
      )}
      {act.error && <Notice tone="error">{act.error}</Notice>}
      <CheckoutNote r={checkout} />
      <ul className="list">
        {data.items.map((c: Campaign) => {
          const draft = creative[c.id] ?? { headline: "", body: "", link_url: "https://" };
          return (
            <li key={c.id}>
              <strong>
                {c.advertiser} · <State s={c.status} /> <span className="pill pill--muted">{c.payment_status}</span>
              </strong>
              <span>
                {c.starts_on} to {c.ends_on} · {c.slots.join(", ")} · amount {c.amount}
              </span>
              {c.creatives.map((k) => (
                <span key={k.id} className="pub-creative">
                  <State s={k.review_status} /> {k.headline} ({k.link_url}) · {k.impressions} impressions, {k.clicks} clicks
                  {(isEditor(role) || isSupport(role)) && k.review_status === "pending" && (
                    <span className="row-actions">
                      <button type="button" className="btn btn--small" onClick={() => void act.run(() => pub.review(k.id, "approved"), refresh)}>
                        Approve creative
                      </button>
                      <button
                        type="button"
                        className="btn btn--small btn--danger"
                        onClick={() => {
                          const note = window.prompt("Why is this creative rejected?");
                          if (note) void act.run(() => pub.review(k.id, "rejected", note), refresh);
                        }}
                      >
                        Reject
                      </button>
                    </span>
                  )}
                </span>
              ))}
              {isSales(role) && !["ended", "rejected"].includes(c.status) && (
                <div className="pub-creative-form">
                  <Input id={`cr-h-${c.id}`} label="Creative headline" value={draft.headline} onChange={(x) => setCreative({ ...creative, [c.id]: { ...draft, headline: x } })} />
                  <Input id={`cr-b-${c.id}`} label="Creative text" value={draft.body} onChange={(x) => setCreative({ ...creative, [c.id]: { ...draft, body: x } })} />
                  <Input id={`cr-l-${c.id}`} label="Link (https)" value={draft.link_url} onChange={(x) => setCreative({ ...creative, [c.id]: { ...draft, link_url: x } })} />
                  <div className="row-actions">
                    <button type="button" className="btn btn--small btn--ghost" disabled={!draft.headline} onClick={() => void act.run(() => pub.addCreative(c.id, draft), refresh)}>
                      Add creative
                    </button>
                    {c.status === "draft" || c.status === "paused" ? (
                      <button type="button" className="btn btn--small" onClick={() => void act.run(() => pub.campaignStatus(c.id, "active"), refresh)}>
                        Activate
                      </button>
                    ) : (
                      <button type="button" className="btn btn--small btn--ghost" onClick={() => void act.run(() => pub.campaignStatus(c.id, "paused"), refresh)}>
                        Pause
                      </button>
                    )}
                    {c.payment_status === "unpaid" && c.amount !== "0.00" && (
                      <button type="button" className="btn btn--small btn--ghost" onClick={() => void act.run(async () => setCheckout(await pub.campaignCheckout(c.id)), refresh)}>
                        Create payment link
                      </button>
                    )}
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}

function ReportsDesk() {
  const { data, error } = useLoad(() => pub.reports(), []);
  if (!data) return <Loading error={error} />;
  return (
    <>
      <p className="small muted">Aggregate counts only. No personal data, cookies or IP addresses are stored for ads.</p>
      <h2>Ad campaigns</h2>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Advertiser</th>
              <th scope="col">Status</th>
              <th scope="col">Impressions</th>
              <th scope="col">Clicks</th>
            </tr>
          </thead>
          <tbody>
            {data.campaigns.map((c) => (
              <tr key={c.id}>
                <th scope="row">{c.advertiser}</th>
                <td>{STATE_LABEL[c.status] ?? c.status}</td>
                <td>{c.impressions ?? 0}</td>
                <td>{c.clicks ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2>Sponsorships</h2>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Sponsor</th>
              <th scope="col">Order</th>
              <th scope="col">Payment</th>
              <th scope="col">Content</th>
            </tr>
          </thead>
          <tbody>
            {data.sponsorships.map((o) => (
              <tr key={o.id}>
                <th scope="row">{o.sponsor_name}</th>
                <td>{o.status}</td>
                <td>{o.payment_status.replace("_", " ")}</td>
                <td>{[...o.articles.map((a) => `${a.title} (${a.state})`), ...o.editions.map((e) => `${e.title} (${e.state})`)].join("; ") || "None yet"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function DashboardCard({ ctx }: { ctx: AppContext }) {
  const { data } = useLoad(() => pub.dashboard(), []);
  if (ctx.me.staff_role === "none" || !data) return null;
  const by = data.articles_by_state;
  return (
    <Link to={isSales(data.role as Role) && !isEditor(data.role as Role) ? "/publishing/desk/sponsorships" : isLegal(data.role as Role) && !isEditor(data.role as Role) ? "/publishing/desk/signoff" : "/publishing/desk/queue"} className="card card--link">
      <h2>Publishing desk</h2>
      <p>
        {(by.submitted ?? 0) + (by.screening ?? 0)} to screen · {data.awaiting_legal_signoff} awaiting legal sign-off · {data.creatives_pending_review} ad creatives to review ·{" "}
        {data.open_complaints} open complaints
      </p>
    </Link>
  );
}

export const appModule: AppModule = {
  id: "publishing",
  routes: [
    ["/publishing", (ctx) => <MySubmissions ctx={ctx} />],
    ["/publishing/new", (ctx) => <NewSubmission ctx={ctx} />],
    ["/publishing/desk/:tab", (ctx) => <Desk ctx={ctx} />],
    ["/publishing/:id", (ctx) => <SubmissionPage key={ctx.params.id} ctx={ctx} />],
  ],
  dashboard: (ctx) => (ctx.me.staff_role === "none" ? null : <DashboardCard key="publishing" ctx={ctx} />),
};
