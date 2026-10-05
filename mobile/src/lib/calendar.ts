/** Date picking for "send at": a month grid (India days, Mon-first) and typed times. Pure, tested with node --test. */
import { dateLabel } from './days.ts';

/** Weeks of the month: each day as YYYY-MM-DD, null for blanks before the 1st / after the last day. */
export function monthGrid(year: number, month: number): (string | null)[][] {
  const first = new Date(Date.UTC(year, month - 1, 1));
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const cells: (string | null)[] = Array((first.getUTCDay() + 6) % 7).fill(null); // Monday first
  for (let d = 1; d <= days; d++) cells.push(`${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`);
  while (cells.length % 7) cells.push(null);
  return Array.from({ length: cells.length / 7 }, (_, i) => cells.slice(i * 7, i * 7 + 7));
}

/** "14:30", "9", "2:05 pm", "12 am" → "HH:MM" (24 h), or null if it isn't a time. */
export function parseTime(text: string): string | null {
  const m = /^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*$/i.exec(text);
  if (!m) return null;
  let h = Number(m[1]);
  const min = Number(m[2] ?? 0);
  const ampm = m[3]?.toLowerCase();
  if (ampm) {
    if (h < 1 || h > 12) return null;
    h = (h % 12) + (ampm === 'pm' ? 12 : 0);
  }
  if (h > 23 || min > 59) return null;
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
}

/** Sent to the server, read as India time ("2026-10-03 11:00"). */
export function whenText(day: string, time: string): string {
  return `${day} ${time}`;
}

/** "Sat 3 Oct, 2:30 PM" */
export function timeLabel(day: string, time: string): string {
  const [h, m] = time.split(':').map(Number);
  const clock = `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
  return `${dateLabel(day)}, ${clock}`;
}
