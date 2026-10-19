// Small shared UI pieces: form fields, badges, notices, async loading.
import { useEffect, useId, useState, type ReactNode } from "react";
import { ApiError } from "../api";
import { REVIEW_LABEL } from "../format";

export function MoneyField(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
  error?: string;
  required?: boolean;
}) {
  const id = useId();
  const pretty = (v: string) => {
    const digits = v.replace(/[^\d.]/g, "");
    if (!digits) return "";
    const [whole, frac] = digits.split(".");
    return Number(whole).toLocaleString("en-NG") + (frac !== undefined ? `.${frac.slice(0, 2)}` : "");
  };
  return (
    <div className={`field${props.error ? " field--error" : ""}`}>
      <label htmlFor={id}>
        {props.label}
        {props.required && <span aria-hidden="true"> *</span>}
      </label>
      <div className="money">
        <span aria-hidden="true">₦</span>
        <input
          id={id}
          inputMode="decimal"
          autoComplete="off"
          value={props.value}
          required={props.required}
          aria-invalid={Boolean(props.error)}
          aria-describedby={props.hint || props.error ? `${id}-hint` : undefined}
          onChange={(e) => props.onChange(e.target.value)}
          onBlur={(e) => props.onChange(pretty(e.target.value))}
        />
      </div>
      {(props.error || props.hint) && (
        <p id={`${id}-hint`} className="field__hint">
          {props.error ?? props.hint}
        </p>
      )}
    </div>
  );
}

export function SelectField<T extends string>(props: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  error?: string;
}) {
  const id = useId();
  return (
    <div className={`field${props.error ? " field--error" : ""}`}>
      <label htmlFor={id}>{props.label}</label>
      <select id={id} value={props.value} onChange={(e) => props.onChange(e.target.value as T)}>
        {props.options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {props.error && <p className="field__hint">{props.error}</p>}
    </div>
  );
}

export function CheckField(props: { label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string }) {
  const id = useId();
  return (
    <div className="check">
      <input id={id} type="checkbox" checked={props.checked} onChange={(e) => props.onChange(e.target.checked)} />
      <label htmlFor={id}>
        {props.label}
        {props.hint && <span className="check__hint">{props.hint}</span>}
      </label>
    </div>
  );
}

export function ReviewBadge({ status }: { status: string }) {
  return <span className={`badge badge--${status}`}>{REVIEW_LABEL[status] ?? status}</span>;
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "error"; children: ReactNode }) {
  return (
    <div className={`notice notice--${tone}`} role={tone === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "Something went wrong. Please try again.";
}

/** Loads data once per dependency change. Keeps pages free of fetch boilerplate. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]): { data?: T; error?: string } {
  const [state, setState] = useState<{ data?: T; error?: string }>({});
  useEffect(() => {
    let live = true;
    setState({});
    load().then(
      (data) => live && setState({ data }),
      (err: unknown) => live && setState({ error: errorText(err) }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

export function Loading({ error }: { error?: string }) {
  return error ? <Notice tone="error">{error}</Notice> : <p className="muted">Loading…</p>;
}
