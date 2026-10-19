// Signed-in advisory pages (ADV-02, ADV-03, ADV-05, GOV-04): my bookings and engagements,
// the pre-engagement consent step, consents, the adviser portal and staff review.
import { useState } from "react";
import { PageHead } from "../../app/core";
import { CheckField, Loading, Notice, errorText, useLoad } from "../../components/ui";
import { date } from "../../format";
import { Link } from "../../router";
import type { AppContext, AppModule } from "../types";
import { advisoryApi as api, type Booking, type Engagement } from "./api";
import { AdviserPortal, ClientReportPage, RequestPage, StaffReview } from "./portal";
import { AdviserCard, PractitionerNotice } from "./shared";

const STATUS_TONE: Record<string, string> = { requested: "warn", accepted: "ok", declined: "muted", cancelled: "muted", active: "ok", ended: "muted" };

function EngagementPanel({ e, onChange }: { e: Engagement; onChange: () => void }) {
  const [error, setError] = useState<string>();
  const act = async (fn: () => Promise<unknown>, confirmText?: string) => {
    if (confirmText && !window.confirm(confirmText)) return;
    setError(undefined);
    try {
      await fn();
      onChange();
    } catch (err) {
      setError(errorText(err));
    }
  };
  return (
    <div className="adv-engagement">
      <p className="small">
        Engagement <span className={`pill pill--${STATUS_TONE[e.status]}`}>{e.status}</span> since {date(e.created_at.slice(0, 10))}
      </p>
      {e.status === "active" &&
        (e.consent ? (
          <p className="small">
            The adviser can read your latest health-check report (granted {date(e.consent.granted_at.slice(0, 10))}).{" "}
            <button type="button" className="btn btn--ghost btn--small" onClick={() => void act(() => api.revoke(e.id))}>
              Withdraw access
            </button>
          </p>
        ) : (
          <p className="small">
            The adviser cannot see your health-check report.{" "}
            <button
              type="button"
              className="btn btn--small"
              onClick={() =>
                void act(
                  () => api.grant(e.id, ["health_check_report"]),
                  "Allow this adviser to read your latest tax health-check report for this engagement? You can withdraw this at any time, and every access is logged.",
                )
              }
            >
              Share my health-check report
            </button>
          </p>
        ))}
      <div className="row-actions">
        <Link to={`/advisory/engagements/${e.id}/log`} className="btn btn--ghost btn--small">
          Who has accessed my data
        </Link>
        {e.status === "active" && (
          <button type="button" className="btn btn--ghost btn--small" onClick={() => void act(() => api.end(e.id), "End this engagement? The adviser loses any access.")}>
            End engagement
          </button>
        )}
      </div>
      <PractitionerNotice text={e.terms_notice} />
      {error && <Notice tone="error">{error}</Notice>}
    </div>
  );
}

function MyBookings() {
  const [version, setVersion] = useState(0);
  const bookings = useLoad(() => api.bookings(), [version]);
  const refresh = () => setVersion(version + 1);
  if (!bookings.data) return <Loading error={bookings.error} />;
  if (!bookings.data.items.length)
    return (
      <p>
        You have no bookings yet. <a href="/#/advisers">Find an adviser</a>.
      </p>
    );
  return (
    <ul className="list">
      {bookings.data.items.map((b: Booking) => (
        <li key={b.id}>
          <strong>
            {b.topic} with {b.adviser.name}
          </strong>
          <span>
            <span className={`pill pill--${STATUS_TONE[b.status]}`}>{b.status}</span> requested {date(b.created_at.slice(0, 10))}
            {b.intake_fields.length ? ` · shared ${b.intake_fields.length} item(s)` : " · nothing shared"}
          </span>
          {b.status === "requested" && (
            <button type="button" className="btn btn--ghost btn--small" onClick={() => void api.cancel(b.id).then(refresh)}>
              Cancel request
            </button>
          )}
          {b.engagement && <EngagementPanel e={b.engagement} onChange={refresh} />}
        </li>
      ))}
    </ul>
  );
}

