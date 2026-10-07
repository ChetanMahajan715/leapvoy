/** Email accounts: connect Gmail / Outlook / Zoho / Yahoo with an App Password (the server checks the login by mailing
 * the address itself before saving), pick the default, set a daily limit (≤ 20), and turn test mode on/off. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ExternalLink, Minus, Plus, ShieldCheck, TriangleAlert } from 'lucide-react-native';
import { useState } from 'react';
import { Linking, StyleSheet, Text, TextInput, View } from 'react-native';

import { Pill } from '@/components/chat-cards';
import { IconButton } from '@/components/icon-button';
import { Sheet } from '@/components/sheet';
import { Button, Card, Field, Screen, T } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

type Account = {
  id: number; email: string; provider: string; is_default: boolean; daily_limit: number; sent_today: number;
  scheduled: number; app_password_help: string;
};
type Sending = { test_mode: boolean; rules: { daily_limit_default: number; daily_limit_max: number; gap_minutes: [number, number]; hr_cooldown_days: number }; senders: number };

const HELP: Record<string, [string, string]> = {
  gmail: ['Gmail', 'https://myaccount.google.com/apppasswords'],
  outlook: ['Outlook', 'https://account.live.com/proofs/AppPassword'],
  zoho: ['Zoho', 'https://accounts.zoho.in/home#security/app_password'],
  yahoo: ['Yahoo', 'https://login.yahoo.com/myaccount/security/'],
};
const DOMAINS: Record<string, string> = {
  'gmail.com': 'gmail', 'googlemail.com': 'gmail', 'outlook.com': 'outlook', 'hotmail.com': 'outlook', 'live.com': 'outlook',
  'zoho.com': 'zoho', 'zoho.in': 'zoho', 'zohomail.in': 'zoho', 'yahoo.com': 'yahoo', 'yahoo.in': 'yahoo',
};

const MAX = 500; // Gmail's own daily ceiling for a personal account

/** Type a number (or use − / +); saved when you leave the box or press Enter. */
function LimitInput({ value, max, onSave }: { value: number; max: number; onSave: (n: number) => void }) {
  const { colors } = useColors();
  const [text, setText] = useState(String(value));
  const save = () => {
    const n = Math.round(Number(text));
    if (Number.isFinite(n) && n >= 1 && n <= max && n !== value) onSave(n);
    else setText(String(value));
  };
  return (
    <TextInput
      accessibilityLabel="Daily limit"
      value={text}
      onChangeText={(v) => setText(v.replace(/\D/g, '').slice(0, 3))}
      onBlur={save}
      onSubmitEditing={save}
      keyboardType="number-pad"
      returnKeyType="done"
      style={[styles.limit, { color: colors.text, borderColor: colors.border, backgroundColor: colors.background }]}
    />
  );
}

