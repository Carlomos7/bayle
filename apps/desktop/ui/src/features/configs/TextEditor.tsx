import type { ReactNode } from 'react';

/** The raw file, monospaced. */
export function TextEditor({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      spellCheck={false}
      aria-label={label}
      className="min-h-[420px] w-full resize-y rounded-lg border border-line2 bg-input p-3.5 font-mono text-ui leading-relaxed text-t1 outline-hidden focus:border-[var(--focus)]"
    />
  );
}

/** A plain read view for readmes: headings, lists and paragraphs. Nothing is executed or linked. */
export function MarkdownView({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) out.push(<ul key={`l${out.length}`} className="my-2 pl-5 text-body text-t2">{list.map((l, i) => <li key={i}>{l}</li>)}</ul>);
    list = [];
  };
  text.split('\n').forEach((line, i) => {
    const t = line.trim();
    if (/^[-*] /.test(t)) { list.push(t.slice(2)); return; }
    flush();
    if (!t) return;
    if (t.startsWith('## ')) out.push(<h3 key={i} className="mt-4 mb-1 font-serif text-lg font-semibold">{t.slice(3)}</h3>);
    else if (t.startsWith('# ')) out.push(<h2 key={i} className="mt-0 mb-2 font-serif text-heading font-semibold">{t.slice(2)}</h2>);
    else out.push(<p key={i} className="my-2 text-body text-t2">{t}</p>);
  });
  flush();
  return <div className="rounded-lg border border-line2 bg-panel px-5 py-4">{out}</div>;
}
