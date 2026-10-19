// Public pages for the publishing module: insights, news sections, contribute,
// advertise, newsletter archive, complaints and unsubscribe.
import { useEffect, useState, type FormEvent } from "react";
import { Loading, Notice, SelectField, errorText, useLoad } from "../../components/ui";
import { date } from "../../format";
import { Link } from "../../router";
import type { SiteModule } from "../types";
import { AdSlot } from "./AdSlot";
import { pub, RSS_URL, type ArticleCard, type Labels, type Section } from "./api";

const SECTION_NAME: Record<Section, string> = { nigeria: "Nigeria", africa: "Africa", global: "Global" };

function day(iso: string | null | undefined): string {
  return iso ? date(iso.slice(0, 10)) : "";
}

/** Badge plus the Sponsored / Paid Partnership label (LAW-05, SPON-03). */
export function ArticleLabels({ tag }: { tag: Pick<Labels, "badge" | "sponsored" | "label"> }) {
  return (
    <span className="pub-labels">
      {tag.sponsored && tag.label ? <span className="sponsored-label">{tag.label}</span> : null}
      <span className="badge badge--kind">{tag.badge}</span>
    </span>
  );
}

function Card({ a }: { a: ArticleCard }) {
  return (
    <li className="card pub-card">
      <ArticleLabels tag={a} />
      <h2>
        <Link to={a.url}>{a.title}</Link>
      </h2>
      <p>{a.summary}</p>
      <p className="muted small">
        {a.author_name}
        {a.affiliation ? `, ${a.affiliation}` : ""} · {day(a.published_at)}
        {a.corrected ? " · Corrected" : ""}
        {a.sponsored && a.sponsor ? ` · Sponsor: ${a.sponsor.name}` : ""}
      </p>
    </li>
  );
}

