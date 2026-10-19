// Public adviser directory (ADV-01, ADV-04, GOV-04). Default order is relevance to the
// search only. A paid placement appears in its own labelled "Sponsored listing" slot and
// never changes the order of the main list.
import { useState } from "react";
import { Loading, SelectField, useLoad } from "../../components/ui";
import { Link } from "../../router";
import type { SiteModule } from "../types";
import { advisoryApi as api } from "./api";
import { AdviserCard, PractitionerNotice, VerifiedBadge } from "./shared";

function Directory() {
  const meta = useLoad(() => api.meta(), []);
  const [specialism, setSpecialism] = useState("");
  const [state, setState] = useState("");
  const list = useLoad(() => api.directory(specialism || undefined, state || undefined), [specialism, state]);
  if (!meta.data) return <Loading error={meta.error} />;
  const labels = Object.fromEntries(meta.data.specialisms.map((s) => [s.id, s.label]));
  return (
    <>
      <h1>Find a tax adviser</h1>
      <p className="lede">Chartered tax practitioners and accountants whose membership we check against the professional registers.</p>
      <div className="grid-2 adv-filters">
        <SelectField
          label="Specialism"
          value={specialism}
          onChange={setSpecialism}
          options={[{ value: "", label: "Any specialism" }, ...meta.data.specialisms.map((s) => ({ value: s.id, label: s.label }))]}
        />
        <SelectField
          label="State"
          value={state}
          onChange={setState}
          options={[{ value: "", label: "Anywhere in Nigeria" }, ...meta.data.states.map((s) => ({ value: s, label: s }))]}
        />
      </div>
      {!list.data ? (
        <Loading error={list.error} />
      ) : (
        <>
          {list.data.sponsored.length > 0 && (
            <aside className="ad-slot adv-sponsored" aria-label={list.data.sponsored_label}>
              <span className="sponsored-label">{list.data.sponsored_label}</span>
              <p className="small muted">Paid placement. It does not affect the order of the results below.</p>
              {list.data.sponsored.map((a) => (
                <AdviserCard key={a.id} a={a} labels={labels} action={<Link to={`/advisers/${a.id}`}>View profile</Link>} />
              ))}
            </aside>
          )}
          <h2 className="sr-only">Results</h2>
          <p className="muted small" aria-live="polite">
            {list.data.items.length} {list.data.items.length === 1 ? "adviser" : "advisers"}, ordered by how well they match your search.
          </p>
          <div className="cards">
            {list.data.items.map((a) => (
              <AdviserCard key={a.id} a={a} labels={labels} action={<Link to={`/advisers/${a.id}`}>View profile</Link>} />
            ))}
          </div>
          <PractitionerNotice text={list.data.practitioner_notice} />
        </>
      )}
    </>
  );
}

function AdviserProfile({ id }: { id: string }) {
  const meta = useLoad(() => api.meta(), []);
  const adviser = useLoad(() => api.adviser(id), [id]);
  if (!adviser.data || !meta.data) return <Loading error={adviser.error ?? meta.error} />;
  const a = adviser.data;
  const labels = Object.fromEntries(meta.data.specialisms.map((s) => [s.id, s.label]));
  return (
    <div className="narrow">
      <p className="crumbs">
        <Link to="/advisers">Advisers</Link>
      </p>
      <h1>{a.name}</h1>
      <p className="lede">{[a.firm, a.location, a.state].filter(Boolean).join(" · ")}</p>
      <VerifiedBadge v={a.verification} />
      {a.memberships.length > 0 && (
        <p className="small">
          Memberships: {a.memberships.map((m) => `${m.register} ${m.number}`).join("; ")}
        </p>
      )}
      <h2>Specialisms</h2>
      <ul>
        {a.specialisms.map((s) => (
          <li key={s}>{labels[s] ?? s}</li>
        ))}
      </ul>
      {a.bio && (
        <>
          <h2>About</h2>
          <p>{a.bio}</p>
        </>
      )}
      <p>
        <a className="btn" href={`/app/#/advisory/book/${encodeURIComponent(a.id)}`}>
          Request a booking
        </a>
      </p>
      <p className="small muted">
        Before your request is sent you choose exactly what, if anything, this adviser can see. Your health-check report is shared only if
        you allow it later, and you can withdraw that at any time.
      </p>
      <PractitionerNotice text={a.practitioner_notice} />
    </div>
  );
}

export const siteModule: SiteModule = {
  id: "advisory",
  routes: [
    ["/advisers", () => <Directory />],
    ["/advisers/:id", (p) => <AdviserProfile id={p.id} />],
  ],
};
