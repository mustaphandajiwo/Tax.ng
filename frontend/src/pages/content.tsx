// Content pages: home, reform hub, guides, laws, news, about.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Figures } from "../components/Figures";
import { Loading, Notice, ReviewBadge, useLoad } from "../components/ui";
import { date } from "../format";
import { http } from "../http";
import { AdSlot } from "../modules/publishing/AdSlot";
import { Link } from "../router";

const CALC_PATH: Record<string, string> = {
  pit: "/calculators/pit",
  "pit-compare": "/calculators/pit-compare",
  cit: "/calculators/cit",
  vat: "/calculators/vat",
  wht: "/calculators/wht",
  cgt: "/calculators/cgt",
  "stamp-duty": "/calculators/stamp-duty",
};

export function Home() {
  const guides = useLoad(() => api.guides(), []);
  return (
    <>
      <section className="hero">
        <p className="eyebrow">The 2025 tax reform</p>
        <h1>The new tax law, explained and calculated.</h1>
        <p className="lede">
          From 1 January 2026, the Nigeria Tax Act 2025 sets new rules for PAYE, company tax and VAT. See what changed,
          work out what you owe, and check the source for every figure.
        </p>
        <div className="hero__actions">
          <Link to="/calculators/pit-compare" className="btn">
            Compare my PAYE
          </Link>
          <Link to="/reform" className="btn btn--ghost">
            What changed
          </Link>
        </div>
      </section>

      <section>
        <h2>Start with a calculator</h2>
        <div className="cards">
          <Link to="/calculators/pit" className="card card--link">
            <h3>PAYE</h3>
            <p>Monthly PAYE with rent relief.</p>
          </Link>
          <Link to="/calculators/cit" className="card card--link">
            <h3>Company tax</h3>
            <p>Are you a small company?</p>
          </Link>
          <Link to="/calculators/vat" className="card card--link">
            <h3>VAT</h3>
            <p>Add or extract VAT.</p>
          </Link>
          <Link to="/calculators/wht" className="card card--link">
            <h3>Withholding tax</h3>
            <p>What to deduct from a payment.</p>
          </Link>
        </div>
      </section>

      <section>
        <h2>Reform guides</h2>
        {guides.data ? <GuideList items={guides.data.items} /> : <Loading error={guides.error} />}
      </section>

      <AdSlot slot="home_sidebar" page="/" />

      <section className="card ask-cta">
        <h2>Ask Tax AI</h2>
        <p>Ask a question in plain words. Answers cite the law, and every figure comes from the rules engine.</p>
        <Link to="/ask" className="btn">
          Ask a question
        </Link>
      </section>
    </>
  );
}

function GuideList({ items }: { items: { id: string; title: string; summary: string }[] }) {
  return (
    <ul className="list">
      {items.map((g) => (
        <li key={g.id}>
          <Link to={`/reform/${g.id}`}>
            <strong>{g.title}</strong>
          </Link>
          <span>{g.summary}</span>
        </li>
      ))}
    </ul>
  );
}

export function Reform() {
  const guides = useLoad(() => api.guides(), []);
  return (
    <>
      <h1>New Tax Law 2026</h1>
      <p className="lede">
        One guide for each major change in the 2025 reform acts, linked to the provision and the calculator that applies it.
      </p>
      {guides.data ? <GuideList items={guides.data.items} /> : <Loading error={guides.error} />}
    </>
  );
}

interface GuideTranslation {
  lang: string;
  name: string;
  summary: string;
}

export function GuidePage({ id }: { id: string }) {
  const { data, error } = useLoad(() => api.guide(id), [id]);
  // CH-04: reviewed summary translations, served only once approved.
  const translations = useLoad(
    () =>
      http
        .get<{ items: GuideTranslation[] }>(`/api/channels/guide-translations/${encodeURIComponent(id)}`)
        .catch(() => ({ items: [] as GuideTranslation[] })),
    [id],
  );
  const [lang, setLang] = useState("en");
  const end = useRef<HTMLDivElement>(null);
  const [sent, setSent] = useState(false);

  // AN-02: "guide read to end" fires once when the last paragraph is visible.
  useEffect(() => {
    if (!data || sent || !end.current || !("IntersectionObserver" in window)) return;
    const obs = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        void api.event("guide_read_to_end", { guide: id });
        setSent(true);
        obs.disconnect();
      }
    });
    obs.observe(end.current);
    return () => obs.disconnect();
  }, [data, id, sent]);

  if (!data) return <Loading error={error} />;
  return (
    <article className="article">
      <p className="crumbs">
        <Link to="/reform">New Tax Law 2026</Link>
      </p>
      <h1>{data.title}</h1>
      {translations.data && translations.data.items.length > 0 && (
        <div className="tabs" role="tablist" aria-label="Summary language">
          <button type="button" role="tab" aria-selected={lang === "en"} onClick={() => setLang("en")}>
            English
          </button>
          {translations.data.items.map((t) => (
            <button key={t.lang} type="button" role="tab" aria-selected={lang === t.lang} onClick={() => setLang(t.lang)}>
              {t.name}
            </button>
          ))}
        </div>
      )}
      {(() => {
        const t = translations.data?.items.find((x) => x.lang === lang);
        return t ? (
          <>
            <p className="lede" lang={t.lang}>
              {t.summary}
            </p>
            <p className="muted small">Reviewed translation. If it differs from the English version, the English version applies.</p>
          </>
        ) : (
          <p className="lede">{data.summary}</p>
        );
      })()}
      <p className="muted small">Applies from {date(data.applies_from)}</p>
      <div className="article__grid">
        <div>
          {data.body.map((p, i) => (
            <p key={i}>{p}</p>
          ))}
          <div ref={end} />
          {data.calculator && CALC_PATH[data.calculator] && (
            <p>
              <Link to={CALC_PATH[data.calculator]} className="btn">
                Open the calculator
              </Link>
            </p>
          )}
          <h2>Provisions</h2>
          <ul className="cites">
            {data.provisions.map((p) => (
              <li key={p.id}>
                <Link to={`/laws/${p.id}`}>{p.title}</Link>
              </li>
            ))}
          </ul>
        </div>
        <aside>
          <Figures cards={data.figures} />
        </aside>
      </div>
    </article>
  );
}

