/** Settings → Password / Delete account: change password (current password + 2-step code, other devices signed out), delete account
 * (7 days to change your mind), and the "Keep my account" screen shown when signing in during those 7 days. */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Sheet } from '@/components/sheet';
import { Button, Card, Field, Screen, T } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { useAuth, useMe, type Me } from '@/lib/auth';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

function longDate(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata' });
}

function Tick({ on, label, onPress }: { on: boolean; label: string; onPress: () => void }) {
  const { colors } = useColors();
  return (
    <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: on }} onPress={onPress} style={styles.tickRow}>
      <View style={[styles.box, { borderColor: colors.primary, backgroundColor: on ? colors.primary : undefined }]}>
        {on ? <Text style={{ color: colors.onPrimary, fontFamily: fonts.semibold, fontSize: 12 }}>✓</Text> : null}
      </View>
      <Text style={[styles.tickText, { color: colors.text }]}>{label}</Text>
    </Pressable>
  );
}

export function ChangePassword() {
  const router = useRouter();
  const me = useMe().data;
  const signOut = useAuth((s) => s.signOut);
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const [code, setCode] = useState('');
  const [others, setOthers] = useState(true);
  const [done, setDone] = useState(false);
  const change = useMutation({
    mutationFn: () =>
      api.post('/auth/password/change', {
        current_password: current, new_password: next, code: code.trim() || null, sign_out_others: others,
      }),
    onSuccess: () => {
      setDone(true);
      setOpen(false);
      setCurrent('');
      setNext('');
      setAgain('');
      setCode('');
    },
  });
  // Forgot the current one: the email reset signs every device out anyway, so sign out here first.
  const forgot = async () => {
    setOpen(false);
    await signOut();
    router.replace({ pathname: '/forgot-password', params: me?.email ? { email: me.email } : {} });
  };
  const mismatch = again.length > 0 && next !== again;
  const short = next.length > 0 && next.length < 10;

  return (
    <Card>
      <T variant="heading">Password</T>
      <T variant="muted">Change it any time. You confirm with your current password{me?.totp_enabled ? ' and a code from your authenticator' : ''}.</T>
      {done ? <T variant="muted">✓ Password changed.{others ? ' Other devices were signed out.' : ''}</T> : null}
      <View style={styles.row}>
        <Button kind="secondary" title="Change password" onPress={() => { change.reset(); setDone(false); setOpen(true); }} />
      </View>
      <Sheet open={open} title="Change password" onClose={() => setOpen(false)}>
        <View style={{ gap: spacing.md }}>
          <Field label="Current password" value={current} onChangeText={setCurrent} secureTextEntry />
          <Field label="New password (at least 10 characters)" value={next} onChangeText={setNext} secureTextEntry />
          {short ? <T variant="error">Use at least 10 characters.</T> : null}
          <Field label="New password again" value={again} onChangeText={setAgain} secureTextEntry />
          {mismatch ? <T variant="error">The two new passwords are different.</T> : null}
          {me?.totp_enabled ? (
            <Field label="Code from your authenticator (or a backup code)" value={code} onChangeText={setCode} keyboardType="number-pad" />
          ) : null}
          <Tick on={others} label="Sign out all my other devices" onPress={() => setOthers(!others)} />
          {change.error ? <T variant="error">{errorMessage(change.error)}</T> : null}
          <Button
            title="Change password"
            busy={change.isPending}
            disabled={!current || next.length < 10 || next !== again || (!!me?.totp_enabled && code.trim().length < 6)}
            onPress={() => change.mutate()}
          />
          <Button kind="secondary" title="Forgot your current password? Reset it by email" onPress={forgot} />
        </View>
      </Sheet>
    </Card>
  );
}

