/** A list of server data (Jobs / Scheduled / Sent): pull to refresh, saved-copy note when offline, empty text. */
import type { UseQueryResult } from '@tanstack/react-query';
import type { ReactElement, ReactNode } from 'react';
import { RefreshCw } from 'lucide-react-native';
import { FlatList, Platform, RefreshControl, StyleSheet, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Loading, Pill, Small, when } from '@/components/chat-cards';
import { haptic } from '@/lib/haptics';
import { spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

export function ServerList<T>({
  query,
  items,
  keyOf,
  renderItem,
  header,
  empty,
  footer,
}: {
  query: UseQueryResult<unknown>;
  items: T[];
  keyOf: (item: T) => string | number;
  renderItem: (item: T) => ReactElement;
  header?: ReactNode;
  empty: string;
  /** Stays at the bottom, outside the scroll (e.g. "Write & schedule 3 emails"). */
  footer?: ReactNode;
}) {
  const { colors } = useColors();
  const offline = query.isError && query.data !== undefined;
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={['bottom', 'left', 'right']}>
      <FlatList
        data={items}
        keyExtractor={(item) => String(keyOf(item))}
        renderItem={({ item, index }) => (
          // cards arrive one after another (capped, so a long list never waits)
          <Animated.View entering={FadeInDown.duration(240).delay(Math.min(index, 6) * 45)}>{renderItem(item)}</Animated.View>
        )}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl
            refreshing={query.isRefetching}
            onRefresh={() => query.refetch().then(haptic.refreshed)}
            tintColor={colors.primary}
            colors={[colors.primary]}
            progressBackgroundColor={colors.surface}
          />
        }
        ListHeaderComponent={
          <View style={{ gap: spacing.md }}>
            {header}
            {Platform.OS === 'web' && query.data !== undefined ? ( // no pull-to-refresh in a browser
              <View style={{ alignSelf: 'flex-end' }}>
                <Pill label={query.isRefetching ? 'Refreshing…' : 'Refresh'} icon={RefreshCw} busy={query.isRefetching} onPress={() => query.refetch()} />
              </View>
            ) : null}
            {offline ? (
              <View style={[styles.note, { backgroundColor: colors.primarySoft }]}>
                <Small color={colors.text}>
                  Can’t reach Leapvoy. Showing the copy saved {when(new Date(query.dataUpdatedAt).toISOString())}.
                </Small>
              </View>
            ) : null}
          </View>
        }
        ListEmptyComponent={
          query.data === undefined ? <Loading error={query.error} retry={() => query.refetch()} count={3} /> : <Small>{empty}</Small>
        }
      />
      {footer}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  list: { width: '100%', maxWidth: 760, alignSelf: 'center', padding: spacing.lg, gap: spacing.md },
  note: { borderRadius: 8, padding: spacing.md },
});
