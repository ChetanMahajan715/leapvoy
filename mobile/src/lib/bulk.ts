/** One click for many jobs: write each missing email (from the template), then schedule it to all its HR addresses.
 * Jobs go one by one so the free AI limits hold; the server spaces sends 3–8 min apart, max 20/day per sender. */
import type { Job, Send } from '@/components/chat-cards';

import { api, errorMessage } from './api';

export type BulkResult = { job: Job; ok: boolean; note: string };
export type Progress = { index: number; total: number; job: Job; phase: 'writing' | 'scheduling' };

export async function writeAndSchedule(
  jobs: Job[],
  when: string,
  onProgress: (p: Progress) => void,
  model: string | null = null, // "Write emails with" picker (null = Auto)
): Promise<BulkResult[]> {
  const results: BulkResult[] = [];
  for (const [index, job] of jobs.entries()) {
    try {
      let draft = job.draft;
      if (!draft || draft.outdated) {
        onProgress({ index, total: jobs.length, job, phase: 'writing' });
        draft = (await api.post<Job>(`/jobs/${job.id}/draft`, { model }, { timeout: 180_000 })).data.draft;
      }
      if (!draft) throw new Error('No email could be written.');
      if (draft.status === 'needs_review') {
        results.push({ job, ok: false, note: `Email needs review first: ${draft.issues.join('; ')}` });
        continue;
      }
      onProgress({ index, total: jobs.length, job, phase: 'scheduling' });
      const send = (await api.post<Send>(`/jobs/${job.id}/schedule`, { when, to: draft.to_emails })).data;
      results.push({ job, ok: true, note: send.send_at });
    } catch (e) {
      results.push({ job, ok: false, note: errorMessage(e) });
    }
  }
  return results;
}