export function DeleteAccount() {
  const { colors } = useColors();
  const router = useRouter();
  const me = useMe().data;
  const signOut = useAuth((s) => s.signOut);
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [typed, setTyped] = useState('');
  const remove = useMutation({
    mutationFn: async () =>
      (await api.post<{ delete_after: string }>('/auth/account/delete', { password, code: code.trim() || null, confirm: typed.trim() })).data,
    onSuccess: async (r) => {
      setOpen(false);
      await signOut(); // the server already signed every device out
      router.replace({ pathname: '/sign-in', params: { deleting: r.delete_after } });
    },
  });

  return (
    <Card>
      <T variant="heading">Delete account</T>
      <T variant="muted">
        Everything stops at once and your account is deleted after 7 days. Sign in within those 7 days to keep it.
      </T>
      <View style={styles.row}>
        <Button kind="danger" title="Delete my account" onPress={() => { remove.reset(); setTyped(''); setPassword(''); setCode(''); setOpen(true); }} />
      </View>
      <Sheet open={open} title="Delete your account?" onClose={() => setOpen(false)}>
        <View style={{ gap: spacing.md }}>
          <View style={[styles.warn, { borderColor: colors.error, backgroundColor: colors.background }]}>
            <T>Right now: every device is signed out, scheduled emails are cancelled, and Telegram reading stops.</T>
            <T>After 7 days: your jobs, posts, emails, chats, resumes, templates, the Telegram login and your email App Passwords are deleted for good.</T>
            <T variant="muted">Changed your mind? Sign in within 7 days and tap “Keep my account”.</T>
          </View>
          <Field label="Password" value={password} onChangeText={setPassword} secureTextEntry />
          {me?.totp_enabled ? (
            <Field label="Code from your authenticator (or a backup code)" value={code} onChangeText={setCode} keyboardType="number-pad" />
          ) : null}
          <Field label="Type DELETE to confirm" value={typed} onChangeText={setTyped} autoCapitalize="characters" />
          {remove.error ? <T variant="error">{errorMessage(remove.error)}</T> : null}
          <Button kind="danger" title="Delete my account" busy={remove.isPending} disabled={!password || typed.trim() !== 'DELETE'} onPress={() => remove.mutate()} />
          <Button kind="secondary" title="Cancel" onPress={() => setOpen(false)} />
        </View>
      </Sheet>
    </Card>
  );
}

/** Signed in during the 7 days: nothing is restored by itself; the user chooses. */
export function PendingDeletion({ deleteAfter }: { deleteAfter: string }) {
  const { colors } = useColors();
  const qc = useQueryClient();
  const signOut = useAuth((s) => s.signOut);
  const keep = useMutation({
    mutationFn: () => api.post('/auth/account/restore'),
    onSuccess: () => {
      qc.setQueryData<Me>(['me'], (old) => (old ? { ...old, delete_after: null } : old));
      void qc.invalidateQueries({ queryKey: ['me'] });
    },
  });
  return (
    <Screen center>
      <View style={[styles.pending, { borderColor: colors.border, backgroundColor: colors.surface }]}>
        <T variant="title">Your account is being deleted</T>
        <T>{`It will be deleted for good on ${longDate(deleteAfter)}. Until then, Telegram reading and email sending are paused.`}</T>
        <T variant="muted">Emails that were scheduled were cancelled; schedule them again after keeping your account.</T>
        {keep.error ? <T variant="error">{errorMessage(keep.error)}</T> : null}
        <Button title="Keep my account" busy={keep.isPending} onPress={() => keep.mutate()} />
        <Button kind="secondary" title="Continue deleting (sign out)" onPress={signOut} />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  tickRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: 4 },
  box: { width: 20, height: 20, borderRadius: 5, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  tickText: { fontFamily: fonts.body, fontSize: 15 },
  warn: { borderWidth: 1, borderRadius: radius.sm, padding: spacing.md, gap: spacing.sm },
  pending: { borderWidth: 1, borderRadius: radius.lg, padding: spacing.xl, gap: spacing.md, width: '100%', maxWidth: 520 },
});
