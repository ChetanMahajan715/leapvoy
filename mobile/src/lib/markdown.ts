/** Tiny markdown for chat replies: paragraphs, - / 1. lists, **bold**, `code`, # headings (shown bold). */

export type Span = { text: string; bold?: true; code?: true };
export type Block = { kind: 'p'; spans: Span[] } | { kind: 'li'; mark: string; spans: Span[] };

const ITEM = /^\s*(?:[-*•]|(\d+[.)]))\s+(.*)$/;
const HEADING = /^#{1,6}\s+(.*)$/;
const INLINE = /\*\*([\s\S]+?)\*\*|`([^`\n]+)`/g;

function inline(text: string): Span[] {
  const spans: Span[] = [];
  let last = 0;
  for (const m of text.matchAll(INLINE)) {
    if (m.index > last) spans.push({ text: text.slice(last, m.index) });
    spans.push(m[1] !== undefined ? { text: m[1], bold: true } : { text: m[2], code: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) spans.push({ text: text.slice(last) });
  return spans;
}

export function parseMarkdown(md: string): Block[] {
  const blocks: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) blocks.push({ kind: 'p', spans: inline(para.join('\n')) });
    para = [];
  };
  for (const line of md.split('\n')) {
    const item = ITEM.exec(line);
    const heading = HEADING.exec(line);
    if (!line.trim()) flush();
    else if (item) {
      flush();
      blocks.push({ kind: 'li', mark: item[1] ?? '•', spans: inline(item[2]) });
    } else if (heading) {
      flush();
      blocks.push({ kind: 'p', spans: [{ text: heading[1], bold: true }] });
    } else para.push(line);
  }
  flush();
  return blocks;
}
