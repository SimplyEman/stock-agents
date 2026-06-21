// Renders the thesis's "what would change my mind" falsifiers. Per-falsifier
// firing status is not tracked server-side yet, so all show green (not triggered);
// the diff timeline on the ticker page is where movement actually surfaces.

function splitFalsifiers(text: string): string[] {
  return text
    .split(/(?<=[.;])\s+(?=[A-Z(0-9])/)
    .map((s) => s.trim())
    .filter((s) => s.length > 8);
}

export function FalsifierList({ text }: { text: string }) {
  const items = splitFalsifiers(text || "");
  if (items.length === 0) return <p className="text-sm text-muted-foreground">None recorded.</p>;
  return (
    <ul className="flex flex-col gap-2">
      {items.map((f, i) => (
        <li key={i} className="flex items-start gap-2.5 text-sm">
          <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-emerald-400" title="not triggered" />
          <span>{f}</span>
        </li>
      ))}
    </ul>
  );
}
