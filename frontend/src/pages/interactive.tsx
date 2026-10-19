// Ask Tax AI (AI-01 to AI-06) and newsletter signup (NEWS-03).
import { useState, type FormEvent } from "react";
import { api, ApiError, type AskResult, type Meta } from "../api";
import { Notice, ReviewBadge, errorText } from "../components/ui";
import { Link } from "../router";

const EXAMPLES = [
  "How much PAYE on a salary of ₦6m in 2026?",
  "I earn 450,000 per month. What is my tax?",
  "What is rent relief?",
  "Are small companies exempt from company tax?",
  "What happens if a supplier has no TIN?",
  "What was the consolidated relief allowance in 2025?",
];

function Paragraphs({ text }: { text: string }) {
  return (
    <>
      {text.split("\n\n").map((p, i) => (
        <p key={i}>{p}</p>
      ))}
    </>
  );
}

export function Ask() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AskResult>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const ask = async (q: string) => {
    setQuestion(q);
    setBusy(true);
    setError(undefined);
    try {
      setResult(await api.ask(q));
    } catch (err) {
      setResult(undefined);
      setError(err instanceof ApiError && err.fields.question ? err.fields.question : errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void ask(question);
  };

  return (
    <>
      <h1>Ask Tax AI</h1>
      <p className="lede">
        Answers come from the approved legal library. Figures come from the rules engine, never from the model. If the
        answer can't be grounded, Tax AI says so.
      </p>
      <form className="ask" onSubmit={onSubmit}>
        <label htmlFor="q" className="sr-only">
          Your question
        </label>
        <input id="q" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about PAYE, company tax, VAT or WHT" maxLength={500} />
        <button className="btn" disabled={busy || question.trim().length < 3}>
          {busy ? "Thinking…" : "Ask"}
        </button>
      </form>
      <div className="chips">
        {EXAMPLES.map((q) => (
          <button key={q} type="button" className="chip" onClick={() => void ask(q)}>
            {q}
          </button>
        ))}
      </div>

      {error && <Notice tone="error">{error}</Notice>}
      {result && (
        <section className="card answer" aria-live="polite">
          {result.blocked && <Notice tone="warn">The answer failed a safety check and was withheld.</Notice>}
          <Paragraphs text={result.answer} />
          {result.notices.map((n) => (
            <p key={n} className="muted small">
              {n}
            </p>
          ))}
          {result.citations.length > 0 && (
            <>
              <h3>Sources</h3>
              <ul className="cites">
                {result.citations.map((c) => (
                  <li key={c.id}>
                    <Link to={`/laws/${c.id}`}>{c.title}</Link> <span className="muted small">{c.instrument}</span>{" "}
                    <ReviewBadge status={c.review_status} />
                  </li>
                ))}
              </ul>
            </>
          )}
          {result.escalate && (
            <Notice>
              This needs a professional. Adviser booking opens in Phase 2; until then, consult a CITN-registered tax practitioner.
            </Notice>
          )}
          <details className="trace">
            <summary>How this answer was checked</summary>
            <ul>
              <li>Tax year applied: {result.tax_year}</li>
              <li>Confidence: {result.confidence}</li>
              <li>
                Rules engine calls: {result.tool_calls.length}
                {result.tool_calls.length > 0 && ` (${[...new Set(result.tool_calls.map((t) => t.name))].join(", ")})`}
              </li>
              <li>Citation check: {result.guard.citations_ok ? "passed" : "failed"}</li>
              <li>Figure check: {result.guard.figures_ok ? "passed" : "failed"}</li>
              {result.guard.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </details>
          <p className="muted small">{result.disclaimer}</p>
        </section>
      )}
    </>
  );
}

export function Newsletter({ meta }: { meta: Meta }) {
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setState("busy");
    setErrors({});
    try {
      await api.subscribe(email, consent);
      setState("done");
    } catch (err) {
      setErrors(err instanceof ApiError ? err.fields : { form: errorText(err) });
      setState("idle");
    }
  };

  return (
    <>
      <h1>Nigerian Tax Brief</h1>
      <p className="lede">A weekly email on what changed in Nigerian tax and what it means. Unsubscribe in one click.</p>
      {state === "done" ? (
        <Notice>Thank you. You're subscribed to the weekly Nigerian Tax Brief.</Notice>
      ) : (
        <form className="card narrow" onSubmit={onSubmit} noValidate>
          <div className={`field${errors.email ? " field--error" : ""}`}>
            <label htmlFor="email">Email address</label>
            <input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={Boolean(errors.email)} />
            {errors.email && <p className="field__hint">{errors.email}</p>}
          </div>
          <div className={`check${errors.consent ? " field--error" : ""}`}>
            <input id="consent" type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <label htmlFor="consent">{meta.consent_text}</label>
          </div>
          {errors.consent && <p className="field__hint error-text">{errors.consent}</p>}
          {errors.form && <Notice tone="error">{errors.form}</Notice>}
          <button className="btn" disabled={state === "busy"}>
            Subscribe
          </button>
        </form>
      )}
    </>
  );
}
