import { View } from 'react-native';

import { Brand } from '@/components/brand';
import { TwoFactor } from '@/components/two-factor';
import { Button, Screen, T } from '@/components/ui';
import { useAuth } from '@/lib/auth';
import { spacing } from '@/theme/theme';

const dismiss = () => useAuth.setState({ offer2fa: false });

/** Shown once right after sign-up: add 2-step sign-in now, or skip (can be done later in Settings). */
export function SecureAccount() {
  return (
    <Screen center>
      <View style={{ alignItems: 'center', gap: spacing.sm }}>
        <Brand />
        <T variant="title">Protect your account?</T>
        <T variant="muted">
          2-step sign-in asks for a code from Google Authenticator when you sign in. It’s optional; you can turn it on
          or off anytime in Settings.
        </T>
      </View>
      <TwoFactor enabled={false} onFinished={dismiss} />
      <Button kind="secondary" title="Skip for now" onPress={dismiss} />
    </Screen>
  );
}
