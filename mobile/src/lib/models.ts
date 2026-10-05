/** Model picker data: every AI model with its free usage (refreshed every minute) + the user's picks on this device. */
import { useQuery } from '@tanstack/react-query';
import { create } from 'zustand';

import { api } from './api';
import { storage } from './storage';
import type { ModelInfo } from './usage-text';

export type Models = { models: ModelInfo[]; auto: string; auto_email: string };
export type PickKind = 'chat' | 'email';

const KEYS: Record<PickKind, string> = { chat: 'leapvoy.model.chat', email: 'leapvoy.model.email' };

/** null = Auto (best available, Leapvoy falls back by itself). */
export const usePicks = create<Record<PickKind, string | null>>(() => ({ chat: null, email: null }));

export async function loadPicks() {
  usePicks.setState({ chat: await storage.get(KEYS.chat), email: await storage.get(KEYS.email) });
}

export async function setPick(kind: PickKind, model: string | null) {
  usePicks.setState({ [kind]: model });
  if (model) await storage.set(KEYS[kind], model);
  else await storage.remove(KEYS[kind]);
}

export function useModels() {
  return useQuery({
    queryKey: ['models'],
    queryFn: async () => (await api.get<Models>('/models')).data,
    refetchInterval: 60_000,
  });
}