const TAX_FILTERS = [
  { id: "", label: "All" },
  { id: "pit", label: "Personal income tax" },
  { id: "cit", label: "Company tax" },
  { id: "vat", label: "VAT" },
  { id: "wht", label: "Withholding tax" },
  { id: "general", label: "Administration" },
];

export function Laws() {
  const [tax, setTax] = useState("");
  const { data, error } = useLoad(() => api.laws(tax || undefined), [tax]);
  return (
    <>
      <h1>Laws and regulations</h1>
      <p className="lede">
        Plain-language summaries of the provisions behind every calculator. Section references are confirmed by a legal
        reviewer before release; until then they show as "to be confirmed".
      </p>
      <div className="filters" role="group" aria-label="Filter by tax">
        {TAX_FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            className={`chip${tax === f.id ? " chip--on" : ""}`}
            aria-pressed={tax === f.id}
            onClick={() => setTax(f.id)}
          >
            {f.label}
          </button>
        ))}
      </div>
      {!data ? (
        <Loading error={error} />
      ) : (
        <ul className="list">
          {data.items.map((p) => (
            <li key={p.id}>
              <Link to={`/laws/${p.id}`}>
                <strong>{p.title}</strong>
              </Link>
              <span>
                {p.instrument} · {p.in_force ? "In force" : p.effective_to ? `Applied until ${date(p.effective_to)}` : "Not yet in force"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function LawPage({ id }: { id: string }) {
  const { data, error } = useLoad(() => api.law(id), [id]);
  if (!data) return <Loading error={error} />;
  return (
    <article className="article">
      <p className="crumbs">
        <Link to="/laws">Laws and regulations</Link>
      </p>
      <h1>{data.title}</h1>
      <dl className="meta">
        <div>
          <dt>Instrument</dt>
          <dd>{data.instrument}</dd>
        </div>
        <div>
          <dt>Section</dt>
          <dd>{data.section}</dd>
        </div>
        <div>
          <dt>Effective</dt>
          <dd>
            From {date(data.effective_from)}
            {data.effective_to && ` until ${date(data.effective_to)}`}
          </dd>
        </div>
        <div>
          <dt>Review status</dt>
          <dd>
            <ReviewBadge status={data.review_status} />
          </dd>
        </div>
        <div>
          <dt>Provision ID</dt>
          <dd>
            <code>{data.id}</code>
          </dd>
        </div>
      </dl>
      <div className="article__grid">
        <div>
          <span className="badge badge--kind">Explanatory summary</span>
          <p>{data.summary}</p>
          <Notice>This is a summary, not the statute text. Rely on the official gazette for the exact wording.</Notice>
        </div>
        <aside>
          <Figures cards={data.parameters} />
        </aside>
      </div>
    </article>
  );
}

export function News() {
  const { data, error } = useLoad(() => api.news(), []);
  return (
    <>
      <h1>Tax news: Nigeria</h1>
      <p className="small">
        Also: <Link to="/news/africa">Africa</Link> · <Link to="/news/global">Global</Link>
      </p>
      {!data ? (
        <Loading error={error} />
      ) : (
        <ul className="news">
          {data.items.filter((n) => n.section === "nigeria").map((n) => (
            <li key={n.id} className="card">
              <p className="muted small">
                {date(n.date)}
                {n.sample && <span className="badge badge--unverified">Sample item</span>}
              </p>
              <h2>{n.headline}</h2>
              <p>{n.standfirst}</p>
              <p className="small">
                Source:{" "}
                <a href={n.source_url} target="_blank" rel="noreferrer">
                  {n.source_name}
                </a>
              </p>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function About() {
  return (
    <article className="article">
      <h1>About and ownership</h1>
      <p>
        tax.ng is owned and licensed by <strong>Astound Innovation Hub</strong>.
      </p>
      <h2>What tax.ng is, and is not</h2>
      <p>
        tax.ng explains Nigerian tax law and calculates liabilities from published rules. It is not a tax authority, does
        not act for one, and does not file returns in this version. Its content is general information, not tax advice.
      </p>
      <h2>How we keep figures accurate</h2>
      <p>
        Every rate, band and threshold lives once, in an effective-dated rules engine. Calculators, guides, the law library
        and Tax AI all read from it. Each rule records its source and a review status. A rule becomes "legally approved" only
        after two legal reviewers sign it off against the official text.
      </p>
      <h2>Editorial independence and conflicts</h2>
      <p>
        An editor has final authority over editorial content. Advertising and sponsorship have no approval role. Any director,
        employee or reviewer who holds public office takes no decision on content concerning a public body they deal with
        officially, and recusals are logged.
      </p>
      <h2>Corrections and complaints</h2>
      <p>Report an error and we will correct it and keep a visible record of the change.</p>
    </article>
  );
}

export function NotFound() {
  return (
    <>
      <h1>Page not found</h1>
      <p>
        <Link to="/">Go to the home page</Link>
      </p>
    </>
  );
}
