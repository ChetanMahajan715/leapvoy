import { StyleSheet, Text, View } from 'react-native';

import { Small, sendStatus, type Send } from '@/components/chat-cards';
import { SendList } from '@/components/send-list';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

const DONE = ['sent', 'failed', 'unknown', 'sending']; // not waiting, not cancelled

/** Emails that went out, by day (newest first), searchable; replies, and failures with the reason. */
export default function Sent() {
  return (
    <SendList
      keep={(s) => DONE.includes(s.status)}
      at={(s) => s.sent_at ?? s.send_at}
      order="newest"
      renderSend={(s) => <SentRow send={s} />}
      empty="No emails sent yet."
    />
  );
}

function SentRow({ send }: { send: Send }) {
  const { colors } = useColors();
  const color = send.replied_at ? colors.success : send.status === 'sent' ? colors.primaryText : colors.error;
  return (
    <View style={[styles.card, { backgroundColor: colors.glass, borderColor: colors.glassBorder, boxShadow: colors.cardShadow }]}>
      <Text style={[styles.title, { color: colors.text }]}>
        {send.company} · {send.role}
      </Text>
      <Small color={color}>
        {send.replied_at ? '✉ ' : ''}
        {sendStatus(send)}
      </Small>
      <Small>To {(send.to_emails ?? [send.to_email]).join(', ')}</Small>
      {send.subject ? <Small>{send.subject}</Small> : null}
      {send.status === 'unknown' ? (
        <Small color={colors.warning}>Stopped mid-send. Check your Gmail “Sent” folder; it is never retried by itself.</Small>
      ) : null}
      {send.reply_snippet ? (
        <View style={[styles.reply, { backgroundColor: colors.background, borderColor: colors.border }]}>
          <Small color={colors.text}>{send.reply_snippet}</Small>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.sm },
  title: { fontFamily: fonts.semibold, fontSize: 15 },
  reply: { borderWidth: 1, borderRadius: radius.sm, padding: spacing.md, marginTop: spacing.xs },
});
