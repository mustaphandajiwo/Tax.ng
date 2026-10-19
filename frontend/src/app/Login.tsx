// Passwordless sign-in: email -> six-digit code -> session cookie.
import { useState, type FormEvent } from "react";
import type { Meta } from "../api";
import { Notice } from "../components/ui";
import { ApiError, http, qs } from "../http";

export function Login({ meta, onSignedIn }: { meta: Meta; onSignedIn: () => Promise<void> }) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"email" | "code">("email");
  const [demoCode, setDemoCode] = useState<string>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const fail = (err: unknown) => setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");

  const requestCode = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await http.post("/api/auth/request-code", { email });
      setStep("code");
      if (meta.demo_mode) {
        // Demo only: read the code from the sandbox outbox instead of email.
        const box = await http.get<{ items: { body: string }[] }>(`/api/dev/outbox${qs({ recipient: email.trim().toLowerCase() })}`);
        setDemoCode(box.items[0]?.body.match(/\b\d{6}\b/)?.[0]);
      }
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const verify = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await http.post("/api/auth/verify", { email, code });
      await onSignedIn();
    } catch (err) {
      fail(err);
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <a href="/" className="brand">
        tax<span>.ng</span>
      </a>
      <div className="card">
        <h1>Sign in</h1>
        <p className="muted">We'll email you a six-digit code. No password needed.</p>
        {error && <Notice tone="error">{error}</Notice>}
        {step === "email" ? (
          <form onSubmit={requestCode}>
            <div className="field">
              <label htmlFor="login-email">Email address</label>
              <input id="login-email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <button className="btn" disabled={busy || !email}>
              {busy ? "Sending…" : "Send code"}
            </button>
          </form>
        ) : (
          <form onSubmit={verify}>
            <p className="small">Code sent to {email}.</p>
            {demoCode && (
              <Notice>
                Demo mode: your code is <strong>{demoCode}</strong>. In production it arrives by email only.
              </Notice>
            )}
            <div className="field">
              <label htmlFor="login-code">Six-digit code</label>
              <input id="login-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required />
            </div>
            <button className="btn" disabled={busy || code.length !== 6}>
              {busy ? "Signing in…" : "Sign in"}
            </button>{" "}
            <button type="button" className="btn btn--ghost" onClick={() => setStep("email")}>
              Use a different email
            </button>
          </form>
        )}
      </div>
      <p className="muted small">
        © 2026 {meta.owner}. tax.ng is not a tax authority. <a href="/#/about">About</a>
      </p>
    </div>
  );
}
