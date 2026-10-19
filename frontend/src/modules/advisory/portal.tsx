// Adviser portal (ADV-01 to ADV-04): listing application and edits, verification,
// sponsored placement, booking requests, engagements and the client report view
// (only while the client's consent is in force). Staff review of listings.
import { useState, type FormEvent } from "react";
import { PageHead } from "../../app/core";
import { ApiError } from "../../http";
import { CheckField, Loading, Notice, SelectField, errorText, useLoad } from "../../components/ui";
import { date } from "../../format";
import { Link } from "../../router";
import { ReportView } from "../compliance/report";
import type { AppContext } from "../types";
import { advisoryApi as api, type AdvisoryMeta, type MyListing } from "./api";
import { PractitionerNotice, VerifiedBadge } from "./shared";

const LISTING_TONE: Record<string, string> = { pending: "warn", approved: "ok", rejected: "bad", suspended: "bad" };

function ListingForm({ meta, listing, onSaved }: { meta: AdvisoryMeta; listing?: MyListing; onSaved: (l: MyListing) => void }) {
  const [v, setV] = useState({
    name: listing?.name ?? "",
    firm: listing?.firm ?? "",
    state: listing?.state ?? "Lagos",
    location: listing?.location ?? "",
    bio: listing?.bio ?? "",
    citn_number: listing?.citn_number ?? "",
    ican_number: listing?.ican_number ?? "",
  });
  const [specs, setSpecs] = useState<string[]>(listing?.specialisms ?? []);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState<string>();
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setFields({});
    setError(undefined);
    try {
      const body = { ...v, specialisms: specs };
      onSaved(listing ? await api.updateMine(body) : await api.apply(body));
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fields).length) setFields(err.fields);
      else setError(errorText(err));
    }
  };
  const text = (key: keyof typeof v, label: string, hint?: string) => (
    <div className={`field${fields[key] ? " field--error" : ""}`}>
      <label htmlFor={`adv-${key}`}>{label}</label>
      <input id={`adv-${key}`} value={v[key]} onChange={set(key)} />
      {(fields[key] || hint) && <p className="field__hint">{fields[key] ?? hint}</p>}
    </div>
  );
  return (
    <form className="card" onSubmit={submit} noValidate>
      <h2>{listing ? "Edit my listing" : "Apply to be listed"}</h2>
      {text("name", "Name shown in the directory")}
      {text("firm", "Firm (optional)")}
      <SelectField label="State" value={v.state} onChange={(x) => setV({ ...v, state: x })} options={meta.states.map((s) => ({ value: s, label: s }))} error={fields.state} />
      {text("location", "Town or city (optional)")}
      <fieldset>
        <legend>Specialisms</legend>
        {meta.specialisms.map((s) => (
          <CheckField key={s.id} label={s.label} checked={specs.includes(s.id)} onChange={(on) => setSpecs(on ? [...specs, s.id] : specs.filter((x) => x !== s.id))} />
        ))}
        {fields.specialisms && <p className="field__hint">{fields.specialisms}</p>}
      </fieldset>
      {text("citn_number", "CITN membership number", "Changing a membership number sends your listing back for review.")}
      {text("ican_number", "ICAN membership number")}
      <div className="field">
        <label htmlFor="adv-bio">About you (optional)</label>
        <textarea id="adv-bio" maxLength={1500} value={v.bio} onChange={set("bio")} />
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      <button className="btn">{listing ? "Save changes" : "Submit application"}</button>
    </form>
  );
}

