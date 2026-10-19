// Signed-in pages for the compliance module: "My tax health" (HC-01 to HC-07).
// The questionnaire saves every answer as it is given, so a check can be left and resumed.
import { useEffect, useState } from "react";
import { PageHead } from "../../app/core";
import { Loading, Notice, errorText, useLoad } from "../../components/ui";
import { date } from "../../format";
import { Link } from "../../router";
import type { AppContext, AppModule } from "../types";
import { complianceApi as api, type CheckState, type Report } from "./api";
import { QuestionField } from "./questions";
import { ReportView } from "./report";

const thisYear = () => Math.max(2026, new Date().getFullYear());

function go(path: string) {
  window.location.hash = path;
}

// ------------------------------------------------------------------ overview
function Overview() {
  const checks = useLoad(() => api.checks(), []);
  const profile = useLoad(() => api.profile(), []);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const start = async (year: number) => {
    setBusy(true);
    setError(undefined);
    try {
      const state = await api.start(year);
      go(`/compliance/checks/${state.check.id}`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const forget = async () => {
    if (!window.confirm("Delete your saved tax profile? Completed reports are kept until you delete them.")) return;
    await api.deleteProfile();
    window.location.reload();
  };

  return (
    <>
      <PageHead
        title="My tax health"
        intro="Find out which taxes apply to you, what is due when and what evidence to keep. The result is self-reported and indicative, not an official assessment."
      >
        <button type="button" className="btn" disabled={busy} onClick={() => void start(thisYear())}>
          {busy ? "Starting…" : `Check ${thisYear()}`}
        </button>
      </PageHead>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="grid-2">
        <section className="card">
          <h2>My health checks</h2>
          {!checks.data ? (
            <Loading error={checks.error} />
          ) : checks.data.items.length === 0 ? (
            <p>You have not started a health check yet.</p>
          ) : (
            <ul className="list">
              {checks.data.items.map((c) => (
                <li key={c.id}>
                  <Link to={c.status === "completed" ? `/compliance/checks/${c.id}/report` : `/compliance/checks/${c.id}`}>
                    Tax year {c.year}
                  </Link>
                  <span>
                    {c.status === "completed" ? `Completed ${date(c.completed_at!.slice(0, 10))}` : `In progress, started ${date(c.created_at.slice(0, 10))}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="card">
          <h2>My tax profile</h2>
          <p className="small">
            We keep only the facts needed to work out your obligations, such as whether you employ staff. You can change them in any health
            check, or delete them.
          </p>
          {!profile.data ? (
            <Loading error={profile.error} />
          ) : (
            <>
              <p className="muted small">
                {Object.keys(profile.data.facts).length} facts saved
                {profile.data.updated_at ? `, last updated ${date(profile.data.updated_at.slice(0, 10))}` : ""}
              </p>
              {Object.keys(profile.data.facts).length > 0 && (
                <button type="button" className="btn btn--ghost btn--small" onClick={() => void forget()}>
                  Delete my profile
                </button>
              )}
            </>
          )}
        </section>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ questionnaire
interface Step {
  id: string;
  title: string;
  intro?: string;
  questionIds: string[];
}

function steps(state: CheckState): Step[] {
  const facts = state.questions.filter((q) => q.kind === "fact").map((q) => q.id);
  const out: Step[] = [{ id: "about", title: "About you", intro: "Only the questions that matter for your earlier answers are shown.", questionIds: facts }];
  for (const ob of state.obligations) {
    const ids = state.questions.filter((q) => q.kind === "evidence" && q.obligation === ob.id).map((q) => q.id);
    if (ids.length) out.push({ id: ob.id, title: ob.title, intro: ob.applies_because, questionIds: ids });
  }
  out.push({ id: "finish", title: "Review and finish", questionIds: [] });
  return out;
}

function CheckPage({ ctx }: { ctx: AppContext }) {
  const id = ctx.params.id;
  const [state, setState] = useState<CheckState>();
  const [loadError, setLoadError] = useState<string>();
  const [stepIndex, setStepIndex] = useState(0);
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let live = true;
    api.check(id).then(
      (s) => {
        if (!live) return;
        if (s.check.status === "completed") go(`/compliance/checks/${id}/report`);
        setState(s);
      },
      (err: unknown) => live && setLoadError(errorText(err)),
    );
    return () => {
      live = false;
    };
  }, [id]);

  if (!state) return <Loading error={loadError} />;
  const all = steps(state);
  const index = Math.min(stepIndex, all.length - 1);
  const step = all[index];
  const byId = Object.fromEntries(state.questions.map((q) => [q.id, q]));

  const save = async (qid: string, value: unknown) => {
    setSaving(true);
    setError(undefined);
    try {
      setState(await api.answer(id, { [qid]: value }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  };
  const finish = async () => {
    setError(undefined);
    try {
      await api.complete(id);
      go(`/compliance/checks/${id}/report`);
    } catch (err) {
      setError(errorText(err));
    }
  };
  const jumpTo = (qid: string) => {
    const target = all.findIndex((s) => s.questionIds.includes(qid));
    if (target >= 0) setStepIndex(target);
  };

  return (
    <>
      <PageHead title={`Tax health check ${state.check.year}`} intro="Answers save as you go. You can leave and come back later." />
      <ol className="hc-steps" aria-label="Steps">
        {all.map((s, i) => (
          <li key={s.id}>
            <button type="button" aria-current={i === index ? "step" : undefined} onClick={() => setStepIndex(i)}>
              {s.title}
            </button>
          </li>
        ))}
      </ol>
      {state.contradictions.length > 0 && (
        <Notice tone="warn">
          <strong>Please clarify:</strong>
          {state.contradictions.map((c) => (
            <span key={c.id} className="hc-clarify">
              {c.message}{" "}
              <button type="button" className="btn btn--ghost btn--small" onClick={() => jumpTo(c.questions[0])}>
                Go to the questions
              </button>
            </span>
          ))}
        </Notice>
      )}
      <section className="card hc-step" aria-live="polite">
        <h2>{step.title}</h2>
        {step.intro && <p className="small muted">{step.intro}</p>}
        {step.questionIds.map((qid) =>
          byId[qid] ? (
            <QuestionField
              key={qid}
              q={byId[qid]}
              flagged={state.contradictions.some((c) => c.questions.includes(qid))}
              disabled={saving}
              onSave={(v) => void save(qid, v)}
            />
          ) : null,
        )}
        {step.id === "finish" && (
          <>
            <p>
              {state.progress.answered} answered, {state.progress.unknown} not sure, {state.progress.not_applicable} do not apply and{" "}
              {state.progress.unanswered} still open. Open and "not sure" answers are reported as insufficient evidence, never as a failure.
            </p>
            {state.obligations.length > 0 && (
              <>
                <h3>Obligations that apply</h3>
                <ul className="list list--tight">
                  {state.obligations.map((o) => (
                    <li key={o.id}>
                      <strong>{o.title}</strong>
                      <span>{o.applies_because}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {state.undetermined.length > 0 && (
              <p className="small">
                We cannot yet tell whether these apply: {state.undetermined.map((u) => u.title).join("; ")}.
              </p>
            )}
            <button type="button" className="btn" disabled={state.contradictions.length > 0} onClick={() => void finish()}>
              See my results
            </button>
          </>
        )}
        {error && <Notice tone="error">{error}</Notice>}
        <div className="row-actions hc-nav">
          {index > 0 && (
            <button type="button" className="btn btn--ghost" onClick={() => setStepIndex(index - 1)}>
              Back
            </button>
          )}
          {index < all.length - 1 && (
            <button type="button" className="btn" onClick={() => setStepIndex(index + 1)}>
              Next
            </button>
          )}
        </div>
      </section>
    </>
  );
}

// ------------------------------------------------------------------ report
function ReportPage({ ctx }: { ctx: AppContext }) {
  const id = ctx.params.id;
  const report = useLoad<Report>(() => api.report(id), [id]);
  return (
    <div className="hc-print">
      <PageHead title="Tax health check report" intro="Findings by dimension, with what to do next.">
        <div className="row-actions hc-noprint">
          <button type="button" className="btn btn--ghost" onClick={() => window.print()}>
            Print
          </button>
          <a className="btn btn--ghost" href={api.downloadUrl(id)} download>
            Download (JSON)
          </a>
          <Link to="/advisory" className="btn">
            Talk to an adviser
          </Link>
        </div>
      </PageHead>
      {report.data ? <ReportView report={report.data} /> : <Loading error={report.error} />}
    </div>
  );
}

// ------------------------------------------------------------------ dashboard card
function DashboardCard() {
  const checks = useLoad(() => api.checks(), []);
  const latest = checks.data?.items[0];
  return (
    <Link key="compliance" to={latest ? (latest.status === "completed" ? `/compliance/checks/${latest.id}/report` : `/compliance/checks/${latest.id}`) : "/compliance"} className="card card--link">
      <h2>My tax health</h2>
      <p>
        {!latest
          ? "Find which taxes apply to you and what evidence you need."
          : latest.status === "completed"
            ? `Your ${latest.year} report is ready.`
            : `Continue your ${latest.year} health check.`}
      </p>
    </Link>
  );
}

export const appModule: AppModule = {
  id: "compliance",
  routes: [
    ["/compliance", () => <Overview />],
    ["/compliance/checks/:id", (ctx) => <CheckPage ctx={ctx} />],
    ["/compliance/checks/:id/report", (ctx) => <ReportPage ctx={ctx} />],
  ],
  dashboard: () => <DashboardCard key="compliance" />,
};
