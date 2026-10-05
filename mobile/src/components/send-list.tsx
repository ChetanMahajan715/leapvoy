/** Scheduled / Sent: a search box (company, role, subject, HR address; searches all history on the server) and the
 * emails grouped by India day ("Today · 3 emails", "Tomorrow", "Fri 2 Oct"). */
import { useQuery } from '@tanstack/react-query';
import { Search, X } from 'lucide-react-native';
import { useEffect, useState, type ReactElement } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import type { Send } from '@/components/chat-cards';
import { ServerList } from '@/components/server-list';
import { api } from '@/lib/api';
import { dayTitle, groupByIstDay } from '@/lib/days';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

type Row = { kind: 'day'; day: string; count: number } | { kind: 'send'; send: Send };

export function SendList({
  status,
  keep,
  at,
  order,
  renderSend,
  empty,
}: {
  /** server filter, e.g. 'scheduled' (none = every status) */
  status?: string;
  /** which of the returned emails belong on this screen */
  keep: (s: Send) => boolean;
  /** the time an email is filed under */
  at: (s: Send) => string;
  order: 'newest' | 'oldest';
  renderSend: (s: Send) => ReactElement;
  empty: string;
}) {
  const { colors } = useColors();
  const [text, setText] = useState('');
  const [search, setSearch] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setSearch(text.trim()), 300);
    return () => clearTimeout(t);
  }, [text]);
  const q = useQuery({
    queryKey: ['sends', status ?? 'all', search],
    queryFn: async () =>
      (await api.get<Send[]>('/sends', { params: { ...(status ? { status } : {}), ...(search ? { q: search } : {}) } })).data,
  });
  const rows: Row[] = groupByIstDay((q.data ?? []).filter(keep), at, order).flatMap((g) => [
    { kind: 'day' as const, day: g.day, count: g.items.length },
    ...g.items.map((send) => ({ kind: 'send' as const, send })),
  ]);

  return (
    <ServerList
      query={q}
      items={rows}
      keyOf={(r) => (r.kind === 'day' ? `day-${r.day}` : r.send.id)}
      renderItem={(r) =>
        r.kind === 'day' ? (
          <View style={styles.dayRow}>
            <Text style={[styles.day, { color: colors.text }]}>{dayTitle(r.day)}</Text>
            <Text style={[styles.count, { color: colors.textMuted }]}>{`${r.count} email${r.count === 1 ? '' : 's'}`}</Text>
            <View style={[styles.rule, { backgroundColor: colors.border }]} />
          </View>
        ) : (
          renderSend(r.send)
        )
      }
      empty={search ? `No emails match “${search}”.` : empty}
      header={
        <View style={[styles.search, { backgroundColor: colors.glass, borderColor: colors.border }]}>
          <Search size={16} color={colors.textMuted} strokeWidth={2} />
          <TextInput
            accessibilityLabel="Search emails"
            value={text}
            onChangeText={setText}
            placeholder="Search company, role, subject or HR email"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="none"
            autoCorrect={false}
            style={[styles.input, { color: colors.text }]}
          />
          {text ? (
            <Pressable accessibilityRole="button" accessibilityLabel="Clear search" onPress={() => setText('')} hitSlop={8}>
              <X size={16} color={colors.textMuted} strokeWidth={2} />
            </Pressable>
          ) : null}
        </View>
      }
    />
  );
}

const styles = StyleSheet.create({
  search: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, borderWidth: 1, borderRadius: radius.pill,
    paddingHorizontal: spacing.md, minHeight: 44 },
  // outlineWidth 0: no browser focus box inside the round field on the web (no effect on phones)
  input: { flex: 1, fontFamily: fonts.body, fontSize: 15, paddingVertical: 10, outlineWidth: 0 } as object,
  dayRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: spacing.sm },
  day: { fontFamily: fonts.semibold, fontSize: 15 },
  count: { fontFamily: fonts.body, fontSize: 13 },
  rule: { flex: 1, height: 1 },
});