function Consents() {
  const [version, setVersion] = useState(0);
  const consents = useLoad(() => api.consents(), [version]);
  const suggestions = useLoad(() => api.suggestions(), [version]);
  const meta = useLoad(() => api.meta(), []);
  const toggle = async (kind: string, granted: boolean) => {
    await api.setConsent(kind, granted);
    setVersion(version + 1);
  };
  if (!consents.data || !meta.data) return <Loading error={consents.error ?? meta.error} />;
  const labels = Object.fromEntries(meta.data.specialisms.map((s) => [s.id, s.label]));
  return (
    <div className="grid-2">
      <section className="card">
        <h2>My choices</h2>
        <p className="small muted">Each choice is separate from any booking or engagement, and you can change it at any time.</p>
        <CheckField label="Suggest advisers using my health-check findings" hint={consents.data.findings_matching.text} checked={consents.data.findings_matching.granted} onChange={(v) => void toggle("findings_matching", v)} />
        <CheckField label="Send me offers about adviser services" hint={consents.data.marketing.text} checked={consents.data.marketing.granted} onChange={(v) => void toggle("marketing", v)} />
      </section>
      <section className="card">
        <h2>Suggested advisers</h2>
        {!suggestions.data ? (
          <Loading error={suggestions.error} />
        ) : suggestions.data.consent_required ? (
          <p className="small">Turn on suggestions to see advisers matched to your health-check findings. Without it, your findings are never used.</p>
        ) : suggestions.data.items.length === 0 ? (
          <p className="small">No matches yet. Complete a health check, or browse the <a href="/#/advisers">directory</a>.</p>
        ) : (
          suggestions.data.items.slice(0, 4).map((a) => (
            <AdviserCard key={a.id} a={a} labels={labels} action={<Link to={`/advisory/book/${a.id}`}>Request a booking</Link>} />
          ))
        )}
      </section>
    </div>
  );
}

function AdvisoryHome({ ctx }: { ctx: AppContext }) {
  const isStaff = ["support", "admin"].includes(ctx.me.staff_role);
  const tabs: [string, string][] = [
    ["bookings", "My bookings"],
    ["choices", "Choices and suggestions"],
    ["adviser", "Adviser portal"],
    ...(isStaff ? ([["review", "Review listings"]] as [string, string][]) : []),
  ];
  const [tab, setTab] = useState("bookings");
  return (
    <>
      <PageHead title="Advisers and bookings" intro="Book a verified adviser, control what they can see, and manage your engagements.">
        <a className="btn" href="/#/advisers">
          Find an adviser
        </a>
      </PageHead>
      <div className="tabs" role="tablist">
        {tabs.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "bookings" && <MyBookings />}
        {tab === "choices" && <Consents />}
        {tab === "adviser" && <AdviserPortal />}
        {tab === "review" && isStaff && <StaffReview />}
      </div>
    </>
  );
}

