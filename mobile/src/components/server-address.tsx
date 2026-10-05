/** "Server: http://… · Change" under the sign-in form: the same app talks to the laptop now and the Oracle server
 * later, without a new build. A new address is tested (GET /health) before it is saved on this device. */
import axios from 'axios';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { Button, Field, T } from '@/components/ui';
import { API_URL, defaultServer, saveServer } from '@/lib/api';
import { fonts, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

export function ServerAddress() {
  const { colors } = useColors();
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState(API_URL);
  const [shown, setShown] = useState(API_URL);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function save(next: string | null) {
    setError('');
    setBusy(true);
    const candidate = (next || defaultServer()).trim().replace(/\/+$/, '');
    try {
      await axios.get(`${candidate}/health`, { timeout: 8000 });
      await saveServer(next);
      setShown(candidate);
      setOpen(false);
    } catch {
      setError(`No Leapvoy server answered at ${candidate}. Check the address (and that Tailscale is on).`);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <Pressable accessibilityRole="button" onPress={() => setOpen(true)} style={{ alignItems: 'center' }}>
        <Text style={{ fontFamily: fonts.body, fontSize: 12, color: colors.textMuted }}>
          {`Server: ${shown} · `}
          <Text style={{ color: colors.primaryText, fontFamily: fonts.semibold }}>Change</Text>
        </Text>
      </Pressable>
    );
  }
  return (
    <View style={{ gap: spacing.sm }}>
      <Field
        label="Leapvoy server address"
        value={url}
        onChangeText={setUrl}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        placeholder="https://leapvoy.your-tailnet.ts.net/api"
      />
      <T variant="muted">{"The server's address ends in /api (or :8000 for a laptop on the same Wi-Fi or hotspot)."}</T>
      {error ? <T variant="error">{error}</T> : null}
      <View style={{ flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' }}>
        <Button title="Test and save" busy={busy} disabled={!url.trim()} onPress={() => save(url)} />
        <Button kind="secondary" title="Back to the default" onPress={() => save(null)} />
        <Button kind="secondary" title="Cancel" onPress={() => setOpen(false)} />
      </View>
    </View>
  );
}
