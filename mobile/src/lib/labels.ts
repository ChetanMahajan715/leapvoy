/** What the user sees for a fit verdict (stored verdicts stay TOP PRIORITY / STRONG MATCH / …). */

const LABELS: Record<string, string> = {
  'TOP PRIORITY': 'Excellent fit',
  'STRONG MATCH': 'Strong fit',
  APPLY: 'Good fit',
  MAYBE: 'Possible fit',
  SKIP: 'Not a fit',
};

export function verdictLabel(verdict: string | null): string | null {
  return verdict ? (LABELS[verdict] ?? verdict) : null;
}

