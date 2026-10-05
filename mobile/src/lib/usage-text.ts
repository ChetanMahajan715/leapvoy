/** Model picker wording for each AI model's free usage (pure, tested with node --test). */

export type ModelInfo = {
  id: string;
  label: string;
  maker: string;
  note: string;
  used_today: number;
  /** Groq publishes its free daily limit; Mistral and Gemini don't → null. */
  left_pct: number | null;
  state: 'ok' | 'low' | 'busy' | 'empty';
  back_at: string | null;
};

function clock(iso: string): string {
  const d = new Date(iso);
  const h = d.getHours();
  return `${h % 12 || 12}:${String(d.getMinutes()).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
}

export function usageText(m: ModelInfo): string {
  if (m.state === 'empty') return m.back_at ? `No usage left, back at ${clock(m.back_at)}` : 'No usage left';
  if (m.state === 'busy') return 'Busy for a moment. Try again shortly';
  if (m.state === 'low' && m.left_pct === 0) return 'Almost used up. Some usage is coming back';
  if (m.left_pct !== null) return m.state === 'low' ? `Only ${m.left_pct}% left today` : `${m.left_pct}% left today`;
  if (!m.used_today) return 'Not used today';
  return `${(m.used_today / 1000).toFixed(1)}k tokens used today`;
}