function Insights() {
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const list = useLoad(() => pub.articles({ type: type || undefined }), [type]);
  const hits = useLoad(() => (query ? pub.search(query) : Promise.resolve({ items: [] })), [query]);
  const go = (e: FormEvent) => {
    e.preventDefault();
    setQuery(q.trim());
  };
  return (
    <>
      <h1>Insights and articles</h1>
      <p className="lede">Commentary, news and opinion on Nigerian and international tax. Every sponsored item is labelled.</p>
      <div className="pub-toolbar">
        <form onSubmit={go} className="pub-search" role="search">
          <label htmlFor="pub-q" className="sr-only">
            Search articles, laws and guides
          </label>
          <input id="pub-q" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search articles, laws and guides" />
          <button className="btn">Search</button>
        </form>
        <SelectField
          label="Type"
          value={type}
          onChange={setType}
          options={[
            { value: "", label: "All types" },
            { value: "commentary", label: "Explanatory commentary" },
            { value: "news", label: "News" },
            { value: "opinion", label: "Opinion" },
            { value: "submission", label: "User submission" },
            { value: "sponsored", label: "Sponsored" },
          ]}
        />
      </div>
      {query && (
        <section aria-live="polite">
          <h2>Results for “{query}”</h2>
          {!hits.data ? (
            <Loading error={hits.error} />
          ) : hits.data.items.length === 0 ? (
            <p className="muted">No matches.</p>
          ) : (
            <ul className="list">
              {hits.data.items.map((h) => (
                <li key={`${h.kind}-${h.id}`}>
                  <span className="pub-labels">
                    {h.sponsored && h.label && <span className="sponsored-label">{h.label}</span>}
                    <span className="badge badge--kind">{h.badge ?? (h.kind === "provision" ? "Law" : "Guide")}</span>
                  </span>
                  <Link to={h.url}>
                    <strong>{h.title}</strong>
                  </Link>
                  {h.summary && <span>{h.summary}</span>}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      <div className="pub-layout">
        <div>
          {!list.data ? (
            <Loading error={list.error} />
          ) : list.data.items.length === 0 ? (
            <Notice>No articles published yet. Want to write one? <Link to="/contribute">Contribute</Link>.</Notice>
          ) : (
            <ul className="news">
              {list.data.items.map((a) => (
                <Card key={a.id} a={a} />
              ))}
            </ul>
          )}
        </div>
        <div className="pub-aside">
          <AdSlot slot="article_inline" />
          <p className="small">
            <a href={RSS_URL}>RSS feed</a> · <Link to="/newsletter/archive">Newsletter archive</Link>
          </p>
        </div>
      </div>
    </>
  );
}

function ComplaintForm({ slug }: { slug?: string }) {
  const [kind, setKind] = useState("accuracy");
  const [details, setDetails] = useState("");
  const [email, setEmail] = useState("");
  const [done, setDone] = useState<{ id: string; token: string }>();
  const [error, setError] = useState<string>();
  const send = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      const res = await pub.complain({ kind, details, article_slug: slug, contact_email: email || undefined });
      setDone({ id: res.id, token: res.tracking_token });
    } catch (err) {
      setError(errorText(err));
    }
  };
  if (done)
    return (
      <Notice>
        Thank you. Your reference is {done.id}. <Link to={`/complaints/${done.id}/${done.token}`}>Track its status</Link> (keep this link).
      </Notice>
    );
  return (
    <form className="card" onSubmit={send}>
      <h2>Report a problem</h2>
      <p className="small">Tell us about an error, a legal concern, undisclosed sponsorship or a takedown request.</p>
      <SelectField
        label="What is the problem?"
        value={kind}
        onChange={setKind}
        options={[
          { value: "accuracy", label: "Factual or legal error" },
          { value: "legal", label: "Legal concern or takedown request" },
          { value: "privacy", label: "Privacy" },
          { value: "sponsorship", label: "Sponsorship or disclosure" },
          { value: "advertising", label: "Advertising" },
          { value: "other", label: "Something else" },
        ]}
      />
      <div className="field">
        <label htmlFor="cmp-details">Details</label>
        <textarea id="cmp-details" rows={4} value={details} onChange={(e) => setDetails(e.target.value)} required minLength={10} />
      </div>
      <div className="field">
        <label htmlFor="cmp-email">Email for a reply (optional)</label>
        <input id="cmp-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      <button className="btn">Send report</button>
    </form>
  );
}

function ArticleView({ slug }: { slug: string }) {
  const { data, error } = useLoad(() => pub.article(slug), [slug]);
  useEffect(() => {
    if (data) document.title = `${data.meta.open_graph?.["og:title"] ?? data.title} | tax.ng`;
  }, [data]);
  if (!data) return <Loading error={error} />;
  if (data.tombstone)
    return (
      <article className="article">
        <p className="crumbs">
          <Link to="/insights">Insights</Link>
        </p>
        <h1>This article has been withdrawn</h1>
        <p className="lede">“{data.title}” was withdrawn on {day(data.withdrawn_at)}.</p>
        <Notice tone="warn">Reason: {data.withdrawn_reason}</Notice>
        {data.corrections.length > 0 && <Corrections items={data.corrections} />}
        <ComplaintForm slug={slug} />
      </article>
    );
  return (
    <article className="article">
      <p className="crumbs">
        <Link to="/insights">Insights</Link>
      </p>
      {data.header_label && (
        <p className="pub-header-label">
          <span className="sponsored-label">{data.header_label}</span>
          {data.sponsor && (
            <span className="small">
              {" "}
              Funded by {data.sponsor.name}. {data.sponsor.funding_relationship}
            </span>
          )}
        </p>
      )}
      <span className="badge badge--kind">{data.badge}</span>
      <h1>{data.title}</h1>
      <p className="lede">{data.summary}</p>
      <p className="muted small">
        By {data.author_name}
        {data.author_credentials ? `, ${data.author_credentials}` : ""}
        {data.affiliation ? ` (${data.affiliation})` : ""} · Published {day(data.published_at)} · Jurisdiction: {data.jurisdiction}
      </p>
      {data.corrections.length > 0 && (
        <Notice tone="warn">
          Corrected {day(data.corrections[data.corrections.length - 1].created_at)}: {data.corrections[data.corrections.length - 1].note}
        </Notice>
      )}
      <div className="article__grid">
        <div>
          {(data.body ?? "").split(/\n{2,}/).map((p, i) => (
            <p key={i}>{p}</p>
          ))}
          <AdSlot slot="article_inline" />
          {data.citations && data.citations.length > 0 && (
            <>
              <h2>Sources</h2>
              <ul className="cites">
                {data.citations.map((c, i) => (
                  <li key={i}>{c.url ? <a href={c.url} target="_blank" rel="noreferrer">{c.text}</a> : c.text}</li>
                ))}
              </ul>
            </>
          )}
          <h2>Disclosures</h2>
          <dl className="pub-dl">
            <dt>Conflicts of interest</dt>
            <dd>{data.conflicts || "None declared"}</dd>
            <dt>Use of AI tools</dt>
            <dd>{data.ai_disclosure || "None declared"}</dd>
            {data.sponsored && (
              <>
                <dt>Sponsorship</dt>
                <dd>{data.sponsor ? `${data.sponsor.name}: ${data.sponsor.funding_relationship}` : "Sponsored content"}</dd>
              </>
            )}
          </dl>
          {data.corrections.length > 0 && <Corrections items={data.corrections} />}
        </div>
        <div>
          <ComplaintForm slug={slug} />
        </div>
      </div>
    </article>
  );
}

function Corrections({ items }: { items: { version: number; note: string; created_at: string }[] }) {
  return (
    <section>
      <h2>Correction history</h2>
      <ul className="list list--tight">
        {items.map((c, i) => (
          <li key={i}>
            <strong>{day(c.created_at)}</strong>
            <span>{c.note}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function NewsSection({ section }: { section: string }) {
  const valid = (["nigeria", "africa", "global"] as const).find((s) => s === section);
  const { data, error } = useLoad(() => (valid ? pub.news(valid) : Promise.reject(new Error("unknown"))), [section]);
  if (!valid) return <Notice tone="error">Unknown news section.</Notice>;
  return (
    <>
      <h1>Tax news: {SECTION_NAME[valid]}</h1>
      <nav className="tabs" aria-label="News sections">
        {(Object.keys(SECTION_NAME) as Section[]).map((s) => (
          <Link key={s} to={`/news/${s}`} aria-current={s === valid ? "page" : undefined}>
            {SECTION_NAME[s]}
          </Link>
        ))}
      </nav>
      <div className="pub-layout">
        <div>
          {!data ? (
            <Loading error={error} />
          ) : data.items.length === 0 ? (
            <p className="muted">No items yet.</p>
          ) : (
            <ul className="news">
              {data.items.map((n) => (
                <li key={n.id} className="card">
                  <p className="muted small">
                    {date(n.date)}
                    {n.sample && <span className="badge badge--unverified">Sample item</span>}
                    {n.sponsored && n.label && <span className="sponsored-label pub-gap">{n.label}</span>}
                  </p>
                  <h2>{n.url ? <Link to={n.url}>{n.headline}</Link> : n.headline}</h2>
                  <p>{n.standfirst}</p>
                  {n.source_url && (
                    <p className="small">
                      Source:{" "}
                      <a href={n.source_url} target="_blank" rel="noreferrer">
                        {n.source_name}
                      </a>
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="pub-aside">
          <AdSlot slot="news_sidebar" />
        </div>
      </div>
    </>
  );
}

function Contribute() {
  return (
    <article className="article">
      <h1>Contribute to tax.ng</h1>
      <p className="lede">We publish clear, sourced writing on Nigerian, African and international tax by practitioners, academics and officials.</p>
      <h2>What we ask of you</h2>
      <ul>
        <li>Your credentials and affiliation, a short summary and the full text.</li>
        <li>Citations for every claim about the law, with links to primary sources where you can.</li>
        <li>The jurisdiction your piece covers.</li>
        <li>A warranty that you hold the rights to publish the work.</li>
        <li>Declarations of any conflict of interest, any sponsorship, and any use of AI tools.</li>
      </ul>
      <h2>How review works</h2>
      <p>
        An editor screens each submission, then a legal reviewer checks facts and law. We may ask you to revise and will tell you why.
        Approval is an editorial decision only: payment never buys approval or publication. Published pieces carry a type label
        (explanatory commentary, news, opinion or user submission) and any correction is shown on the page with its date.
      </p>
      <p>
        <a className="btn" href="/app/#/publishing">
          Start a submission
        </a>{" "}
        <Link to="/advertise" className="btn btn--ghost">
          Sponsorship and advertising
        </Link>
      </p>
    </article>
  );
}

function Advertise() {
  const { data, error } = useLoad(() => pub.policy(), []);
  if (!data) return <Loading error={error} />;
  const a = data.audience;
  return (
    <article className="article">
      <h1>Advertise and sponsor</h1>
      <p className="lede">Sponsored content and display advertising on tax.ng follow published rules. Terms version {data.terms_version}.</p>
      <Notice tone={a.open ? "info" : "warn"}>
        {a.open
          ? "Sponsored publishing and display advertising are open."
          : `Sponsored publishing and display advertising open once the newsletter reaches ${a.threshold.toLocaleString("en-NG")} subscribers. Current audience: ${a.subscribers.toLocaleString("en-NG")}.`}
      </Notice>
      <h2>Rate card</h2>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Placement</th>
              <th scope="col">Price</th>
            </tr>
          </thead>
          <tbody>
            {data.rate_card.map((r) => (
              <tr key={r.id}>
                <th scope="row">
                  {r.name}
                  <span className="step-note">{r.description}</span>
                </th>
                <td>{r.price}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2>Placement policy</h2>
      <ul>{data.placement_policy.map((p, i) => <li key={i}>{p}</li>)}</ul>
      <h2>Disclosure rules</h2>
      <ul>{data.disclosure_rules.map((p, i) => <li key={i}>{p}</li>)}</ul>
      <h2>Rejection and refunds</h2>
      <ul>{data.rejection_and_refund.map((p, i) => <li key={i}>{p}</li>)}</ul>
      <p>To discuss a sponsorship or campaign, contact the tax.ng partnerships team through the About page.</p>
    </article>
  );
}

function Archive() {
  const { data, error } = useLoad(() => pub.archive(), []);
  return (
    <>
      <h1>Newsletter archive</h1>
      <p className="lede">Past editions of the Nigerian Tax Brief and Global Tax Watch.</p>
      {!data ? (
        <Loading error={error} />
      ) : data.items.length === 0 ? (
        <p className="muted">No editions sent yet. <Link to="/newsletter">Subscribe</Link> to get the first one.</p>
      ) : (
        <ul className="list">
          {data.items.map((e) => (
            <li key={e.id}>
              <Link to={`/newsletter/archive/${e.id}`}>
                <strong>
                  {e.newsletter_name}: {e.title}
                </strong>
              </Link>
              <span>
                {day(e.sent_at)}
                {e.sponsored ? " · Includes a sponsored slot" : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function ArchivedEditionPage({ id }: { id: string }) {
  const { data, error } = useLoad(() => pub.archived(id), [id]);
  if (!data) return <Loading error={error} />;
  return (
    <article className="article">
      <p className="crumbs">
        <Link to="/newsletter/archive">Newsletter archive</Link>
      </p>
      <p className="eyebrow">{data.newsletter_name}</p>
      <h1>{data.title}</h1>
      <p className="muted small">Sent {day(data.sent_at)}</p>
      {data.intro && <p className="lede">{data.intro}</p>}
      {data.sponsor && (
        <div className="card pub-sponsor">
          <span className="sponsored-label">{data.sponsor.label}</span>
          <p className="small">
            This edition is supported by {data.sponsor.sponsor} ({data.sponsor.funding_relationship}).
          </p>
        </div>
      )}
      <ul className="news">
        {data.items.map((i) => (
          <li key={i.id} className="card">
            <span className="pub-labels">
              {i.sponsored && i.label && <span className="sponsored-label">{i.label}</span>}
              <span className="badge badge--kind">{i.badge}</span>
              {i.sample && <span className="badge badge--unverified">Sample item</span>}
            </span>
            <h2>{i.url ? <a href={i.url}>{i.title}</a> : i.title}</h2>
            <p>{i.summary}</p>
          </li>
        ))}
      </ul>
      <AdSlot slot="newsletter" />
    </article>
  );
}

function Unsubscribe({ email, token }: { email: string; token: string }) {
  const [state, setState] = useState<"idle" | "done" | "error">("idle");
  const go = () =>
    pub.unsubscribe(email, token).then(
      () => setState("done"),
      () => setState("error"),
    );
  return (
    <article className="article" aria-live="polite">
      <h1>Unsubscribe</h1>
      {state === "done" ? (
        <Notice>{email} will no longer receive tax.ng newsletters.</Notice>
      ) : state === "error" ? (
        <Notice tone="error">That link is not valid or the address is already unsubscribed.</Notice>
      ) : (
        <>
          <p>Stop all tax.ng newsletters to {email}?</p>
          <button type="button" className="btn" onClick={() => void go()}>
            Unsubscribe
          </button>
        </>
      )}
    </article>
  );
}

function ComplaintTracker({ id, token }: { id: string; token: string }) {
  const { data, error } = useLoad(() => pub.complaintStatus(id, token), [id, token]);
  return (
    <article className="article">
      <h1>Your report {id}</h1>
      {!data ? (
        <Loading error={error} />
      ) : (
        <>
          <p>
            Status: <span className={`pill pill--${data.status === "resolved" ? "ok" : data.status === "rejected" ? "bad" : "warn"}`}>{data.status}</span>
          </p>
          {data.resolution && <p>Outcome: {data.resolution}</p>}
          <p className="muted small">Last updated {day(data.updated_at)}</p>
        </>
      )}
    </article>
  );
}

export const siteModule: SiteModule = {
  id: "publishing",
  routes: [
    ["/insights", () => <Insights />],
    ["/insights/:slug", (p) => <ArticleView slug={p.slug} />],
    ["/news/:section", (p) => <NewsSection section={p.section} />],
    ["/contribute", () => <Contribute />],
    ["/advertise", () => <Advertise />],
    ["/newsletter/archive", () => <Archive />],
    ["/newsletter/archive/:id", (p) => <ArchivedEditionPage id={p.id} />],
    ["/newsletter/unsubscribe/:email/:token", (p) => <Unsubscribe email={p.email} token={p.token} />],
    ["/complaints/:id/:token", (p) => <ComplaintTracker id={p.id} token={p.token} />],
  ],
};
