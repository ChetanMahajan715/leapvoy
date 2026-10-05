import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { View } from 'react-native';

import { ChangePassword, DeleteAccount } from '@/components/account-security';
import { TwoFactor } from '@/components/two-factor';
import { Button, Card, Choice, Screen, T } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { useAuth, useMe } from '@/lib/auth';
import type { Appearance } from '@/theme/theme';
import { spacing } from '@/theme/theme';
import { setAppearance, useAppearance, useColors } from '@/theme/use-colors';

type Device = { id: number; name: string; created_at: string; last_seen_at: string; current: boolean };

export default function Settings() {
  const { colors } = useColors();
  const appearance = useAppearance((s) => s.appearance);
  const signOut = useAuth((s) => s.signOut);
  const qc = useQueryClient();
  const me = useMe();
  const devices = useQuery({
    queryKey: ['devices'],
    queryFn: async () => (await api.get<Device[]>('/auth/devices')).data,
  });
  const logoutDevice = useMutation({
    mutationFn: (id: number) => api.delete(`/auth/devices/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['devices'] }),
  });

  return (
    <Screen>
      <Card>
        <T variant="heading">Appearance</T>
        <Choice<Appearance>
          value={appearance}
          onChange={setAppearance}
          options={[
            { label: 'Light', value: 'light' },
            { label: 'Dark', value: 'dark' },
            { label: 'System default', value: 'system' },
          ]}
        />
      </Card>

      <Card>
        <T variant="heading">Account</T>
        <T variant="muted">{me.data?.email ?? '…'}</T>
      </Card>

      <ChangePassword />

      {me.data ? <TwoFactor enabled={me.data.totp_enabled} /> : null}

      <Card>
        <T variant="heading">Logged-in devices</T>
        {devices.isError ? <T variant="error">{errorMessage(devices.error)}</T> : null}
        {devices.data?.map((d) => (
          <View
            key={d.id}
            style={{ gap: spacing.xs, paddingBottom: spacing.sm, borderBottomWidth: 1, borderColor: colors.border }}>
            <T>
              {d.name}
              {d.current ? ' (this device)' : ''}
            </T>
            <T variant="muted">Last active {new Date(d.last_seen_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata' })}</T>
            {!d.current ? (
              <Button
                kind="danger"
                title="Log out this device"
                busy={logoutDevice.isPending && logoutDevice.variables === d.id}
                onPress={() => logoutDevice.mutate(d.id)}
              />
            ) : null}
          </View>
        ))}
      </Card>

      <Button kind="secondary" title="Sign out" onPress={signOut} />

      <DeleteAccount />
    </Screen>
  );
}
