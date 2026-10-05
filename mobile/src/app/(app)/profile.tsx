/** Your profile: what every email ends with (GitHub, LinkedIn, name, phone) and facts the AI uses (education,
 * home city, availability). Mistakes show under their field. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { useState } from 'react';
import { View } from 'react-native';

import { Button, Card, Field, Screen, T } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

type Key = 'full_name' | 'phone' | 'linkedin_url' | 'github_url' | 'sender_email' | 'education' | 'home_city' | 'availability';
type Profile = Record<Key, string>;

const FIELDS: { key: Key; label: string; help: string; placeholder: string; words?: boolean; kind?: 'phone-pad' | 'email-address' | 'url' }[] = [
  { key: 'full_name', label: 'Full name', help: 'Signs every email.', placeholder: 'Your full name', words: true },
  { key: 'phone', label: 'Phone', help: 'Under your name in every email.', placeholder: 'e.g. +91 98765 43210', kind: 'phone-pad' },
  { key: 'linkedin_url', label: 'LinkedIn', help: 'Linked in every email.', placeholder: 'https://linkedin.com/in/your-name', kind: 'url' },
  { key: 'github_url', label: 'GitHub', help: 'Linked in every email.', placeholder: 'https://github.com/your-name', kind: 'url' },
  { key: 'sender_email', label: 'Email you send from', help: 'Checked against the email on your resume.', placeholder: 'e.g. you@gmail.com', kind: 'email-address' },
  { key: 'education', label: 'Education', help: 'The AI mentions it when a job asks.', placeholder: 'e.g. B.Tech CSE, 2025', words: true },
  { key: 'home_city', label: 'Home city', help: 'Jobs in other cities get a “relocation” note.', placeholder: 'e.g. Pune', words: true },
  { key: 'availability', label: 'Availability', help: 'Used when a job asks when you can join.', placeholder: 'e.g. Can join immediately' },
];

/** 422 → { field: message } so each mistake shows under its own field. */
function fieldErrors(e: unknown): Partial<Record<Key, string>> {
  if (!isAxiosError(e) || e.response?.status !== 422) return {};
  const detail = (e.response.data as { detail?: { loc: (string | number)[]; msg: string }[] }).detail;
  if (!Array.isArray(detail)) return {};
  return Object.fromEntries(detail.map((d) => [String(d.loc[d.loc.length - 1]), d.msg.replace(/^Value error, /, '')]));
}

export default function ProfileScreen() {
  const q = useQuery({ queryKey: ['profile'], queryFn: async () => (await api.get<Profile>('/profile')).data });
  if (!q.data) {
    return <Screen>{q.error ? <T variant="error">{errorMessage(q.error)}</T> : <T variant="muted">Loading…</T>}</Screen>;
  }
  return <ProfileForm initial={q.data} />;
}

function ProfileForm({ initial }: { initial: Profile }) {
  const { colors } = useColors();
  const qc = useQueryClient();
  const [form, setForm] = useState<Profile>(initial);
  const [saved, setSaved] = useState(false);
  const save = useMutation({
    mutationFn: async (p: Profile) => (await api.put<Profile>('/profile', p)).data,
    onSuccess: (p) => {
      qc.setQueryData(['profile'], p);
      setForm(p);
      setSaved(true);
    },
  });

  const errors = fieldErrors(save.error);
  const change = (k: Key) => (v: string) => {
    setSaved(false);
    setForm({ ...form, [k]: v });
  };

  return (
    <Screen>
      <Card>
        <T variant="heading">Your profile</T>
        <T variant="muted">Leapvoy uses this in every email it writes for you.</T>
        {FIELDS.map((f) => (
          <View key={f.key} style={{ gap: 4 }}>
            <Field
              label={f.label}
              value={form[f.key]}
              onChangeText={change(f.key)}
              placeholder={f.placeholder}
              keyboardType={f.kind ?? 'default'}
              autoCapitalize={f.words ? 'words' : 'none'}
            />
            {errors[f.key] ? <T variant="error">{errors[f.key]}</T> : <T variant="muted">{f.help}</T>}
          </View>
        ))}
        {save.error && !Object.keys(errors).length ? <T variant="error">{errorMessage(save.error)}</T> : null}
        {Object.keys(errors).length ? <T variant="error">Fix the fields marked above, then save again.</T> : null}
        {saved ? <T style={{ color: colors.success }}>Saved. New emails use this.</T> : null}
        <Button title="Save" busy={save.isPending} onPress={() => save.mutate(form)} />
      </Card>

      <Card>
        <T variant="heading">Every email ends with</T>
        <View style={{ gap: 2, padding: spacing.md, borderRadius: radius.sm, backgroundColor: colors.background }}>
          <T style={{ fontFamily: fonts.body }}>GitHub: {form.github_url || 'not set'}</T>
          <T style={{ fontFamily: fonts.body }}>LinkedIn: {form.linkedin_url || 'not set'}</T>
          <T variant="muted" style={{ marginVertical: spacing.sm }}>
            I have attached my resume and look forward to hearing from you.
          </T>
          <T>Best regards,</T>
          <T>{form.full_name || 'Your name'}</T>
          <T>{form.phone || 'Your phone'}</T>
        </View>
      </Card>
    </Screen>
  );
}
