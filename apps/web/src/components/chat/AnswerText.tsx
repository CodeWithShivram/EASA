import type { Source } from "@/lib/api/conversations";

const MARKER = /\[(S\d+)\]/g;

/**
 * An answer with its citation markers ("[S1]") turned into buttons that show
 * the source. Markers without a matching source stay plain text. The text is
 * rendered as text (never as HTML).
 */
export function AnswerText({
  text,
  sources,
  onCite,
}: {
  text: string;
  sources: readonly Source[];
  onCite: (source: Source) => void;
}) {
  const byLabel = new Map(sources.map((s) => [s.label, s]));
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(MARKER)) {
    const source = byLabel.get(match[1] ?? "");
    if (!source) continue;
    parts.push(text.slice(last, match.index));
    parts.push(
      <button
        key={`${match.index}-${source.label}`}
        type="button"
        onClick={() => onCite(source)}
        aria-label={`Show source ${source.label}: ${source.citation.filename}`}
        className="mx-0.5 rounded bg-blue-100 px-1 align-baseline text-xs font-semibold text-blue-800 hover:bg-blue-200 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-blue-600 dark:bg-blue-950 dark:text-blue-200"
      >
        {source.label}
      </button>,
    );
    last = (match.index ?? 0) + match[0].length;
  }
  parts.push(text.slice(last));
  return <p className="whitespace-pre-wrap">{parts}</p>;
}
