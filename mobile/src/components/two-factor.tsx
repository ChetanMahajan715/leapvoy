import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as Clipboard from 'expo-clipboard';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Image, Linking, Platform, View } from 'react-native';

import { Button, Card, Field, T } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { useAuth, useMe } from '@/lib/auth';
import { spacing } from '@/theme/theme';

type Setup = { totp_secret: string; otpauth_uri: string; qr_png: string };

function useCopy() {
  const [copied, setCopied] = useState<string | null>(null);
  return {
    copied,
    copy: async (what: string, text: string) => {
      await Clipboard.setStringAsync(text);
      setCopied(what);
      setTimeout(() => setCopied(null), 2000);
    },
  };
}

/** Optional 2-step sign-in (Google Authenticator): QR + key with Copy + open-in-app, then 10 backup codes.
 *  Used in Settings → 2-step sign-in and right after sign-up (onFinished closes that screen). */
export function TwoFactor({ enabled, onFinished }: { enabled: boolean; onFinished?: () => void }) {
  const qc = useQueryClient();
  const { copied, copy } = useCopy();
  const [setup, setSetup] = useState<Setup | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [turningOff, setTurningOff] = useState(false);

  const done = () => {
    setSetup(null);
    setBackupCodes(null);
    setCode('');
    setPassword('');
    setTurningOff(false);
    qc.invalidateQueries({ queryKey: ['me'] });
    onFinished?.();
  };
  const start = useMutation({
    mutationFn: async () => (await api.post<Setup>('/auth/2fa/setup')).data,
    onSuccess: setSetup,
  });
  const enable = useMutation({
    mutationFn: async () =>
      (await api.post<{ backup_codes: string[] }>('/auth/2fa/enable', { code: code.trim() })).data,
    onSuccess: (data) => setBackupCodes(data.backup_codes), // show them before closing
  });
  const router = useRouter();
  const email = useMe().data?.email;
  const signOut = useAuth((s) => s.signOut);
  // A reset signs out every device anyway (server side), so sign out here first, then open the reset screen.
  const resetPassword = async () => {
    await signOut();
    router.replace({ pathname: '/forgot-password', params: email ? { email } : {} });
  };
  const disable = useMutation({
    mutationFn: () => api.post('/auth/2fa/disable', { password, code: code.trim() }),
    onSuccess: done,
  });
  const error = start.error ?? enable.error ?? disable.error;

  if (backupCodes) {
    return (
      <Card>
        <T variant="heading">2-step sign-in is on ✓</T>
        <T>Save these 10 backup codes somewhere safe (notes app, printout). Each one signs you in once if you lose your phone:</T>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
          {backupCodes.map((c) => (
            <View key={c} style={{ width: 120 }}>
              <T variant="mono">{c}</T>
            </View>
          ))}
        </View>
        <Button
          kind="secondary"
          title={copied === 'codes' ? 'Copied ✓' : 'Copy all codes'}
          onPress={() => copy('codes', backupCodes.join('\n'))}
        />
        <Button title="I’ve saved them" onPress={done} />
      </Card>
    );
  }

  return (
    <Card>
      <T variant="heading">2-step sign-in</T>
      <T variant="muted">
        {enabled
          ? 'On: signing in needs a code from your authenticator app (or a backup code).'
          : 'Off (optional). Turn it on to ask for a code from Google Authenticator when signing in.'}
      </T>

      {!enabled && !setup ? (
        <Button kind="secondary" title="Turn on" busy={start.isPending} onPress={() => start.mutate()} />
      ) : null}

      {!enabled && setup ? (
        <View style={{ gap: spacing.md }}>
          <T>1. In Google Authenticator tap + and scan this QR code…</T>
          <Image
            source={{ uri: setup.qr_png }}
            style={{ width: 200, height: 200, alignSelf: 'center', borderRadius: 8 }}
            accessibilityLabel="QR code for Google Authenticator"
          />
          <T>…or choose “Enter a setup key” (account: Leapvoy) and paste this key:</T>
          <T variant="mono">{setup.totp_secret.match(/.{1,4}/g)?.join(' ')}</T>
          <View style={{ flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' }}>
            <Button
              kind="secondary"
              title={copied === 'key' ? 'Copied ✓' : 'Copy key'}
              onPress={() => copy('key', setup.totp_secret)}
            />
            {Platform.OS !== 'web' ? (
              <Button kind="secondary" title="Open in authenticator app" onPress={() => Linking.openURL(setup.otpauth_uri)} />
            ) : null}
          </View>
          <T>2. Type the 6-digit code it shows:</T>
          <Field label="Code" value={code} onChangeText={setCode} keyboardType="number-pad" maxLength={6} />
          <Button title="Confirm and turn on" busy={enable.isPending} disabled={code.length < 6} onPress={() => enable.mutate()} />
        </View>
      ) : null}

      {enabled && !turningOff ? (
        <Button kind="danger" title="Turn off" onPress={() => setTurningOff(true)} />
      ) : null}
      {enabled && turningOff ? (
        <View style={{ gap: spacing.md }}>
          <Field label="Password" value={password} onChangeText={setPassword} secureTextEntry />
          <Field
            label="Current 6-digit code (or a backup code)"
            value={code}
            onChangeText={setCode}
            maxLength={9}
          />
          <Button
            kind="danger"
            title="Turn off 2-step sign-in"
            busy={disable.isPending}
            disabled={!password || code.length < 6}
            onPress={() => disable.mutate()}
          />
          <T variant="muted">
            Forgot your password? Reset it by email first. This signs you out on all devices. Then sign in with the
            new password and turn 2-step sign-in off here.
          </T>
          <Button kind="secondary" title="Forgot password? Reset by email" onPress={resetPassword} />
        </View>
      ) : null}

      {error ? <T variant="error">{errorMessage(error)}</T> : null}
    </Card>
  );
}
