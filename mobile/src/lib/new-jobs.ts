/** "New jobs" badge: good jobs found since this device last opened Jobs. Checked every minute while the app is open.
 * (Phone notifications with the app closed come later, with the APK.) */
import { useQuery } from '@tanstack/react-query';
import { create } from 'zustand';

import { api } from './api';
import { storage } from './storage';

const KEY = 'leapvoy.jobsSeen';

export const useSeen = create<{ since: string | null }>(() => ({ since: null }));

export async function loadSeen() {
  const saved = await storage.get(KEY);
  if (saved) useSeen.setState({ since: saved });
  else await markJobsSeen(); // first run: start counting from now
}

export async function markJobsSeen() {
  const now = new Date().toISOString();
  useSeen.setState({ since: now });
  await storage.set(KEY, now);
}

export type NewJobs = { count: number; jobs: { id: number; company: string; role: string; fit_score: number }[] };

export function useNewJobs() {
  const since = useSeen((s) => s.since);
  return useQuery({
    queryKey: ['jobs', 'new', since],
    queryFn: async () => (await api.get<NewJobs>('/jobs/new', { params: { since } })).data,
    enabled: !!since,
    refetchInterval: 60_000,
  });
}
