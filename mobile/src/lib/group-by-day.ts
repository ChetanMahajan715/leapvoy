/** Chat history grouping like Claude's sidebar: Today · Yesterday · Sep 26 · Dec 31, 2025 (device's local time). */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function dayLabel(d: Date, now: Date = new Date()): string {
  const days = Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  const base = `${MONTHS[d.getMonth()]} ${d.getDate()}`;
  return d.getFullYear() === now.getFullYear() ? base : `${base}, ${d.getFullYear()}`;
}

export function groupByDay<T extends { updated_at: string }>(
  items: T[],
  now: Date = new Date(),
): { label: string; items: T[] }[] {
  const sorted = [...items].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
  const groups: { label: string; items: T[] }[] = [];
  for (const item of sorted) {
    const label = dayLabel(new Date(item.updated_at), now);
    const last = groups.at(-1);
    if (last?.label === label) last.items.push(item);
    else groups.push({ label, items: [item] });
  }
  return groups;
}
