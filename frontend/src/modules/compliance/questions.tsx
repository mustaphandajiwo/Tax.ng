// One health-check question. Every input is labelled; radio groups use fieldsets.
// "Not sure" and "Does not apply" are separate answers, distinct from leaving a question open.
import { useEffect, useId, useState } from "react";
import type { Question } from "./api";

const STATUS_LABEL: Record<Question["status"], string> = {
  answered: "Answered",
  unknown: "Not sure",
  not_applicable: "Does not apply",
  unanswered: "Not answered yet",
};

function Radios(props: { name: string; legend: string; value: string; options: [string, string][]; disabled?: boolean; onChange: (v: string) => void }) {
  return (
    <fieldset className="hc-radios">
      <legend>{props.legend}</legend>
      {props.options.map(([value, label]) => (
        <label key={value} className="hc-radio">
          <input type="radio" name={props.name} value={value} checked={props.value === value} disabled={props.disabled} onChange={() => props.onChange(value)} />
          {label}
        </label>
      ))}
    </fieldset>
  );
}

function TextAnswer(props: { q: Question; numeric: "money" | "count"; disabled?: boolean; onSave: (v: unknown) => void }) {
  const id = useId();
  const initial = props.q.answer === null || props.q.answer === "unknown" ? "" : String(props.q.answer);
  const [draft, setDraft] = useState(initial);
  useEffect(() => setDraft(initial), [initial]);
  const commit = () => {
    const clean = draft.replace(/[^\d.]/g, "");
    if (clean !== initial) props.onSave(clean === "" ? null : props.numeric === "count" ? Number(clean) : clean);
  };
  return (
    <div className="field">
      <label htmlFor={id}>{props.q.text}</label>
      <div className={props.numeric === "money" ? "money" : undefined}>
        {props.numeric === "money" && <span aria-hidden="true">₦</span>}
        <input
          id={id}
          inputMode={props.numeric === "money" ? "decimal" : "numeric"}
          value={draft}
          disabled={props.disabled}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && commit()}
        />
      </div>
      {props.q.allow_unknown && (
        <label className="hc-radio">
          <input type="checkbox" checked={props.q.answer === "unknown"} disabled={props.disabled} onChange={(e) => props.onSave(e.target.checked ? "unknown" : null)} /> Not sure
        </label>
      )}
    </div>
  );
}

export function QuestionField(props: { q: Question; flagged?: boolean; disabled?: boolean; onSave: (v: unknown) => void }) {
  const { q } = props;
  const name = useId();
  const current = q.answer === null ? "" : String(q.answer);
  let control;
  if (q.type === "money" || q.type === "count") {
    control = <TextAnswer q={q} numeric={q.type} disabled={props.disabled} onSave={props.onSave} />;
  } else if (q.type === "choice" || q.type === "state") {
    control = (
      <div className="field">
        <label htmlFor={name}>{q.text}</label>
        <select id={name} value={current} disabled={props.disabled} onChange={(e) => props.onSave(e.target.value || null)}>
          <option value="">Choose…</option>
          {(q.options ?? []).map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
    );
  } else if (q.type === "bool") {
    const options: [string, string][] = [["true", "Yes"], ["false", "No"]];
    if (q.allow_unknown) options.push(["unknown", "Not sure"]);
    control = (
      <Radios
        name={name}
        legend={q.text}
        value={current}
        options={options}
        disabled={props.disabled}
        onChange={(v) => props.onSave(v === "true" ? true : v === "false" ? false : v)}
      />
    );
  } else {
    const options: [string, string][] = [["yes", "Yes"], ["no", "No"], ["unknown", "Not sure"]];
    if (q.allow_na) options.push(["not_applicable", "Does not apply"]);
    control = <Radios name={name} legend={q.text} value={current} options={options} disabled={props.disabled} onChange={props.onSave} />;
  }
  return (
    <div className={`hc-question${props.flagged ? " hc-question--flagged" : ""}`} data-status={q.status}>
      {control}
      <span className={`pill pill--${q.status === "answered" ? "ok" : q.status === "unanswered" ? "warn" : "muted"}`}>{STATUS_LABEL[q.status]}</span>
    </div>
  );
}
