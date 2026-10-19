// Signed-in academy pages: my learning (courses, seats, CPD approval) and the lesson player.
import { useState, type FormEvent } from "react";
import { Figures } from "../../components/Figures";
import { Loading, Notice, errorText, useLoad } from "../../components/ui";
import { date } from "../../format";
import { Link } from "../../router";
import { PageHead } from "../../app/core";
import type { AppContext, AppModule } from "../types";
import { academyApi, type GradeResult, type Outline, type Player, type Quiz } from "./api";
import { CALC_PATH, CourseMeta, CpdStatus, PriceTag, TrainerCard } from "./shared";

const CPD_ROLES = ["editor", "legal_reviewer", "admin"];

// ------------------------------------------------------------ my learning
function SeatsPanel({ orgId, orgName }: { orgId: string; orgName: string }) {
  const [version, setVersion] = useState(0);
  const seats = useLoad(() => academyApi.seats(orgId), [orgId, version]);
  const courses = useLoad(() => academyApi.courses(), []);
  const [courseId, setCourseId] = useState("");
  const [count, setCount] = useState("5");
  const [pick, setPick] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ tone: "info" | "error"; text: string }>();

  const buy = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const pool = await academyApi.buySeats(orgId, courseId || courses.data?.items[0]?.id || "", Number(count));
      setMsg({ tone: "info", text: pool.status === "active" ? "Seats added." : "Seats reserved. Complete the sandbox checkout to activate them." });
      setVersion(version + 1);
    } catch (err) {
      setMsg({ tone: "error", text: errorText(err) });
    }
  };
  const assign = async (poolId: string) => {
    try {
      await academyApi.assignSeat(orgId, poolId, pick[poolId] ?? "");
      setMsg({ tone: "info", text: "Seat assigned. The member can start the course from My learning." });
      setVersion(version + 1);
    } catch (err) {
      setMsg({ tone: "error", text: errorText(err) });
    }
  };

  return (
    <section className="card">
      <h2>Team seats for {orgName}</h2>
      <p className="small">As owner you can buy seats on a course and assign them to members of this workspace.</p>
      <form className="academy-inline" onSubmit={buy}>
        <div className="field">
          <label htmlFor="seat-course">Course</label>
          <select id="seat-course" value={courseId} onChange={(e) => setCourseId(e.target.value)}>
            {courses.data?.items.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title} ({c.price.model === "free" ? "free" : "paid"})
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="seat-count">Seats</label>
          <input id="seat-count" inputMode="numeric" value={count} onChange={(e) => setCount(e.target.value.replace(/\D/g, ""))} />
        </div>
        <button className="btn" disabled={!count}>
          Add seats
        </button>
      </form>
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      {!seats.data ? (
        <Loading error={seats.error} />
      ) : seats.data.items.length === 0 ? (
        <p className="muted small">No seats yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Course</th>
                <th scope="col">Seats</th>
                <th scope="col">Status</th>
                <th scope="col">Assign</th>
              </tr>
            </thead>
            <tbody>
              {seats.data.items.map((p) => {
                const taken = new Set(p.assigned.map((a) => a.user_id));
                const free = seats.data!.members.filter((m) => !taken.has(m.id));
                return (
                  <tr key={p.id}>
                    <th scope="row">
                      {p.course_title}
                      <span className="step-note">{p.assigned.map((a) => a.name || a.email).join(", ") || "Nobody assigned yet"}</span>
                    </th>
                    <td className="num">
                      {p.seats_used} / {p.seats_total}
                    </td>
                    <td>
                      {p.status === "active" ? (
                        <span className="pill pill--ok">Active</span>
                      ) : (
                        <>
                          <span className="pill pill--warn">Awaiting payment</span>
                          {p.checkout?.url && (
                            <a className="small" href={p.checkout.url}>
                              {" "}
                              Checkout ({p.checkout.mode === "sandbox" ? "sandbox, no real payment" : p.checkout.mode})
                            </a>
                          )}
                        </>
                      )}
                    </td>
                    <td>
                      {p.status === "active" && p.seats_used < p.seats_total && free.length > 0 ? (
                        <div className="row-actions">
                          <label className="sr-only" htmlFor={`assign-${p.id}`}>
                            Member
                          </label>
                          <select id={`assign-${p.id}`} value={pick[p.id] ?? ""} onChange={(e) => setPick({ ...pick, [p.id]: e.target.value })}>
                            <option value="">Choose a member</option>
                            {free.map((m) => (
                              <option key={m.id} value={m.id}>
                                {m.name || m.email}
                              </option>
                            ))}
                          </select>
                          <button type="button" className="btn btn--small" disabled={!pick[p.id]} onClick={() => void assign(p.id)}>
                            Assign
                          </button>
                        </div>
                      ) : (
                        <span className="muted small">{p.status === "active" ? "No seats or members left" : "After payment"}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function CpdPanel() {
  const [version, setVersion] = useState(0);
  const [courseId, setCourseId] = useState("");
  const [body, setBody] = useState("CITN");
  const [reference, setReference] = useState("");
  const [msg, setMsg] = useState<{ tone: "info" | "error"; text: string }>();
  const list = useLoad(() => academyApi.courses(), [version]).data;
  const target = courseId || list?.items[0]?.id || "";

  const approve = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await academyApi.approveCpd(target, body, reference);
      setReference("");
      setMsg({ tone: "info", text: "CPD approval recorded. The course now shows the accreditation." });
      setVersion(version + 1);
    } catch (err) {
      setMsg({ tone: "error", text: errorText(err) });
    }
  };
  const withdraw = async (id: string) => {
    try {
      await academyApi.withdrawCpd(id);
      setVersion(version + 1);
    } catch (err) {
      setMsg({ tone: "error", text: errorText(err) });
    }
  };

  return (
    <section className="card">
      <h2>CPD accreditation (staff)</h2>
      <p className="small">
        A course shows a CPD claim only after you record the accrediting body and its approval reference. Record it only when you hold the
        body's written approval.
      </p>
      {list && (
        <ul className="list list--tight">
          {list.items.map((c) => (
            <li key={c.id}>
              <strong>{c.title}</strong>
              <span>
                <CpdStatus cpd={c.cpd} />{" "}
                {c.cpd && (
                  <button type="button" className="btn btn--small btn--ghost" onClick={() => void withdraw(c.id)}>
                    Withdraw
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={approve}>
        <div className="field">
          <label htmlFor="cpd-course">Course</label>
          <select id="cpd-course" value={target} onChange={(e) => setCourseId(e.target.value)}>
            {list?.items.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="cpd-body">Accrediting body</label>
          <select id="cpd-body" value={body} onChange={(e) => setBody(e.target.value)}>
            <option value="CITN">CITN (Chartered Institute of Taxation of Nigeria)</option>
            <option value="ICAN">ICAN (Institute of Chartered Accountants of Nigeria)</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="cpd-ref">Approval reference</label>
          <input id="cpd-ref" value={reference} onChange={(e) => setReference(e.target.value)} />
        </div>
        <button className="btn" disabled={!reference.trim()}>
          Record approval
        </button>
      </form>
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
    </section>
  );
}

function MyLearning({ ctx }: { ctx: AppContext }) {
  const mine = useLoad(() => academyApi.mine(), []);
  const courses = useLoad(() => academyApi.courses(), []);
  const enrolled = new Set(mine.data?.items.map((e) => e.course_id));
  return (
    <>
      <PageHead title="My learning" intro="Your courses, progress and certificates." />
      {!mine.data ? (
        <Loading error={mine.error} />
      ) : mine.data.items.length === 0 ? (
        <p className="muted">You have not joined a course yet.</p>
      ) : (
        <ul className="list">
          {mine.data.items.map((e) => (
            <li key={e.id}>
              <Link to={`/learning/${e.course_id}`}>
                <strong>{e.course_title}</strong>
              </Link>
              <span>
                {e.status === "pending_payment" ? (
                  <span className="pill pill--warn">Awaiting payment</span>
                ) : (
                  <>
                    <progress className="academy-progress" max={e.lesson_count} value={e.lessons_done} aria-label="Lessons completed" /> {e.lessons_done} of{" "}
                    {e.lesson_count} lessons
                  </>
                )}{" "}
                {e.certified && <span className="pill pill--ok">Certificate issued</span>}
                {e.source === "seat" && <span className="pill pill--muted">Team seat</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      <h2>Courses</h2>
      {!courses.data ? (
        <Loading error={courses.error} />
      ) : (
        <div className="cards cards--app">
          {courses.data.items.map((c) => (
            <Link key={c.id} to={`/learning/${c.id}`} className="card card--link">
              <h3>{c.title}</h3>
              <p className="small">{c.summary}</p>
              <p className="academy-meta">
                <PriceTag price={c.price} />
                <CpdStatus cpd={c.cpd} />
                {enrolled.has(c.id) && <span className="pill pill--ok">Enrolled</span>}
              </p>
            </Link>
          ))}
        </div>
      )}
      <div className="grid-2">
        {ctx.org && ctx.org.role === "owner" && <SeatsPanel orgId={ctx.org.id} orgName={ctx.org.name} />}
        {CPD_ROLES.includes(ctx.me.staff_role) && <CpdPanel />}
      </div>
      {!ctx.org && ctx.me.organisations.some((o) => o.role === "owner") && (
        <p className="muted small">To buy seats for your team, choose a workspace you own in the switcher above.</p>
      )}
    </>
  );
}

// ------------------------------------------------------------------ player
function QuizForm({ quiz, enrolmentId, onDone }: { quiz: Quiz; enrolmentId: string; onDone: () => void }) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<GradeResult>();
  const [error, setError] = useState<string>();
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      setResult(await academyApi.attempt(enrolmentId, quiz.id, answers));
      onDone();
    } catch (err) {
      setError(errorText(err));
    }
  };
  const verdict = result ? new Map(result.results.map((r) => [r.id, r])) : null;
  return (
    <form onSubmit={submit} className="academy-quiz">
      {quiz.questions.map((q, i) => {
        const r = verdict?.get(q.id);
        return (
          <fieldset key={q.id} className={r ? (r.correct ? "academy-q academy-q--ok" : "academy-q academy-q--bad") : "academy-q"}>
            <legend>
              {i + 1}. {q.prompt}
            </legend>
            {q.options.map((o) => (
              <div key={o.id} className="check">
                <input
                  type="radio"
                  id={`${quiz.id}-${q.id}-${o.id}`}
                  name={`${quiz.id}-${q.id}`}
                  checked={answers[q.id] === o.id}
                  disabled={Boolean(result)}
                  onChange={() => setAnswers({ ...answers, [q.id]: o.id })}
                />
                <label htmlFor={`${quiz.id}-${q.id}-${o.id}`}>
                  {o.text}
                  {r && r.answer === o.id && <span className="check__hint">Correct answer</span>}
                </label>
              </div>
            ))}
            {r && <p className="small">{r.explanation}</p>}
          </fieldset>
        );
      })}
      <div aria-live="polite">
        {error && <Notice tone="error">{error}</Notice>}
        {result && (
          <Notice tone={result.passed ? "info" : "warn"}>
            {result.correct} of {result.total} correct. {result.passed ? "Passed." : `Not yet passed; the pass mark is ${result.pass_mark_percent}%.`}
          </Notice>
        )}
      </div>
      {result ? (
        <button type="button" className="btn btn--ghost" onClick={() => { setResult(undefined); setAnswers({}); }}>
          Try again
        </button>
      ) : (
        <button className="btn" disabled={Object.keys(answers).length < quiz.questions.length}>
          Submit answers
        </button>
      )}
    </form>
  );
}

type View = { kind: "lesson"; id: string } | { kind: "quiz"; id: string } | { kind: "assessment" } | { kind: "case" } | { kind: "certificate" };

function CertificatePanel({ player, onDone, defaultName }: { player: Player; onDone: () => void; defaultName: string }) {
  const [name, setName] = useState(defaultName);
  const [error, setError] = useState<string>();
  const cert = player.certificate;
  if (cert) {
    return (
      <div className="card academy-cert" aria-live="polite">
        <span className="pill pill--ok">Certificate issued</span>
        <h2>{cert.holder_name}</h2>
        <p>
          completed <strong>{player.course.title}</strong> on {date(cert.issued_at.slice(0, 10))}.
        </p>
        <p className="small">
          <CpdStatus cpd={cert.cpd} />
        </p>
        <p>
          Verification code: <code>{cert.code}</code>
        </p>
        <p>
          <a href={`/#/academy/certificates/${encodeURIComponent(cert.code)}`}>Public verification page</a>
        </p>
      </div>
    );
  }
  const lessons = player.modules.flatMap((m) => m.lessons);
  const left = lessons.filter((l) => !l.completed).length;
  const passed = player.results[player.assessment.id]?.passed;
  const issue = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      await academyApi.certificate(player.enrolment.id, name);
      onDone();
    } catch (err) {
      setError(errorText(err));
    }
  };
  return (
    <form className="card" onSubmit={issue}>
      <h2>Certificate</h2>
      <ul className="list list--tight">
        <li>
          <strong>Lessons</strong>
          <span>{left === 0 ? "All complete" : `${left} left`}</span>
        </li>
        <li>
          <strong>Final assessment</strong>
          <span>{passed ? "Passed" : "Not passed yet"}</span>
        </li>
      </ul>
      <div className="field">
        <label htmlFor="cert-name">Name to print on the certificate</label>
        <input id="cert-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      <button className="btn" disabled={left > 0 || !passed || name.trim().length < 2}>
        Issue my certificate
      </button>
    </form>
  );
}

function PlayerView({ player, reload, me }: { player: Player; reload: () => void; me: AppContext["me"] }) {
  const first = player.modules[0]?.lessons[0];
  const [view, setView] = useState<View>(first ? { kind: "lesson", id: first.id } : { kind: "assessment" });
  const [error, setError] = useState<string>();
  const lessons = player.modules.flatMap((m) => m.lessons);
  const done = lessons.filter((l) => l.completed).length;
  const current = view.kind === "lesson" ? lessons.find((l) => l.id === view.id) : undefined;
  const quiz = view.kind === "quiz" ? player.modules.find((m) => m.quiz?.id === view.id)?.quiz : undefined;
  const nextLesson = current ? lessons[lessons.indexOf(current) + 1] : undefined;
  const cs = player.case_study;

  const complete = async (id: string) => {
    setError(undefined);
    try {
      await academyApi.complete(player.enrolment.id, id);
      reload();
      if (nextLesson) setView({ kind: "lesson", id: nextLesson.id });
    } catch (err) {
      setError(errorText(err));
    }
  };
  const isOn = (v: View) => JSON.stringify(v) === JSON.stringify(view);
  const navButton = (v: View, label: string, mark?: string) => (
    <button type="button" className={`academy-nav__item${isOn(v) ? " academy-nav__item--on" : ""}`} aria-current={isOn(v) ? "step" : undefined} onClick={() => setView(v)}>
      {mark && <span aria-hidden="true">{mark} </span>}
      {label}
    </button>
  );

  return (
    <div className="academy-player">
      <nav className="academy-nav" aria-label="Course contents">
        <p className="small">
          <progress className="academy-progress" max={lessons.length} value={done} aria-label="Lessons completed" /> {done} of {lessons.length} lessons
        </p>
        {player.modules.map((m) => (
          <div key={m.id}>
            <p className="eyebrow">{m.title}</p>
            {m.lessons.map((l) => navButton({ kind: "lesson", id: l.id }, l.title, l.completed ? "✓" : "○"))}
            {m.quiz && navButton({ kind: "quiz", id: m.quiz.id }, "Module quiz", player.results[m.quiz.id]?.passed ? "✓" : "?")}
          </div>
        ))}
        <p className="eyebrow">Finish</p>
        {cs && navButton({ kind: "case" }, `Case study: ${cs.title}`)}
        {navButton({ kind: "assessment" }, "Final assessment", player.results[player.assessment.id]?.passed ? "✓" : "?")}
        {navButton({ kind: "certificate" }, "Certificate", player.certificate ? "✓" : undefined)}
      </nav>
      <div className="academy-stage">
        {error && <Notice tone="error">{error}</Notice>}
        {current && (
          <article className="article">
            <h2>{current.title}</h2>
            <div className="article__grid">
              <div>
                {current.body.map((p, i) => (
                  <p key={i}>{p}</p>
                ))}
                {current.provisions.length > 0 && (
                  <>
                    <h3>Provisions</h3>
                    <ul className="cites">
                      {current.provisions.map((p) => (
                        <li key={p.id}>
                          <a href={`/#/laws/${p.id}`}>{p.title}</a>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                <p>
                  {current.completed ? (
                    <span className="pill pill--ok">Completed</span>
                  ) : (
                    <button type="button" className="btn" onClick={() => void complete(current.id)}>
                      Mark as complete
                    </button>
                  )}{" "}
                  {nextLesson && (
                    <button type="button" className="btn btn--ghost" onClick={() => setView({ kind: "lesson", id: nextLesson.id })}>
                      Next lesson
                    </button>
                  )}
                </p>
              </div>
              <aside>
                <Figures cards={current.figures} />
              </aside>
            </div>
          </article>
        )}
        {quiz && (
          <>
            <h2>Module quiz</h2>
            <p className="small">Answers are checked on the server when you submit. Pass mark {quiz.pass_mark_percent}%.</p>
            <QuizForm key={quiz.id} quiz={quiz} enrolmentId={player.enrolment.id} onDone={reload} />
          </>
        )}
        {view.kind === "assessment" && (
          <>
            <h2>Final assessment</h2>
            <p className="small">
              {player.assessment.questions.length} questions. Pass mark {player.assessment.pass_mark_percent}%. You can retake it.
            </p>
            <QuizForm key="assessment" quiz={player.assessment} enrolmentId={player.enrolment.id} onDone={reload} />
          </>
        )}
        {view.kind === "case" && cs && (
          <article className="article">
            <h2>Case study: {cs.title}</h2>
            {cs.scenario.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
            <h3>Your tasks</h3>
            <ol>
              {cs.tasks.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ol>
            {cs.calculator && CALC_PATH[cs.calculator] && (
              <p>
                <a className="btn btn--ghost" href={`/#${CALC_PATH[cs.calculator]}`}>
                  Open the calculator
                </a>
              </p>
            )}
            <details>
              <summary>Discussion</summary>
              {cs.discussion.map((p, i) => (
                <p key={i}>{p}</p>
              ))}
            </details>
          </article>
        )}
        {view.kind === "certificate" && <CertificatePanel player={player} onDone={reload} defaultName={me.name} />}
      </div>
    </div>
  );
}

function EnrolPanel({ outline, onDone }: { outline: Outline; onDone: () => void }) {
  const [cohort, setCohort] = useState("");
  const [error, setError] = useState<string>();
  const enrol = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      await academyApi.enrol(outline.id, cohort || undefined);
      onDone();
    } catch (err) {
      setError(errorText(err));
    }
  };
  const blocked = outline.price.model === "paid" && !outline.payments_available;
  return (
    <div className="grid-2">
      <form className="card" onSubmit={enrol}>
        <h2>Join this course</h2>
        <p className="academy-meta">
          <PriceTag price={outline.price} />
          <CpdStatus cpd={outline.cpd} />
        </p>
        {outline.price.model === "paid" && <p className="small">{outline.price.note}</p>}
        {outline.cohorts.length > 0 && (
          <div className="field">
            <label htmlFor="enrol-cohort">Cohort</label>
            <select id="enrol-cohort" value={cohort} onChange={(e) => setCohort(e.target.value)}>
              <option value="">Self-paced, no cohort</option>
              {outline.cohorts.map((c) => (
                <option key={c.id} value={c.id} disabled={c.places_left === 0}>
                  {c.label}
                  {c.starts_on ? `, starts ${date(c.starts_on)}` : ""}
                  {c.places_left !== null ? ` (${c.places_left} places left)` : ""}
                </option>
              ))}
            </select>
          </div>
        )}
        {blocked && <Notice tone="warn">Payments are unavailable at the moment, so this course cannot be joined yet.</Notice>}
        {error && <Notice tone="error">{error}</Notice>}
        <button className="btn" disabled={blocked}>
          {outline.price.model === "free" ? "Enrol free" : "Continue to checkout"}
        </button>
      </form>
      <TrainerCard trainer={outline.trainer} />
    </div>
  );
}

function CoursePlayer({ ctx }: { ctx: AppContext }) {
  const courseId = ctx.params.courseId;
  const [version, setVersion] = useState(0);
  const reload = () => setVersion((v) => v + 1);
  const outline = useLoad(() => academyApi.course(courseId), [courseId, version]);
  const enrolment = outline.data?.my_enrolment;
  const active = enrolment?.status === "active" ? enrolment.id : null;
  const player = useLoad(() => (active ? academyApi.player(active) : Promise.resolve(null)), [active, version]);

  if (!outline.data) return <Loading error={outline.error} />;
  const o = outline.data;
  return (
    <>
      <p className="crumbs">
        <Link to="/learning">My learning</Link>
      </p>
      <PageHead title={o.title} intro={o.summary} />
      <CourseMeta review={o.review_status} level={o.level} hours={o.duration_hours} />
      {o.review_note && <Notice tone="warn">{o.review_note}</Notice>}
      {!enrolment && <EnrolPanel outline={o} onDone={reload} />}
      {enrolment?.status === "pending_payment" && (
        <div className="card">
          <h2>Awaiting payment</h2>
          <p>Your place is reserved. It activates as soon as the payment is confirmed.</p>
          {enrolment.checkout?.url && (
            <p>
              <a className="btn" href={enrolment.checkout.url}>
                Go to checkout
              </a>{" "}
              {enrolment.checkout.mode === "sandbox" && <span className="pill pill--warn">Sandbox checkout. No real payment is taken.</span>}
            </p>
          )}
          <button type="button" className="btn btn--ghost" onClick={reload}>
            Check again
          </button>
        </div>
      )}
      {active && (player.data ? <PlayerView player={player.data} reload={reload} me={ctx.me} /> : <Loading error={player.error} />)}
    </>
  );
}

function DashboardCard() {
  const mine = useLoad(() => academyApi.mine(), []);
  const active = mine.data?.items.filter((e) => e.status === "active") ?? [];
  const next = active.find((e) => !e.certified);
  return (
    <Link key="academy" to={next ? `/learning/${next.course_id}` : "/learning"} className="card card--link">
      <h2>My learning</h2>
      <p>
        {!mine.data
          ? "Courses on the 2025 reform."
          : active.length === 0
            ? "Start a free course on PAYE under the new Act."
            : next
              ? `Continue ${next.course_title}: ${next.lessons_done} of ${next.lesson_count} lessons done.`
              : `${active.length} course${active.length === 1 ? "" : "s"} complete.`}
      </p>
    </Link>
  );
}

export const appModule: AppModule = {
  id: "academy",
  routes: [
    ["/learning", (ctx) => <MyLearning ctx={ctx} />],
    ["/learning/:courseId", (ctx) => <CoursePlayer ctx={ctx} />],
  ],
  dashboard: () => <DashboardCard key="academy" />,
};
