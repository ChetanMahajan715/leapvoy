/** The notification inbox (same on web and phone) and where tapping one goes. */
import { useQuery } from '@tanstack/react-query';
import type { Href } from 'expo-router';

import { api } from './api';

export type Note = {
  id: number;
  kind: string;
  title: string;
  body: string;
  data: { screen?: string; date?: string; [k: string]: unknown };
  read: boolean;
  created_at: string;
};
export type Inbox = { unread: number; items: Note[] };

export function useInbox() {
  return useQuery({
    queryKey: ['notifications'],
    queryFn: async () => (await api.get<Inbox>('/notifications')).data,
    staleTime: 0, // read / unread must come from the server, never an old saved copy
    refetchInterval: 60_000,
  });
}

const SCREENS = ['jobs', 'scheduled', 'sent', 'stats', 'senders', 'channels', 'settings'];

/** The screen a notification opens (Jobs opens on the job's day). */
export function noteTarget(data: Note['data']): Href | null {
  const screen = data.screen && SCREENS.includes(data.screen) ? data.screen : null;
  if (!screen) return null;
  return (screen === 'jobs' && data.date ? `/jobs?date=${data.date}` : `/${screen}`) as Href;
}

export function markRead(ids?: number[]) {
  return api.post('/notifications/read', { ids: ids ?? null });
}