// ------------------------------------------------------------------ booking with pre-engagement consent (ADV-02)
function BookPage({ ctx }: { ctx: AppContext }) {
  const adviserId = ctx.params.adviserId;
  const adviser = useLoad(() => api.adviser(adviserId), [adviserId]);
  const options = useLoad(() => api.intakeOptions(), []);
  const meta = useLoad(() => api.meta(), []);
  const [step, setStep] = useState<"details" | "consent">("details");
  const [topic, setTopic] = useState("");
  const [message, setMessage] = useState("");
  const [preferred, setPreferred] = useState("");
  const [fields, setFields] = useState<string[]>([]);
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState<string>();
  const [done, setDone] = useState<Booking>();

  if (!adviser.data || !options.data || !meta.data) return <Loading error={adviser.error ?? options.error ?? meta.error} />;
  if (done)
    return (
      <>
        <PageHead title="Request sent" intro={`${adviser.data.name} will accept or decline your request.`} />
        <p>
          You shared {done.intake_fields.length ? done.intake_fields.length + " item(s)" : "nothing"} with this request.{" "}
          <Link to="/advisory">See my bookings</Link>
        </p>
        <PractitionerNotice text={done.practitioner_notice} />
      </>
    );
  const toggleField = (id: string, on: boolean) => setFields(on ? [...fields, id] : fields.filter((f) => f !== id));
  const send = async () => {
    setError(undefined);
    try {
      setDone(await api.book({ adviser_id: adviserId, topic, message, preferred_date: preferred || null, intake_fields: fields, pre_engagement_consent: agreed }));
    } catch (err) {
      setError(errorText(err));
    }
  };
  return (
    <>
      <PageHead title={`Request a booking with ${adviser.data.name}`} intro={adviser.data.firm} />
      <ol className="hc-steps" aria-label="Steps">
        <li>
          <button type="button" aria-current={step === "details" ? "step" : undefined} onClick={() => setStep("details")}>
            Your request
          </button>
        </li>
        <li>
          <button type="button" aria-current={step === "consent" ? "step" : undefined} disabled={!topic} onClick={() => setStep("consent")}>
            What you share
          </button>
        </li>
      </ol>
      {step === "details" ? (
        <form
          className="card"
          onSubmit={(e) => {
            e.preventDefault();
            setStep("consent");
          }}
        >
          <div className="field">
            <label htmlFor="bk-topic">What do you need help with?</label>
            <input id="bk-topic" required maxLength={120} value={topic} onChange={(e) => setTopic(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="bk-message">Anything else the adviser should know (optional)</label>
            <textarea id="bk-message" maxLength={1000} value={message} onChange={(e) => setMessage(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="bk-date">Preferred date (optional)</label>
            <input id="bk-date" type="date" value={preferred} onChange={(e) => setPreferred(e.target.value)} />
          </div>
          <button className="btn" disabled={!topic.trim()}>
            Next: choose what to share
          </button>
        </form>
      ) : (
        <section className="card">
          <h2>Choose what this adviser receives</h2>
          <p className="small">
            Nothing is selected by default. The adviser sees only what you tick here. This is separate from marketing, and it does not give
            access to your health-check report.
          </p>
          {options.data.items.length === 0 ? (
            <p className="small muted">You have no saved tax profile or health check yet, so there is nothing to share.</p>
          ) : (
            options.data.items.map((o) => (
              <CheckField
                key={o.id}
                label={o.label}
                hint={Array.isArray(o.value) ? undefined : `Your answer: ${String(o.value)}`}
                checked={fields.includes(o.id)}
                onChange={(on) => toggleField(o.id, on)}
              />
            ))
          )}
          <hr />
          <CheckField label={meta.data.consent_text.pre_engagement} checked={agreed} onChange={setAgreed} />
          {error && <Notice tone="error">{error}</Notice>}
          <div className="row-actions">
            <button type="button" className="btn btn--ghost" onClick={() => setStep("details")}>
              Back
            </button>
            <button type="button" className="btn" disabled={!agreed} onClick={() => void send()}>
              Send request
            </button>
          </div>
          <PractitionerNotice text={meta.data.practitioner_notice} />
        </section>
      )}
    </>
  );
}

function AccessLogPage({ ctx }: { ctx: AppContext }) {
  const log = useLoad(() => api.accessLog(ctx.params.id), [ctx.params.id]);
  const labels: Record<string, string> = {
    "advisory.client_data_accessed": "Adviser viewed your data",
    "consent.granted": "Consent given",
    "consent.revoked": "Consent withdrawn",
    "advisory.engagement_created": "Engagement started",
    "advisory.engagement_ended": "Engagement ended",
    "advisory.booking_requested": "Booking requested",
    "advisory.booking_accepted": "Booking accepted",
  };
  return (
    <>
      <PageHead title="Who has accessed my data" intro="Every adviser access to your data and every consent change for this engagement." />
      <p>
        <Link to="/advisory">Back to bookings</Link>
      </p>
      {!log.data ? (
        <Loading error={log.error} />
      ) : (
        <ul className="list">
          {log.data.items.map((e, i) => (
            <li key={i}>
              <strong>{labels[e.action] ?? e.action}</strong>
              <span>
                {e.at.replace("T", " ").slice(0, 16)} UTC · by {e.by}
                {typeof e.detail.resource === "string" ? ` · ${e.detail.resource.replace(/_/g, " ")}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function DashboardCard() {
  return (
    <Link key="advisory" to="/advisory" className="card card--link">
      <h2>Advisers and bookings</h2>
      <p>Book a verified adviser and control what they can see.</p>
    </Link>
  );
}

export const appModule: AppModule = {
  id: "advisory",
  routes: [
    ["/advisory", (ctx) => <AdvisoryHome ctx={ctx} />],
    ["/advisory/book/:adviserId", (ctx) => <BookPage ctx={ctx} />],
    ["/advisory/requests/:id", (ctx) => <RequestPage ctx={ctx} />],
    ["/advisory/engagements/:id/report", (ctx) => <ClientReportPage ctx={ctx} />],
    ["/advisory/engagements/:id/log", (ctx) => <AccessLogPage ctx={ctx} />],
  ],
  dashboard: () => <DashboardCard key="advisory" />,
};