export function AdviserPortal() {
  const meta = useLoad(() => api.meta(), []);
  const [version, setVersion] = useState(0);
  const mine = useLoad(() => api.mine().catch((err: unknown) => (err instanceof ApiError && err.status === 404 ? null : Promise.reject(err))), [version]);
  const requests = useLoad(() => (mine.data ? api.requests() : Promise.resolve({ items: [] })), [mine.data?.id, version]);
  const engagements = useLoad(() => (mine.data ? api.adviserEngagements() : Promise.resolve({ items: [] })), [mine.data?.id, version]);
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState<string>();
  const refresh = () => setVersion(version + 1);

  if (!meta.data || mine.data === undefined) return <Loading error={meta.error ?? mine.error} />;
  const listing = mine.data;
  if (!listing)
    return (
      <>
        <p>Chartered tax practitioners and accountants can apply to appear in the directory. We check your membership with the register first.</p>
        <ListingForm meta={meta.data} onSaved={refresh} />
      </>
    );

  const buy = async () => {
    setNotice(undefined);
    try {
      const r = await api.buyPlacement();
      window.location.href = r.checkout.url;
    } catch (err) {
      setNotice(errorText(err));
    }
  };
  const reverify = async () => {
    await api.reverify();
    refresh();
  };

  return (
    <div className="adv-portal">
      <section className="card">
        <h2>
          My listing <span className={`pill pill--${LISTING_TONE[listing.status]}`}>{listing.status}</span>
        </h2>
        <VerifiedBadge v={listing.verification} />
        {listing.verification.expires_at && <p className="small muted">Re-verification due by {date(listing.verification.expires_at.slice(0, 10))}.</p>}
        {listing.review_note && <p className="small">Reviewer note: {listing.review_note}</p>}
        <div className="row-actions">
          <button type="button" className="btn btn--ghost btn--small" onClick={() => setEditing(!editing)}>
            {editing ? "Close" : "Edit listing"}
          </button>
          <button type="button" className="btn btn--ghost btn--small" onClick={() => void reverify()}>
            Re-verify membership
          </button>
          {listing.status === "approved" && (
            <button type="button" className="btn btn--small" onClick={() => void buy()}>
              Buy a sponsored listing
            </button>
          )}
        </div>
        {notice && <Notice tone="warn">{notice}</Notice>}
        <p className="small muted">A sponsored listing appears in a separate, labelled slot. It never changes the order of search results.</p>
      </section>
      {editing && (
        <ListingForm
          meta={meta.data}
          listing={listing}
          onSaved={() => {
            setEditing(false);
            refresh();
          }}
        />
      )}
      <section className="card">
        <h2>Booking requests</h2>
        {!requests.data ? (
          <Loading error={requests.error} />
        ) : requests.data.items.length === 0 ? (
          <p className="small">No requests yet.</p>
        ) : (
          <ul className="list">
            {requests.data.items.map((b) => (
              <li key={b.id}>
                <Link to={`/advisory/requests/${b.id}`}>{b.topic}</Link>
                <span>
                  {b.status} · {date(b.created_at.slice(0, 10))} · client shared {b.intake_fields.length} item(s)
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="card">
        <h2>Engagements</h2>
        {!engagements.data ? (
          <Loading error={engagements.error} />
        ) : engagements.data.items.length === 0 ? (
          <p className="small">No engagements yet.</p>
        ) : (
          <ul className="list">
            {engagements.data.items.map((e) => (
              <li key={e.id}>
                <strong>{e.topic}</strong>
                <span>
                  {e.status} · {e.consent ? "client has shared their health-check report" : "no report access"}
                </span>
                {e.consent && e.status === "active" && <Link to={`/advisory/engagements/${e.id}/report`}>View client report</Link>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

export function RequestPage({ ctx }: { ctx: AppContext }) {
  const id = ctx.params.id;
  const [version, setVersion] = useState(0);
  const booking = useLoad(() => api.request(id), [id, version]);
  const [error, setError] = useState<string>();
  const decide = async (decision: "accept" | "decline") => {
    setError(undefined);
    try {
      await api.decide(id, decision);
      setVersion(version + 1);
    } catch (err) {
      setError(errorText(err));
    }
  };
  if (!booking.data) return <Loading error={booking.error} />;
  const b = booking.data;
  return (
    <>
      <PageHead title={b.topic} intro={`Booking request, ${b.status}`} />
      <p>
        <Link to="/advisory">Back to the portal</Link>
      </p>
      <section className="card">
        {b.message && <p>{b.message}</p>}
        {b.preferred_date && <p className="small">Preferred date: {date(b.preferred_date)}</p>}
        <h2>What the client chose to share</h2>
        <p className="small muted">Your access to this information is logged and visible to the client.</p>
        {!b.intake || b.intake.fields.length === 0 ? (
          <p className="small">{b.intake ? "The client did not share any profile information." : "Shared information is no longer available for this request."}</p>
        ) : (
          <dl className="hc-dl">
            {b.intake.fields.map((f) => (
              <div key={f}>
                <dt>{f.replace(/^fact\./, "").replace(/[._]/g, " ")}</dt>
                <dd>
                  {Array.isArray(b.intake!.data[f])
                    ? (b.intake!.data[f] as { dimension: string; status: string }[]).map((d) => `${d.dimension}: ${d.status.replace(/_/g, " ")}`).join("; ")
                    : String(b.intake!.data[f])}
                </dd>
              </div>
            ))}
          </dl>
        )}
        {b.status === "requested" && (
          <div className="row-actions">
            <button type="button" className="btn" onClick={() => void decide("accept")}>
              Accept
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => void decide("decline")}>
              Decline
            </button>
          </div>
        )}
        {error && <Notice tone="error">{error}</Notice>}
        <PractitionerNotice text={b.practitioner_notice} />
      </section>
    </>
  );
}

export function ClientReportPage({ ctx }: { ctx: AppContext }) {
  const data = useLoad(() => api.clientReport(ctx.params.id), [ctx.params.id]);
  return (
    <>
      <PageHead title="Client health-check report" intro="Shared by your client for this engagement. Read only; every view is logged and visible to the client." />
      <p>
        <Link to="/advisory">Back to the portal</Link>
      </p>
      {!data.data ? (
        <Loading error={data.error} />
      ) : data.data.report ? (
        <ReportView report={data.data.report} />
      ) : (
        <p>The client has not completed a health check yet.</p>
      )}
    </>
  );
}

export function StaffReview() {
  const [status, setStatus] = useState("pending");
  const [version, setVersion] = useState(0);
  const list = useLoad(() => api.staffList(status), [status, version]);
  const [error, setError] = useState<string>();
  const decide = async (id: string, decision: string) => {
    setError(undefined);
    try {
      await api.staffDecide(id, decision);
      setVersion(version + 1);
    } catch (err) {
      setError(errorText(err));
    }
  };
  return (
    <section>
      <SelectField
        label="Show listings"
        value={status}
        onChange={setStatus}
        options={["pending", "approved", "suspended", "rejected"].map((s) => ({ value: s, label: s }))}
      />
      {error && <Notice tone="error">{error}</Notice>}
      {!list.data ? (
        <Loading error={list.error} />
      ) : list.data.items.length === 0 ? (
        <p className="small">Nothing here.</p>
      ) : (
        <ul className="list">
          {list.data.items.map((a) => (
            <li key={a.id}>
              <strong>
                {a.name} {a.firm && `(${a.firm})`}
              </strong>
              <span>
                {a.state} · CITN {a.citn_number ?? "none"} · ICAN {a.ican_number ?? "none"}
              </span>
              <VerifiedBadge v={a.verification} />
              <div className="row-actions">
                {(a.status === "pending" || a.status === "suspended") && (
                  <button type="button" className="btn btn--small" disabled={a.verification.status !== "verified"} onClick={() => void decide(a.id, "approve")}>
                    Approve
                  </button>
                )}
                {a.status === "pending" && (
                  <button type="button" className="btn btn--ghost btn--small" onClick={() => void decide(a.id, "reject")}>
                    Reject
                  </button>
                )}
                {a.status === "approved" && (
                  <button type="button" className="btn btn--danger btn--small" onClick={() => void decide(a.id, "suspend")}>
                    Suspend
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
