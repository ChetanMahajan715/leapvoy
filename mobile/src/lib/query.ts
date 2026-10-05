/** Server data cache, saved on the device so the app still shows the last jobs / emails when the server can't be reached. */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import { MutationCache, QueryClient } from '@tanstack/react-query';

import { haptic } from './haptics';

const WEEK = 7 * 24 * 60 * 60 * 1000;

export const queryClient = new QueryClient({
  mutationCache: new MutationCache({ onError: () => haptic.error() }), // any action that failed: one distinct buzz
  // gcTime ≥ maxAge, or saved entries are dropped before they're old (TanStack docs).
  defaultOptions: { queries: { retry: 1, staleTime: 30_000, gcTime: WEEK } },
});

export const persister = createAsyncStoragePersister({ storage: AsyncStorage, key: 'leapvoy.cache' });

/** maxAge: older copies are thrown away. buster: bump when the API shapes change. */
export const persistOptions = { persister, maxAge: WEEK, buster: 'v2' };

/** Sign-out (or session ended): forget this account's data on the device. */
export async function clearCache() {
  queryClient.clear();
  await persister.removeClient();
}
