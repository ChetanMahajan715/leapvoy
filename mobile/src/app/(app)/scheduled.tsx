import { useMutation } from '@tanstack/react-query';
import { Clock, Mail, X } from 'lucide-react-native';
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Pill, Small, useRefresh, when, type Send } from '@/components/chat-cards';
import { ScheduleSheet } from '@/components/schedule-sheet';
import { SendList } from '@/components/send-list';
import { api, errorMessage } from '@/lib/api';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

/** Emails waiting to go out, by day (soonest first), searchable: move them or cancel them (each asks first). */
export default function Scheduled() {
  return (
    <SendList
      status="scheduled"
      keep={() => true}
      at={(s) => s.send_at}
      order="oldest"
      renderSend={(s) => <ScheduledRow send={s} />}
      empty="Nothing scheduled. Approve an email from Jobs or chat and it appears here."
    />
  );
}

function ScheduledRow({ send }: { send: Send }) {
  const { colors } = useColors();
  const refresh = useRefresh();
  const [moving, setMoving] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const cancel = useMutation({ mutationFn: () => api.post(`/sends/${send.id}/cancel`), onSuccess: refresh });
  const move = useMutation({
    mutationFn: (w: string) => api.post(`/sends/${send.id}/reschedule`, { when: w }),
    onSuccess: refresh,
  });
  const error = cancel.error ?? move.error;

  return (
    <View style={[styles.card, { backgroundColor: colors.glass, borderColor: colors.glassBorder, boxShadow: colors.cardShadow }]}>
      <View style={styles.head}>
        <View style={{ flex: 1 }}>
          <Text style={[styles.title, { color: colors.text }]}>{send.role}</Text>
          <Small>{send.company}</Small>
        </View>
        {send.test_mode ? (
          <View style={[styles.badge, { borderColor: colors.warning }]}>
            <Text style={[styles.badgeText, { color: colors.warning }]}>TEST</Text>
          </View>
        ) : null}
      </View>
      <View style={[styles.banner, { backgroundColor: colors.primarySoft }]}>
        <Clock size={14} color={colors.primaryText} strokeWidth={2} />
        <Text style={[styles.small, { color: colors.text }]}>
          {when(send.send_at)}
          {send.test_mode ? ' · to your own inbox' : ''}
        </Text>
      </View>
      <View style={styles.meta}>
        <Mail size={14} color={colors.textMuted} strokeWidth={2} />
        <Text selectable style={[styles.small, { color: colors.text, flexShrink: 1 }]}>
          {(send.to_emails ?? [send.to_email]).join(', ')}
        </Text>
      </View>
      {send.subject ? <Small>{send.subject}</Small> : null}

      {cancelling ? (
        <View style={[styles.ask, { backgroundColor: colors.primarySoft }]}>
          <Small color={colors.text}>Cancel this email? It won’t be sent.</Small>
          <View style={styles.row}>
            <Pill label="Yes, cancel it" primary busy={cancel.isPending} onPress={() => cancel.mutate()} />
            <Pill label="Keep it" onPress={() => setCancelling(false)} />
          </View>
        </View>
      ) : (
        <View style={[styles.actions, { borderTopColor: colors.border }]}>
          <Pill label="Move" icon={Clock} busy={move.isPending} onPress={() => setMoving(true)} />
          <Pill label="Cancel email" icon={X} onPress={() => setCancelling(true)} />
        </View>
      )}
      {error ? <Small color={colors.error}>{errorMessage(error)}</Small> : null}
      <ScheduleSheet
        open={moving}
        title="Move it to…"
        quick={['hour', 'tomorrow']}
        onClose={() => setMoving(false)}
        onChoose={(c) => {
          setMoving(false);
          move.mutate(c.when);
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.sm },
  head: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  title: { fontFamily: fonts.semibold, fontSize: 15 },
  small: { fontFamily: fonts.body, fontSize: 13, lineHeight: 19 },
  badge: { borderWidth: 1, borderRadius: radius.pill, paddingVertical: 2, paddingHorizontal: spacing.sm },
  badgeText: { fontFamily: fonts.semibold, fontSize: 11 },
  banner: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, borderRadius: radius.sm, padding: spacing.sm },
  meta: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  ask: { borderRadius: radius.sm, padding: spacing.md, gap: spacing.sm },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.sm },
  actions: { borderTopWidth: 1, paddingTop: spacing.md, flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
});
