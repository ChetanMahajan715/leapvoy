/** A thin banner on top of every screen while the Leapvoy server can't be reached (turned off on Oracle, no internet,
 * or Tailscale off on this phone). The saved copy stays readable; it checks again by itself and refreshes everything
 * once the server is back. */
import { useQuery } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { CloudOff } from 'lucide-react-native';
import { useEffect, useRef } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api } from '@/lib/api';
import { queryClient } from '@/lib/query';
import { fonts, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

export type ServerState = 'ok' | 'off' | 'starting';

/** No answer at all = off / out of reach; an error answer (database not ready) = starting. */
export function serverState(error: unknown): ServerState {
  if (!error) return 'ok';
  return isAxiosError(error) && error.response ? 'starting' : 'off';
}

/** Checks the server every minute (every 15 s while it's down); one shared check for the whole app. */
export function useServer() {
  const q = useQuery({
    queryKey: ['health'],
    queryFn: async () => (await api.get('/health', { timeout: 8000 })).data,
    retry: false,
    staleTime: 0,
    refetchInterval: (query) => (query.state.error ? 15_000 : 60_000),
  });
  const state: ServerState = q.isError ? serverState(q.error) : 'ok';
  const wasDown = useRef(false);
  useEffect(() => {
    if (state !== 'ok') wasDown.current = true;
    else if (wasDown.current) {
      wasDown.current = false;
      queryClient.invalidateQueries({ predicate: (x) => x.queryKey[0] !== 'health' }); // back: fresh data everywhere
    }
  }, [state]);
  return { state, checking: q.isFetching, retry: () => q.refetch() };
}

/** Takes the top safe area itself (the header then drops its own status-bar space). */
export function ServerBanner({ server }: { server: ReturnType<typeof useServer> }) {
  const { colors } = useColors();
  const insets = useSafeAreaInsets();
  if (server.state === 'ok') return null;
  return (
    <View style={[styles.bar, { paddingTop: insets.top + spacing.sm, backgroundColor: colors.warningSoft, borderBottomColor: colors.border }]}>
      <CloudOff size={16} color={colors.warning} />
      <Text style={[styles.text, { color: colors.text }]}>
        {server.state === 'off'
          ? 'Leapvoy server is off or out of reach (or Tailscale is off). Showing your saved copy.'
          : 'Leapvoy server is starting. One moment.'}
      </Text>
      <Pressable accessibilityRole="button" onPress={server.retry} hitSlop={8}>
        <Text style={[styles.retry, { color: colors.primaryText }]}>{server.checking ? 'Checking…' : 'Retry'}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    paddingHorizontal: spacing.lg, paddingBottom: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth,
  },
  text: { flex: 1, fontFamily: fonts.semibold, fontSize: 13 },
  retry: { fontFamily: fonts.semibold, fontSize: 13 },
});
