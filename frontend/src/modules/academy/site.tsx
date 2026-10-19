// Public academy pages: catalogue, course outline and certificate verification.
import { useState, type FormEvent } from "react";
import { Loading, Notice, useLoad } from "../../components/ui";
import { date } from "../../format";
import { Link } from "../../router";
import type { SiteModule } from "../types";
import { academyApi } from "./api";
import { CourseMeta, CpdStatus, PriceTag, TrainerCard } from "./shared";

function VerifyForm() {
  const [code, setCode] = useState("");
  const go = (e: FormEvent) => {
    e.preventDefault();
    if (code.trim()) window.location.hash = `#/academy/certificates/${encodeURIComponent(code.trim())}`;
  };
  return (
    <form className="card academy-verify" onSubmit={go}>
      <h2>Check a certificate</h2>
      <div className="field">
        <label htmlFor="cert-code">Certificate code</label>
        <input id="cert-code" value={code} placeholder="TNGC-..." autoComplete="off" onChange={(e) => setCode(e.target.value)} />
      </div>
      <button className="btn btn--ghost" disabled={!code.trim()}>
        Verify
      </button>
    </form>
  );
}

function Catalogue() {
  const { data, error } = useLoad(() => academyApi.courses(), []);
  return (
    <>
      <h1>tax.ng Academy</h1>
      <p className="lede">
        Short courses on the 2025 tax reform. Every figure in a lesson comes from the same rules engine as the calculators, and each course shows
        its review status.
      </p>
      {!data ? (
        <Loading error={error} />
      ) : (
        <div className="cards">
          {data.items.map((c) => (
            <Link key={c.id} to={`/academy/${c.id}`} className="card card--link">
              <h2>{c.title}</h2>
              <p>{c.summary}</p>
              <CourseMeta review={c.review_status} level={c.level} hours={c.duration_hours} />
              <p className="academy-meta">
                <PriceTag price={c.price} />
                <CpdStatus cpd={c.cpd} />
              </p>
            </Link>
          ))}
        </div>
      )}
      <VerifyForm />
    </>
  );
}

function CoursePage({ id }: { id: string }) {
  const { data, error } = useLoad(() => academyApi.course(id), [id]);
  if (!data) return <Loading error={error} />;
  const appLink = `/app/#/learning/${encodeURIComponent(data.id)}`;
  return (
    <article className="article">
      <p className="crumbs">
        <Link to="/academy">Academy</Link>
      </p>
      <h1>{data.title}</h1>
      <p className="lede">{data.summary}</p>
      <CourseMeta review={data.review_status} level={data.level} hours={data.duration_hours} />
      <p className="academy-meta">
        <PriceTag price={data.price} />
        <CpdStatus cpd={data.cpd} />
      </p>
      {data.review_note && <Notice tone="warn">{data.review_note}</Notice>}
      {data.price.model === "paid" && (
        <Notice>
          {data.payments_available
            ? `The price is to be set after validation. ${data.price.note ?? ""}`
            : "Payments are unavailable at the moment, so this course cannot be joined yet."}
        </Notice>
      )}
      <div className="article__grid">
        <div>
          <h2>Course outline</h2>
          <ol className="academy-outline">
            {data.modules.map((m) => (
              <li key={m.id}>
                <strong>{m.title}</strong>
                <ul>
                  {m.lessons.map((l) => (
                    <li key={l.id}>{l.title}</li>
                  ))}
                  {m.has_quiz && <li className="muted">Module quiz</li>}
                </ul>
              </li>
            ))}
          </ol>
          <p>
            Final assessment: {data.assessment.question_count} questions, pass mark {data.assessment.pass_mark_percent}%. A certificate
            with a public verification code is issued when you complete every lesson and pass.
          </p>
          {data.case_study && <p>Case study: {data.case_study.title}.</p>}
          {data.cohorts.length > 0 && (
            <>
              <h2>Cohorts</h2>
              <ul className="list list--tight">
                {data.cohorts.map((c) => (
                  <li key={c.id}>
                    <strong>{c.label}</strong>
                    <span>
                      {c.starts_on ? `Starts ${date(c.starts_on)}` : "Start any time"}
                      {c.places_left !== null && ` · ${c.places_left} places left`}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <p>
            <a className="btn" href={appLink}>
              {data.price.model === "free" ? "Enrol free" : "Enrol"}
            </a>{" "}
            <span className="muted small">You will be asked to sign in.</span>
          </p>
        </div>
        <aside>
          <TrainerCard trainer={data.trainer} />
        </aside>
      </div>
    </article>
  );
}

function VerifyPage({ code }: { code: string }) {
  const { data, error } = useLoad(() => academyApi.verify(code), [code]);
  return (
    <article className="article narrow" aria-live="polite">
      <p className="crumbs">
        <Link to="/academy">Academy</Link>
      </p>
      <h1>Certificate check</h1>
      {!data && !error && <Loading />}
      {error && (
        <Notice tone="error">
          No valid certificate matches <code>{code}</code>. Check the code was copied in full. A code that has been altered will not verify.
        </Notice>
      )}
      {data && (
        <div className="card academy-cert">
          <span className="pill pill--ok">Valid certificate</span>
          <h2>{data.holder_name}</h2>
          <p>
            completed <strong>{data.course_title}</strong> on {date(data.issued_at.slice(0, 10))}.
          </p>
          <p className="small">Issued by {data.issuer}.</p>
          <p className="small">
            <CpdStatus cpd={data.cpd} />
          </p>
          <p className="muted small">
            Code <code>{data.code}</code>
          </p>
        </div>
      )}
      <VerifyForm />
    </article>
  );
}

export const siteModule: SiteModule = {
  id: "academy",
  routes: [
    ["/academy", () => <Catalogue />],
    ["/academy/certificates/:code", (p) => <VerifyPage code={p.code} />],
    ["/academy/:courseId", (p) => <CoursePage id={p.courseId} />],
  ],
};
