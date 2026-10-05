/** Channels: connect Telegram (phone → code, or a QR code scanned with the Telegram app; then an optional 2-step
 * password), choose which channels Leapvoy reads,
 * and read older posts. Leapvoy only reads Telegram: it never posts, joins or marks anything as read. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, TriangleAlert } from 'lucide-react-native';
import { useEffect, useState } from 'react';
import { Image, Linking, Platform, StyleSheet, Switch, Text, View } from 'react-native';

import { Pill } from '@/components/chat-cards';
import { Sheet } from '@/components/sheet';
import { Button, Card, Field, Screen, T } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

type Status = { configured: boolean; connected: boolean; revoked: boolean; name: string | null; phone: string | null };
type Channel = { id: number; title: string; username: string | null; enabled: boolean; posts: number; last_post_at: string | null };
type Step = 'phone' | 'code' | 'password' | 'qr';
type Qr = { state: 'none' | 'waiting' | 'needs_password' | 'done' | 'expired' | 'error'; url?: string; qr_png?: string; error?: string | null };

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' });
}

/** Scan with the Telegram app (web), or open the login link in Telegram on this phone (Android). The server waits for
 * the scan; this asks every 2 s. A 2-step password continues in the normal password step. */
function QrStep({ onPassword, onDone, onPhone }: { onPassword: () => void; onDone: () => void; onPhone: () => void }) {
  const { colors } = useColors();
  const start = useMutation({ mutationFn: async () => (await api.post<Qr>('/telegram/qr', {}, { timeout: 60_000 })).data });
  const { mutate } = start;
  useEffect(() => mutate(), [mutate]);
  const q = useQuery({
    queryKey: ['telegram-qr'],
    queryFn: async () => (await api.get<Qr>('/telegram/qr')).data,
    enabled: start.isSuccess,
    staleTime: 0,
    gcTime: 0,
    refetchInterval: (query) => (query.state.data?.state === 'waiting' ? 2000 : false),
  });
  const qr = q.data ?? start.data;
  useEffect(() => {
    if (qr?.state === 'done') onDone();
    if (qr?.state === 'needs_password') onPassword();
  }, [qr?.state, onDone, onPassword]);
  const phone = Platform.OS !== 'web';
  return (
    <View style={{ gap: spacing.md }}>
      {phone ? (
        <T variant="muted">Tap “Open in Telegram” and confirm the login there. Or scan the code below with Telegram on another phone.</T>
      ) : (
        <T variant="muted">On your phone, open Telegram → Settings → Devices → Link Desktop Device, and scan this code.</T>
      )}
      {qr?.state === 'waiting' && qr.qr_png ? (
        <>
          {phone && qr.url ? <Button title="Open in Telegram" onPress={() => Linking.openURL(qr.url!)} /> : null}
          <View style={[styles.qr, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <Image source={{ uri: qr.qr_png }} style={{ width: 220, height: 220 }} accessibilityLabel="QR code to log in with Telegram" />
          </View>
          <T variant="muted">The code renews by itself every half minute. Waiting for your scan…</T>
        </>
      ) : null}
      {start.isPending ? <T variant="muted">Getting a QR code from Telegram…</T> : null}
      {qr?.state === 'expired' || qr?.state === 'error' ? (
        <>
          <Text style={[styles.note, { color: colors.error }]}>{qr.error ?? 'The QR code ran out of time.'}</Text>
          <Button title="Show a new QR code" busy={start.isPending} onPress={() => mutate()} />
        </>
      ) : null}
      {start.error ? <Text style={[styles.note, { color: colors.error }]}>{errorMessage(start.error)}</Text> : null}
      <Pill label="Use my phone number instead" onPress={onPhone} />
    </View>
  );
}

/** Phone → code → (2-step password) → connected; or QR (scan with the Telegram app) → (2-step password) → connected. */
function Connect({ onDone }: { onDone: () => void }) {
  const { colors } = useColors();
  const [step, setStep] = useState<Step>(Platform.OS === 'web' ? 'qr' : 'phone');
  const [phone, setPhone] = useState('+91 ');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const send = useMutation({
    mutationFn: () => api.post('/telegram/code', { phone }, { timeout: 60_000 }),
    onSuccess: () => {
      setCode('');
      setStep('code');
    },
  });
  const verify = useMutation({
    mutationFn: async () => (await api.post<{ needs_password?: boolean }>('/telegram/verify', { code }, { timeout: 60_000 })).data,
    onSuccess: (r) => (r.needs_password ? setStep('password') : onDone()),
  });
  const twoStep = useMutation({
    mutationFn: () => api.post('/telegram/password', { password }, { timeout: 60_000 }),
    onSuccess: () => {
      setPassword('');
      onDone();
    },
  });
  const error = send.error ?? verify.error ?? twoStep.error;

  return (
    <View style={{ gap: spacing.md }}>
      {step === 'phone' ? (
        <>
          <Field label="Your Telegram phone number" value={phone} onChangeText={setPhone} keyboardType="phone-pad" placeholder="+91 98765 43210" />
          <Button title="Send code" busy={send.isPending} disabled={phone.replace(/\D/g, '').length < 8} onPress={() => send.mutate()} />
          <Pill label={Platform.OS === 'web' ? 'Scan a QR code instead' : 'Log in with Telegram instead (no code)'} onPress={() => setStep('qr')} />
        </>
      ) : null}
      {step === 'qr' ? <QrStep onDone={onDone} onPassword={() => setStep('password')} onPhone={() => setStep('phone')} /> : null}
      {step === 'code' ? (
        <>
          <T variant="muted">Telegram sent a login code to your Telegram app (a message from “Telegram”), not by SMS.</T>
          <Field label="Login code" value={code} onChangeText={setCode} keyboardType="number-pad" placeholder="e.g. 12345" />
          <Button title="Log in" busy={verify.isPending} disabled={code.replace(/\D/g, '').length < 5} onPress={() => verify.mutate()} />
          <View style={styles.row}>
            <Pill label="Send a new code" onPress={() => { send.reset(); verify.reset(); send.mutate(); }} />
            <Pill label="Change number" onPress={() => { verify.reset(); setStep('phone'); }} />
          </View>
        </>
      ) : null}
      {step === 'password' ? (
        <>
          <T variant="muted">Your Telegram has 2-step verification. Enter that password: it is used once to log in and never saved.</T>
          <Field label="2-step password" value={password} onChangeText={setPassword} secureTextEntry />
          <Button title="Log in" busy={twoStep.isPending} disabled={!password} onPress={() => twoStep.mutate()} />
        </>
      ) : null}
      {error ? <Text style={[styles.note, { color: colors.error }]}>{errorMessage(error)}</Text> : null}
    </View>
  );
}

export default function Channels() {
  const { colors } = useColors();
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ['telegram'], queryFn: async () => (await api.get<Status>('/telegram')).data });
  const channels = useQuery({ queryKey: ['channels'], queryFn: async () => (await api.get<Channel[]>('/channels')).data });
  const [search, setSearch] = useState('');
  const [askLogout, setAskLogout] = useState(false);
  const [askBackfill, setAskBackfill] = useState(false);
  const [backfilled, setBackfilled] = useState<number | null>(null);
  const refreshAll = () => Promise.all(['telegram', 'channels', 'posts', 'jobs'].map((k) => qc.invalidateQueries({ queryKey: [k] })));

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => api.patch(`/channels/${id}`, { enabled }),
    onMutate: ({ id, enabled }) =>
      qc.setQueryData<Channel[]>(['channels'], (old) => old?.map((c) => (c.id === id ? { ...c, enabled } : c))),
    onSettled: () => qc.invalidateQueries({ queryKey: ['channels'] }),
  });
  const reload = useMutation({
    mutationFn: async () => (await api.post<Channel[]>('/channels/refresh', {}, { timeout: 90_000 })).data,
    onSuccess: (list) => qc.setQueryData(['channels'], list),
  });
  const logout = useMutation({
    mutationFn: () => api.post('/telegram/logout', {}, { timeout: 60_000 }),
    onSuccess: () => {
      setAskLogout(false);
      void refreshAll();
    },
  });
  const backfill = useMutation({
    mutationFn: (days: number) => api.post('/telegram/backfill', { days }, { timeout: 60_000 }),
    onSuccess: (_, days) => {
      setAskBackfill(false);
      setBackfilled(days);
    },
  });

  const s = status.data;
  const all = channels.data ?? [];
  const shown = search.trim() ? all.filter((c) => c.title.toLowerCase().includes(search.trim().toLowerCase())) : all;
  const on = all.filter((c) => c.enabled).length;

  return (
    <Screen>
      <Card>
        <T variant="heading">Telegram</T>
        <T variant="muted">Leapvoy only reads your channels. It never posts, joins, or marks messages as read.</T>
        {!s ? (
          status.error ? <T variant="error">{errorMessage(status.error)}</T> : <T variant="muted">Checking Telegram…</T>
        ) : !s.configured ? (
          <T variant="error">Telegram is not set up on the server yet (TELEGRAM_API_ID / TELEGRAM_API_HASH in .env).</T>
        ) : s.connected && !s.revoked ? (
          <>
            <View style={styles.line}>
              <CheckCircle2 size={18} color={colors.success} strokeWidth={2} />
              <Text style={[styles.strong, { color: colors.text }]}>
                {`Connected${s.name ? ` as ${s.name}` : ''}${s.phone ? ` · ${s.phone}` : ''}`}
              </Text>
            </View>
            <View style={styles.row}>
              <Pill label="Disconnect" onPress={() => { logout.reset(); setAskLogout(true); }} />
            </View>
          </>
        ) : (
          <>
            {s.revoked ? (
              <View style={[styles.box, { borderColor: colors.warning, backgroundColor: colors.background }]}>
                <TriangleAlert size={16} color={colors.warning} strokeWidth={2} />
                <Text style={[styles.note, { color: colors.text }]}>
                  Telegram signed Leapvoy out (for example from Active sessions in Telegram). Log in again to keep reading posts.
                </Text>
              </View>
            ) : null}
            <Connect onDone={() => void refreshAll()} />
          </>
        )}
      </Card>

      {s?.connected && !s.revoked ? (
        <Card>
          <T variant="heading">Channels</T>
          <T variant="muted">
            {`${on} of ${all.length} on. Leapvoy reads new posts from the channels that are on and checks them against your resume.`}
          </T>
          <View style={styles.row}>
            <Pill label="Refresh list" busy={reload.isPending} onPress={() => reload.mutate()} />
            <Pill label="Read older posts" onPress={() => { backfill.reset(); setAskBackfill(true); }} />
          </View>
          {backfilled ? (
            <T style={{ color: colors.success }}>
              {`Reading the last ${backfilled} days in the background. New posts appear in Jobs → All posts.`}
            </T>
          ) : null}
          {reload.error ? <T variant="error">{errorMessage(reload.error)}</T> : null}
          {all.length > 6 ? <Field label="Search channels" value={search} onChangeText={setSearch} placeholder="e.g. referrals" /> : null}
          {channels.error ? <T variant="error">{errorMessage(channels.error)}</T> : null}
          {shown.map((c) => (
            <View key={c.id} style={[styles.channel, { borderColor: colors.border }]}>
              <View style={{ flex: 1, gap: 2 }}>
                <Text numberOfLines={1} style={[styles.strong, { color: colors.text }]}>{c.title || 'Untitled channel'}</Text>
                <Text style={[styles.note, { color: colors.textMuted }]}>
                  {c.posts ? `${c.posts} posts saved${c.last_post_at ? ` · last post ${shortDate(c.last_post_at)}` : ''}` : 'No posts saved yet'}
                </Text>
              </View>
              <Switch
                accessibilityLabel={`Read ${c.title}`}
                value={c.enabled}
                onValueChange={(enabled) => toggle.mutate({ id: c.id, enabled })}
                trackColor={{ false: colors.border, true: colors.primary }}
                thumbColor={colors.surface}
                {...({ activeThumbColor: colors.surface } as object)}
              />
            </View>
          ))}
          {toggle.error ? <T variant="error">{errorMessage(toggle.error)}</T> : null}
          {all.length && !shown.length ? <T variant="muted">No channel matches that search.</T> : null}
          {!all.length && !channels.isLoading ? <T variant="muted">No channels yet. Tap Refresh list.</T> : null}
        </Card>
      ) : null}

      <Sheet open={askLogout} title="Disconnect Telegram?" onClose={() => setAskLogout(false)}>
        <View style={{ gap: spacing.md }}>
          <T>Leapvoy stops reading your channels and the login is ended on Telegram too. Saved posts and jobs stay.</T>
          {logout.error ? <T variant="error">{errorMessage(logout.error)}</T> : null}
          <Button kind="danger" title="Disconnect" busy={logout.isPending} onPress={() => logout.mutate()} />
          <Button kind="secondary" title="Cancel" onPress={() => setAskLogout(false)} />
        </View>
      </Sheet>
      <Sheet open={askBackfill} title="Read older posts" onClose={() => setAskBackfill(false)}>
        <View style={{ gap: spacing.md }}>
          <T>From the channels that are on. Older posts are only listed in All posts (the AI checks the last 3 days).</T>
          {backfill.error ? <T variant="error">{errorMessage(backfill.error)}</T> : null}
          {[7, 30, 90].map((d) => (
            <Button key={d} kind={d === 7 ? 'primary' : 'secondary'} title={`Last ${d} days`} busy={backfill.isPending && backfill.variables === d} onPress={() => backfill.mutate(d)} />
          ))}
        </View>
      </Sheet>
    </Screen>
  );
}

const styles = StyleSheet.create({
  qr: { alignSelf: 'center', padding: spacing.md, borderRadius: radius.md, borderWidth: 1 },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.sm },
  line: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  strong: { fontFamily: fonts.semibold, fontSize: 15, flexShrink: 1 },
  note: { fontFamily: fonts.body, fontSize: 14, lineHeight: 20, flexShrink: 1 },
  box: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm, borderWidth: 1, borderRadius: radius.sm, padding: spacing.md },
  channel: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderTopWidth: 1, paddingTop: spacing.sm },
});
