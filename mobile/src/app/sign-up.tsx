import { Link } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { Brand } from '@/components/brand';
import { Button, Card, Field, Screen, T } from '@/components/ui';
import { errorMessage } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { spacing } from '@/theme/theme';
import { ServerAddress } from '@/components/server-address';

/** Email + password + confirm → signed in. 2-step sign-in is optional (Settings → 2-step sign-in). */
export default function SignUp() {
  const signUp = useAuth((s) => s.signUp);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const mismatch = confirm.length > 0 && confirm !== password;

  async function submit() {
    setError('');
    setBusy(true);
    try {
      await signUp(email.trim(), password);
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
        <T variant="muted">Create your account</T>
      </View>
      <Card>
        <Field label="Email" value={email} onChangeText={setEmail} keyboardType="email-address" autoComplete="email" />
        <Field label="Password (at least 10 characters)" value={password} onChangeText={setPassword} secureTextEntry />
        <Field label="Confirm password" value={confirm} onChangeText={setConfirm} secureTextEntry onSubmitEditing={submit} />
        {mismatch ? <T variant="error">Passwords don’t match.</T> : null}
        {error ? <T variant="error">{error}</T> : null}
        <Button
          title="Create account"
          busy={busy}
          disabled={!email || password.length < 10 || confirm !== password}
          onPress={submit}
        />
        <T variant="muted">You can turn on 2-step sign-in later in Settings → 2-step sign-in (tap your name at the bottom of the menu).</T>
      </Card>
      <Link href="/sign-in" style={{ alignSelf: 'center' }}>
        <T variant="muted">Already have an account? Sign in</T>
      </Link>
      <ServerAddress />
    </Screen>
  );
}
