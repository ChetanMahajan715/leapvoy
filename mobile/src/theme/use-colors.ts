import { useColorScheme } from 'react-native';
import { create } from 'zustand';

import { storage } from '@/lib/storage';

import { dark, light, type Appearance } from './theme';

export type Colors = typeof light;
const KEY = 'leapvoy.appearance';

export const useAppearance = create<{ appearance: Appearance }>(() => ({ appearance: 'system' }));

export async function loadAppearance() {
  const saved = await storage.get(KEY);
  if (saved === 'light' || saved === 'dark' || saved === 'system') useAppearance.setState({ appearance: saved });
}

export async function setAppearance(appearance: Appearance) {
  useAppearance.setState({ appearance });
  await storage.set(KEY, appearance);
}

/** Current colors from the brand tokens: Light / Dark / System default. */
export function useColors(): { colors: Colors; scheme: 'light' | 'dark' } {
  const system = useColorScheme();
  const appearance = useAppearance((s) => s.appearance);
  const scheme = appearance === 'system' ? (system === 'dark' ? 'dark' : 'light') : appearance;
  return { colors: scheme === 'dark' ? dark : light, scheme };
}
