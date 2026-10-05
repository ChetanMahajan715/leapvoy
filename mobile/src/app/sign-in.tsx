import { Link, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { Brand } from '@/components/brand';
import { ServerAddress } from '@/components/server-address';
import { Button, Card, Field, Screen, T } from '@/components/ui';
import { errorMessage } from '@/lib/api';
import { NeedsCode, useAuth } from '@/lib/auth';
import { spacing } from '@/theme/theme';

export default function SignIn() {
  const signIn = useAuth((s) => s.signIn);
  const { reset, deleting } = useLocalSearchParams<{ reset?: string; deleting?: string }>();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [askCode, setAskCode] = useState(false); // shown only for accounts with 2-step sign-in on
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit() {
    setError('');
    setBusy(true);
    try {
      await signIn(email.trim(), password, askCode ? code.trim() : undefined);
    } catch (e) {
      if (e instanceof NeedsCode) setAskCode(true);
      else setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen center>
      <View style={{ alignItems: 'center', gap: spacing.sm }}>
        <Brand />
        <T variant="muted">Your job-outreach agent</T>
      </View>
      <Card>
        <T variant="heading">Sign in</T>
        {reset ? <T variant="muted">Password changed ✓. Sign in with your new password.</T> : null}
        {deleting ? (
          <T variant="muted">{`Your account will be deleted on ${new Date(deleting).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' })}. Sign in before then to keep it.`}</T>
        ) : null}
        <Field label="Email" value={email} onChangeText={setEmail} keyboardType="email-address" autoComplete="email" />
        <Field
          label="Password"
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          autoComplete="password"
          onSubmitEditing={submit}
        />
        {askCode ? (
          <Field
            label="6-digit code from your authenticator app (or a backup code)"
            value={code}
            onChangeText={setCode}
            maxLength={9}
            autoComplete="one-time-code"
            autoFocus
            onSubmitEditing={submit}
          />
        ) : null}
        {error ? <T variant="error">{error}</T> : null}
        <Button
          title="Sign in"
          onPress={submit}
          busy={busy}
          disabled={!email || !password || (askCode && code.length < 6)}
        />
      </Card>
      <View style={{ alignItems: 'center', gap: spacing.sm }}>
        <Link href="/forgot-password">
          <T variant="muted">Forgot password?</T>
        </Link>
        <Link href="/sign-up">
          <T variant="muted">New here? Create an account</T>
        </Link>
      </View>
      <ServerAddress />
    </Screen>
  );
}
