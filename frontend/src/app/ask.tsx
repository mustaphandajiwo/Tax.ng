// Ask Tax AI with access to the user's own account (AI-04).
// Requires the user's explicit permission (Account settings). Uses the same
// citation and figure guards as the public Tax AI.
import { useState, type FormEvent } from "react";
import type { AskResult } from "../api";
import { Notice, ReviewBadge } from "../components/ui";
import { ApiError, http } from "../http";
import type { AppContext } from "../modules/types";
import { Link } from "../router";
import { PageHead } from "./core";

export function AskAccount({ ctx }: { ctx: AppContext }) {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AskResult & { account_used?: boolean }>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const ask = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      setResult(await http.post<AskResult & { account_used?: boolean }>("/api/ask/account", { question, org_id: ctx.orgId }));
    } catch (err) {
      setResult(undefined);
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead
        title="Ask Tax AI about my account"
        intro={ctx.org ? `Answers can use your own health check and ${ctx.org.name}'s calendar.` : "Answers can use your own health check. Choose a workspace above to include a business."}
      />
      {!ctx.me.ai_account_access ? (
        <Notice>
          Tax AI can't see your account yet. <Link to="/account">Allow access in Account settings</Link>. You can turn it off at any time, and every access is
          logged.
        </Notice>
      ) : (
        <form className="ask" onSubmit={ask}>
          <label htmlFor="acct-q" className="sr-only">
            Your question
          </label>
          <input id="acct-q" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="What do I need to file next?" maxLength={500} />
          <button className="btn" disabled={busy || question.trim().length < 3}>
            {busy ? "Thinking…" : "Ask"}
          </button>
        </form>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      {result && (
        <section className="card answer" aria-live="polite">
          {result.blocked && <Notice tone="warn">The answer failed a safety check and was withheld.</Notice>}
          {result.answer.split("\n\n").map((p, i) => (
            <p key={i}>{p}</p>
          ))}
          {result.citations.length > 0 && (
            <ul className="cites">
              {result.citations.map((c) => (
                <li key={c.id}>
                  <a href={`/#/laws/${c.id}`}>{c.title}</a> <ReviewBadge status={c.review_status} />
                </li>
              ))}
            </ul>
          )}
          <p className="muted small">
            {result.account_used ? "Used your account data (logged). " : ""}Citation check {result.guard.citations_ok ? "passed" : "failed"} · figure check{" "}
            {result.guard.figures_ok ? "passed" : "failed"}. {result.disclaimer}
          </p>
        </section>
      )}
    </>
  );
}
