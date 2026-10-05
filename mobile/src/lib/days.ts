/** Job days are India days (IST, like the backend), written YYYY-MM-DD. */

const IST_MS = 5.5 * 60 * 60 * 1000;
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function istToday(now: Date = new Date()): string {
  return new Date(now.getTime() + IST_MS).toISOString().slice(0, 10);
}

export function shiftDay(day: string, by: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + by);
  return d.toISOString().slice(0, 10);
}

/** "Tue 29 Sep" */
export function dateLabel(day: string): string {
  const d = new Date(`${day}T00:00:00Z`);
  return `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

export function dayTitle(day: string, today: string = istToday()): string {
  if (day === today) return 'Today';
  if (day === shiftDay(today, -1)) return 'Yesterday';
  if (day === shiftDay(today, 1)) return 'Tomorrow';
  return dateLabel(day);
}

/** The India day (YYYY-MM-DD) an instant falls on. */
export function istDay(iso: string): string {
  return new Date(Date.parse(iso) + IST_MS).toISOString().slice(0, 10);
}

/** Items grouped by India day: 'newest' first (Sent) or 'oldest' first (Scheduled), also inside each day. */
export function groupByIstDay<T>(items: T[], at: (item: T) => string, order: 'newest' | 'oldest'): { day: string; items: T[] }[] {
  const sign = order === 'newest' ? -1 : 1;
  const sorted = [...items].sort((a, b) => sign * (Date.parse(at(a)) - Date.parse(at(b))));
  const groups: { day: string; items: T[] }[] = [];
  for (const item of sorted) {
    const day = istDay(at(item));
    const last = groups.at(-1);
    if (last?.day === day) last.items.push(item);
    else groups.push({ day, items: [item] });
  }
  return groups;
}
