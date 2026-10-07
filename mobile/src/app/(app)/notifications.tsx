/** Notifications: the inbox (same on web and phone; the phone also gets them as push notifications), tap opens the
 * right screen. The gear opens what to be notified about: each kind, the minimum fit, quiet hours. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { Settings2, X } from 'lucide-react-native';
import { useState } from 'react';
import { Pressable, StyleSheet, Switch, Text, View } from 'react-native';

import { IconButton } from '@/components/icon-button';
import { Sheet } from '@/components/sheet';
import { Button, Card, Choice, PageHeader, Screen, T } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { markRead, noteTarget, useInbox, type Note } from '@/lib/notifications';
import { fonts, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

type Prefs = { off: string[]; min_fit: string; quiet_from: number; quiet_to: number };

const KINDS: [string, string][] = [
  ['job', 'New jobs that fit you'],
  ['summary', 'Morning summary (after 9 AM)'],
  ['reply', 'Replies to your emails'],
  ['send_failed', "An email couldn't be sent"],
  ['limit', 'Daily sending limit reached'],
  ['ai_paused', 'Free AI used up for the day'],
];
const QUIET: { label: string; value: string }[] = [
  { label: 'Off', value: '0-0' },
  { label: '10 PM to 7 AM', value: '22-7' },
  { label: '11 PM to 8 AM', value: '23-8' },
  { label: '12 AM to 9 AM', value: '0-9' },
];

function when(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', {
    day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata',
  });
}

function Row({ note, onOpen, onDelete }: { note: Note; onOpen: () => void; onDelete: () => void }) {
  const { colors } = useColors();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onOpen}
      style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [
        styles.row,
        { borderColor: colors.border, backgroundColor: pressed || hovered ? colors.surfaceAlt : undefined },
      ]}>
      <View style={[styles.dot, { backgroundColor: note.read ? undefined : colors.primary }]} />
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={[styles.title, { color: colors.text }]}>{note.title}</Text>
        {note.body ? <Text style={[styles.body, { color: colors.textMuted }]}>{note.body}</Text> : null}
        <Text style={[styles.time, { color: colors.textMuted }]}>{when(note.created_at)}</Text>
      </View>
      <IconButton icon={X} label="Delete this notification" onPress={onDelete} />
    </Pressable>
  );
}

function Choices() {
  const { colors } = useColors();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['notify-prefs'], queryFn: async () => (await api.get<Prefs>('/notify-prefs')).data, staleTime: 0 });
  const save = useMutation({
    mutationFn: async (values: Partial<Prefs>) => (await api.put<Prefs>('/notify-prefs', values)).data,
    onSuccess: (p) => qc.setQueryData(['notify-prefs'], p),
  });
  const p = q.data;
  if (!p) return q.isError ? <T variant="error">{errorMessage(q.error)}</T> : <T variant="muted">Loading…</T>;
  return (
    <View style={{ gap: spacing.lg }}>
      <View style={{ gap: spacing.sm }}>
        {KINDS.map(([kind, label]) => (
          <View key={kind} style={styles.switchRow}>
            <Text style={[styles.body, { color: colors.text, flex: 1 }]}>{label}</Text>
            <Switch
              accessibilityLabel={label}
              value={!p.off.includes(kind)}
              onValueChange={(on) => save.mutate({ off: on ? p.off.filter((k) => k !== kind) : [...p.off, kind] })}
              trackColor={{ false: colors.border, true: colors.primary }}
              thumbColor={colors.surface}
              {...({ activeThumbColor: colors.surface } as object)} // web uses its own prop for the "on" knob
            />
          </View>
        ))}
        <T variant="muted">New sign-ins and Telegram sign-outs always come: they need you.</T>
      </View>
      <View style={{ gap: spacing.sm }}>
        <T variant="heading">Buzz for jobs from</T>
        <Choice
          value={p.min_fit}
          onChange={(min_fit) => save.mutate({ min_fit })}
          options={[
            { label: 'Excellent fit', value: 'TOP PRIORITY' },
            { label: 'Strong fit', value: 'STRONG MATCH' },
            { label: 'Good fit', value: 'APPLY' },
          ]}
        />
        <T variant="muted">Weaker fits still appear here, without a buzz.</T>
      </View>
      <View style={{ gap: spacing.sm }}>
        <T variant="heading">Quiet hours (India time)</T>
        <Choice
          value={`${p.quiet_from}-${p.quiet_to}`}
          onChange={(v) => {
            const [quiet_from, quiet_to] = v.split('-').map(Number);
            save.mutate({ quiet_from, quiet_to });
          }}
          options={QUIET}
        />
        <T variant="muted">During quiet hours notifications wait and come together in the morning.</T>
      </View>
      {save.error ? <T variant="error">{errorMessage(save.error)}</T> : null}
    </View>
  );
}

export default function Notifications() {
  const router = useRouter();
  const qc = useQueryClient();
  const inbox = useInbox();
  const [choices, setChoices] = useState(false);
  const readAll = useMutation({ mutationFn: () => markRead(), onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }) });
  const [clearing, setClearing] = useState(false);
  const remove = useMutation({ // ids undefined = Clear all
    mutationFn: (ids?: number[]) => api.post('/notifications/delete', { ids: ids ?? null }),
    onSuccess: () => {
      setClearing(false);
      return qc.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
  const open = async (n: Note) => {
    if (!n.read) markRead([n.id]).then(() => qc.invalidateQueries({ queryKey: ['notifications'] }));
    const target = noteTarget(n.data);
    if (target) router.navigate(target);
  };
  const items = inbox.data?.items ?? [];
  const unread = inbox.data?.unread ?? 0;
  return (
    <Screen>
      <PageHeader
        title="Notifications"
        subtitle={unread ? `${unread} unread` : 'All caught up'}
        right={<IconButton icon={Settings2} label="Choose notifications" onPress={() => setChoices(true)} />}
      />
      {unread ? <Button kind="secondary" title="Mark all as read" busy={readAll.isPending} onPress={() => readAll.mutate()} /> : null}
      {items.length ? (
        clearing ? (
          <Card>
            <T>Delete all {items.length} notifications?</T>
            <Button kind="danger" title="Delete all" busy={remove.isPending} onPress={() => remove.mutate(undefined)} />
            <Button kind="secondary" title="Keep them" onPress={() => setClearing(false)} />
          </Card>
        ) : (
          <Button kind="secondary" title="Clear all" onPress={() => setClearing(true)} />
        )
      ) : null}
      {remove.error ? <T variant="error">{errorMessage(remove.error)}</T> : null}
      <Card>
        {inbox.isError && !inbox.data ? <T variant="error">{errorMessage(inbox.error)}</T> : null}
        {inbox.data && !items.length ? (
          <T variant="muted">Nothing yet. New jobs that fit you, replies and sending problems show up here.</T>
        ) : null}
        {items.map((n) => (
          <Row key={n.id} note={n} onOpen={() => open(n)} onDelete={() => remove.mutate([n.id])} />
        ))}
      </Card>
      <Sheet open={choices} title="Notify me about" onClose={() => setChoices(false)}>
        <Choices />
      </Sheet>
    </Screen>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: spacing.md, paddingVertical: spacing.md, borderBottomWidth: StyleSheet.hairlineWidth },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 7 },
  title: { fontFamily: fonts.semibold, fontSize: 15 },
  body: { fontFamily: fonts.body, fontSize: 14, lineHeight: 20 },
  time: { fontFamily: fonts.body, fontSize: 12, marginTop: 2 },
  switchRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
});