export default function EmailAccounts() {
  const { colors } = useColors();
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ['senders'], queryFn: async () => (await api.get<Account[]>('/senders')).data });
  const sending = useQuery({ queryKey: ['sending'], queryFn: async () => (await api.get<Sending>('/sending')).data });
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [connected, setConnected] = useState<string | null>(null);
  const [askOff, setAskOff] = useState(false);
  const [removing, setRemoving] = useState<Account | null>(null);
  const [tested, setTested] = useState<number | null>(null);
  const refresh = () => Promise.all(['senders', 'sending', 'me'].map((k) => qc.invalidateQueries({ queryKey: [k] })));

  const connect = useMutation({
    mutationFn: async () => (await api.post<Account>('/senders', { email: email.trim(), password }, { timeout: 90_000 })).data,
    onSuccess: (a) => {
      setConnected(a.email);
      setEmail('');
      setPassword('');
      void refresh();
    },
  });
  const mode = useMutation({
    mutationFn: (on: boolean) => api.put('/sending', { test_mode: on, confirm: !on }),
    onSuccess: () => {
      setAskOff(false);
      void refresh();
    },
  });
  const makeDefault = useMutation({ mutationFn: (id: number) => api.post(`/senders/${id}/default`), onSuccess: () => void refresh() });
  const limit = useMutation({
    mutationFn: ({ id, n }: { id: number; n: number }) => api.patch(`/senders/${id}`, { daily_limit: n }),
    onSuccess: () => void refresh(),
  });
  const test = useMutation({
    mutationFn: (id: number) => api.post(`/senders/${id}/test`, {}, { timeout: 90_000 }),
    onSuccess: (_, id) => setTested(id),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/senders/${id}`),
    onSuccess: () => {
      setRemoving(null);
      void refresh();
    },
  });

  const provider = DOMAINS[email.trim().toLowerCase().split('@')[1] ?? ''];
  const s = sending.data;
  const actionError = makeDefault.error ?? limit.error ?? test.error;

  return (
    <Screen>
      <Card>
        <T variant="heading">Sending</T>
        {s ? (
          <>
            <View style={[styles.mode, { backgroundColor: s.test_mode ? colors.primarySoft : colors.surfaceAlt, borderColor: s.test_mode ? colors.primary : colors.error }]}>
              {s.test_mode ? (
                <ShieldCheck size={18} color={colors.primaryText} strokeWidth={2} />
              ) : (
                <TriangleAlert size={18} color={colors.error} strokeWidth={2} />
              )}
              <Text style={[styles.modeText, { color: colors.text }]}>
                {s.test_mode
                  ? 'Test mode is ON: every email goes to your own inbox, never to a company.'
                  : 'Test mode is OFF: approved emails go to the addresses in the job posts.'}
              </Text>
            </View>
            <T variant="muted">
              {`Safety rules: ${s.rules.daily_limit_default} emails a day per account to start (change it below) · ${s.rules.gap_minutes[0]}–${s.rules.gap_minutes[1]} minutes between emails · one email per HR address every ${s.rules.hr_cooldown_days} days · nothing is sent until you approve it.`}
            </T>
            <View style={styles.row}>
              {s.test_mode ? (
                <Pill label="Turn test mode off" onPress={() => { mode.reset(); setAskOff(true); }} />
              ) : (
                <Pill label="Turn test mode on" primary busy={mode.isPending} onPress={() => mode.mutate(true)} />
              )}
            </View>
          </>
        ) : sending.error ? (
          <T variant="error">{errorMessage(sending.error)}</T>
        ) : (
          <T variant="muted">Loading…</T>
        )}
      </Card>

      <Card>
        <T variant="heading">Connect an email</T>
        <T variant="muted">Gmail, Outlook, Zoho or Yahoo. Use an App Password, not your normal password.</T>
        <Field label="Email address" value={email} onChangeText={setEmail} placeholder="e.g. you@gmail.com" keyboardType="email-address" />
        <Field label="App Password" value={password} onChangeText={setPassword} placeholder="16 letters, spaces are fine" secureTextEntry />
        <View style={styles.row}>
          {(provider ? [HELP[provider]] : [HELP.gmail]).map(([name, url]) => (
            <Pill key={url} label={`Create a ${name} App Password`} icon={ExternalLink} onPress={() => Linking.openURL(url)} />
          ))}
        </View>
        {!provider || provider === 'gmail' ? (
          <T variant="muted">Gmail shows App Passwords only when 2-Step Verification is on (with your phone as the second step).</T>
        ) : null}
        {connect.isPending ? <T variant="muted">Checking the login by sending a test email to this address…</T> : null}
        {connect.error ? <T variant="error">{errorMessage(connect.error)}</T> : null}
        {connected ? <T style={{ color: colors.success }}>{`Connected ${connected}. Check its inbox for “Leapvoy is connected”.`}</T> : null}
        <Button title="Connect" busy={connect.isPending} disabled={!email.includes('@') || password.length < 4} onPress={() => { setConnected(null); connect.mutate(); }} />
      </Card>

      {accounts.error ? <T variant="error">{errorMessage(accounts.error)}</T> : null}
      {accounts.data?.map((a) => (
        <Card key={a.id}>
          <View style={styles.head}>
            <Text numberOfLines={1} style={[styles.email, { color: colors.text }]}>{a.email}</Text>
            {a.is_default ? (
              <View style={[styles.chip, { borderColor: colors.success }]}>
                <Text style={[styles.chipText, { color: colors.success }]}>Default</Text>
              </View>
            ) : null}
          </View>
          <T variant="muted">{`Sent today ${a.sent_today} / ${a.daily_limit}${a.scheduled ? ` · ${a.scheduled} scheduled` : ''}`}</T>
          <View style={styles.row}>
            <T>Daily limit</T>
            <IconButton icon={Minus} label="Lower the daily limit" onPress={() => a.daily_limit > 1 && limit.mutate({ id: a.id, n: a.daily_limit - 1 })} />
            <LimitInput key={a.daily_limit} value={a.daily_limit} max={MAX} onSave={(n) => limit.mutate({ id: a.id, n })} />
            <IconButton icon={Plus} label="Raise the daily limit" onPress={() => a.daily_limit < MAX && limit.mutate({ id: a.id, n: a.daily_limit + 1 })} />
            <T variant="muted">emails a day</T>
          </View>
          {a.daily_limit > 20 ? (
            <T style={{ color: colors.warning }}>
              {`Above 20 a day, Gmail may flag the account as spam or pause it for a day (Gmail's own limit is ${MAX}).`}
            </T>
          ) : null}
          <View style={styles.row}>
            {!a.is_default ? <Pill label="Make default" primary onPress={() => makeDefault.mutate(a.id)} /> : null}
            <Pill label="Send test email" busy={test.isPending && test.variables === a.id} onPress={() => { setTested(null); test.mutate(a.id); }} />
            <Pill label="Remove" onPress={() => { remove.reset(); setRemoving(a); }} />
          </View>
          {tested === a.id ? <T style={{ color: colors.success }}>Sent. Check this inbox for “Leapvoy test email”.</T> : null}
        </Card>
      ))}
      {accounts.data && !accounts.data.length ? <T variant="muted">{"No email connected yet. Emails can't be sent until you connect one."}</T> : null}
      {actionError ? <T variant="error">{errorMessage(actionError)}</T> : null}

      <Sheet open={askOff} title="Turn test mode off?" onClose={() => setAskOff(false)}>
        <View style={{ gap: spacing.md }}>
          <T>Emails you approve will go to the real addresses in the job posts, from your default email account. Nothing is sent without your approval, and every safety rule still applies.</T>
          {mode.error ? <T variant="error">{errorMessage(mode.error)}</T> : null}
          <Button kind="danger" title="Yes, send for real" busy={mode.isPending} onPress={() => mode.mutate(false)} />
          <Button kind="secondary" title="Keep test mode on" onPress={() => setAskOff(false)} />
        </View>
      </Sheet>
      <Sheet open={!!removing} title="Remove this email account?" onClose={() => setRemoving(null)}>
        <View style={{ gap: spacing.md }}>
          <T>{`${removing?.email} will be disconnected and its App Password deleted from Leapvoy. Emails already sent are not affected.`}</T>
          {remove.error ? <T variant="error">{errorMessage(remove.error)}</T> : null}
          <Button kind="danger" title="Remove" busy={remove.isPending} onPress={() => removing && remove.mutate(removing.id)} />
          <Button kind="secondary" title="Cancel" onPress={() => setRemoving(null)} />
        </View>
      </Sheet>
    </Screen>
  );
}

const styles = StyleSheet.create({
  mode: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, borderWidth: 1, borderRadius: radius.sm, padding: spacing.md },
  modeText: { fontFamily: fonts.semibold, fontSize: 14, lineHeight: 20, flexShrink: 1 },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.sm },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  email: { fontFamily: fonts.semibold, fontSize: 16, flexShrink: 1 },
  chip: { borderWidth: 1, borderRadius: radius.pill, paddingVertical: 3, paddingHorizontal: 10 },
  chipText: { fontFamily: fonts.semibold, fontSize: 12 },
  limit: { fontFamily: fonts.heading, fontSize: 16, width: 64, textAlign: 'center', borderWidth: 1, borderRadius: radius.sm,
    paddingVertical: 6 },
});
