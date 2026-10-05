import { Link, useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { Brand } from '@/components/brand';
import { Button, Card, Field, Screen, T } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { spacing } from '@/theme/theme';

/** Forgot password: email → 6-digit code by email → new password. (2-step sign-in, if on, stays on.) */
export default function ForgotPassword() {
  const router = useRouter();
  const params = useLocalSearchParams<{ email?: string }>(); // filled in when coming from Settings → 2-step sign-in → Turn off
  const [email, setEmail] = useState(params.email ?? '');
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<void>) {
    setError('');
    setBusy(true);
    try {
      await action();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen center>
      <View style={{ alignItems: 'center', gap: spacing.sm }}>
        <Brand />
        <T variant="muted">Reset your password</T>
      </View>
      <Card>
        {!sent ? (
          <>
            <T>Enter your account email. We’ll send a 6-digit code from leapvoy@gmail.com.</T>
            <Field label="Email" value={email} onChangeText={setEmail} keyboardType="email-address" autoComplete="email" />
            {error ? <T variant="error">{error}</T> : null}
            <Button
              title="Send code"
              busy={busy}
              disabled={!email}
              onPress={() =>
                run(async () => {
                  await api.post('/auth/password/forgot', { email: email.trim() });
                  setSent(true);
                })
              }
            />
          </>
        ) : (
          <>
            <T>If {email.trim()} has an account, a code is on its way (check spam too). It works for 15 minutes.</T>
            <Field label="6-digit code" value={code} onChangeText={setCode} keyboardType="number-pad" maxLength={6} />
            <Field label="New password (at least 10 characters)" value={password} onChangeText={setPassword} secureTextEntry />
            <Field label="Confirm new password" value={confirm} onChangeText={setConfirm} secureTextEntry />
            {confirm && confirm !== password ? <T variant="error">Passwords don’t match.</T> : null}
            {error ? <T variant="error">{error}</T> : null}
            <Button
              title="Set new password"
              busy={busy}
              disabled={code.length < 6 || password.length < 10 || confirm !== password}
              onPress={() =>
                run(async () => {
                  await api.post('/auth/password/reset', { email: email.trim(), code: code.trim(), new_password: password });
                  router.replace({ pathname: '/sign-in', params: { reset: '1' } });
                })
              }
            />
            <Button kind="secondary" title="Send a new code" onPress={() => { setSent(false); setCode(''); }} />
          </>
        )}
      </Card>
      <Link href="/sign-in" style={{ alignSelf: 'center' }}>
        <T variant="muted">Back to sign in</T>
      </Link>
    </Screen>
  );
}
