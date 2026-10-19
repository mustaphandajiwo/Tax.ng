// WhatsApp simulator used on the public demo page and the staff channels page.
import { useState, type FormEvent } from "react";
import { Notice, errorText, useLoad } from "../../components/ui";
import { channelsApi } from "./api";

interface Bubble {
  from: "me" | "bot";
  text: string;
  note?: string;
}

const SAMPLES = ["PAYE 6m", "tax 450k monthly", "VAT 100000", "What is rent relief?", "help", "STOP"];

export function WhatsAppSimulator({ onSent }: { onSent?: () => void }) {
  const status = useLoad(() => channelsApi.status(), []);
  const [phone, setPhone] = useState("+234 800 000 0000");
  const [text, setText] = useState("");
  const [thread, setThread] = useState<Bubble[]>([]);
  const [busy, setBusy] = useState(false);

  const send = async (message: string) => {
    if (!message.trim()) return;
    setBusy(true);
    setThread((t) => [...t, { from: "me", text: message }]);
    setText("");
    try {
      const r = await channelsApi.demo(phone, message);
      setThread((t) => [...t, { from: "bot", text: r.reply ?? "(no reply)", note: `${r.kind ?? r.status} · ${r.mode}` }]);
      onSent?.();
    } catch (err) {
      setThread((t) => [...t, { from: "bot", text: errorText(err), note: "error" }]);
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void send(text);
  };

  if (status.data && !status.data.demo_available) {
    return <Notice tone="warn">The WhatsApp simulator is available only in the demo environment.</Notice>;
  }
  return (
    <div className="wa-sim">
      <div className="field">
        <label htmlFor="wa-phone">Send as phone number</label>
        <input id="wa-phone" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />
        <p className="field__hint">Only a one-way hash of the number is stored.</p>
      </div>
      <div className="wa-thread" aria-live="polite" aria-label="Conversation">
        {thread.length === 0 && <p className="muted small">Try one of the sample messages below.</p>}
        {thread.map((b, i) => (
          <div key={i} className={`wa-bubble wa-bubble--${b.from}`}>
            <span className="sr-only">{b.from === "me" ? "You:" : "tax.ng:"}</span>
            <pre>{b.text}</pre>
            {b.note && <span className="wa-bubble__note">{b.note}</span>}
          </div>
        ))}
      </div>
      <div className="chips" role="group" aria-label="Sample messages">
        {SAMPLES.map((s) => (
          <button key={s} type="button" className="chip" disabled={busy} onClick={() => void send(s)}>
            {s}
          </button>
        ))}
      </div>
      <form className="wa-compose" onSubmit={submit}>
        <label htmlFor="wa-text" className="sr-only">
          Message
        </label>
        <input id="wa-text" value={text} placeholder="Type a message" autoComplete="off" onChange={(e) => setText(e.target.value)} />
        <button className="btn" disabled={busy || !text.trim()}>
          Send
        </button>
      </form>
      {status.data && (
        <p className="muted small">
          Delivery: {status.data.adapter.mode === "sandbox" ? "sandbox. Replies go to the demo outbox, not to a phone." : status.data.adapter.mode}{" "}
          {status.data.retention_note}
        </p>
      )}
    </div>
  );
}
