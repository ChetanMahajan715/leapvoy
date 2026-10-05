/** Resumes: upload a new version (PDF; scanned ones are read with OCR), switch back to an older one, delete old ones.
 * The active one is used to match jobs and is attached to every email. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, FileUp, TriangleAlert } from 'lucide-react-native';
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Pill } from '@/components/chat-cards';
import { Sheet } from '@/components/sheet';
import { Button, Card, Field, Screen, T } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { pickFile } from '@/lib/attach';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

type Resume = {
  id: number; name: string; filename: string | null; is_active: boolean; created_at: string; chars: number; drafts: number;
};
type Uploaded = { resume: Resume; warnings: string[]; outdated_drafts: number };
type Picked = { name: string; base64: string };

const MAX_MB = 5;

function uploadedOn(iso: string): string {
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' });
}

export default function Resumes() {
  const { colors } = useColors();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['resumes'], queryFn: async () => (await api.get<Resume[]>('/resumes')).data });
  const [file, setFile] = useState<Picked | null>(null);
  const [name, setName] = useState('');
  const [done, setDone] = useState<Uploaded | null>(null);
  const [pickError, setPickError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Resume | null>(null);
  // a new active resume changes matches and makes older drafts outdated
  const refresh = () => Promise.all(['resumes', 'jobs', 'posts'].map((k) => qc.invalidateQueries({ queryKey: [k] })));

  const upload = useMutation({
    mutationFn: async (f: Picked) =>
      (await api.post<Uploaded>('/resumes', { name: name.trim(), filename: f.name, data: f.base64 }, { timeout: 120_000 })).data,
    onSuccess: (u) => {
      setDone(u);
      setFile(null);
      void refresh();
    },
  });
  const activate = useMutation({
    mutationFn: (id: number) => api.post(`/resumes/${id}/activate`),
    onSuccess: () => {
      setDone(null);
      void refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/resumes/${id}`),
    onSuccess: () => {
      setDeleting(null);
      void refresh();
    },
  });

  const choose = async () => {
    setPickError(null);
    try {
      const f = await pickFile(['application/pdf'], MAX_MB);
      if (!f) return;
      if (!/\.pdf$/i.test(f.name)) throw new Error('Choose a PDF file.');
      upload.reset();
      setName(f.name.replace(/\.pdf$/i, ''));
      setFile(f);
    } catch (e) {
      setPickError(errorMessage(e));
    }
  };

  return (
    <Screen>
      <Card>
        <T variant="heading">Your resume</T>
        <T variant="muted">
          Leapvoy matches jobs against your active resume and attaches its PDF to every email. Older versions are kept, so
          you can switch back.
        </T>
        <View style={styles.uploadRow}>
          <Pill label="Upload new resume (PDF)" icon={FileUp} primary onPress={choose} />
          <T variant="muted">Up to {MAX_MB} MB · scanned PDFs work too</T>
        </View>
        {pickError ? <T variant="error">{pickError}</T> : null}
        {done ? (
          <View style={[styles.note, { backgroundColor: colors.background, borderColor: colors.border }]}>
            <View style={styles.line}>
              <CheckCircle2 size={16} color={colors.success} strokeWidth={2} />
              <Text style={[styles.noteText, { color: colors.text }]}>“{done.resume.name}” is now your active resume.</Text>
            </View>
            {done.warnings.map((w) => (
              <View key={w} style={styles.line}>
                <TriangleAlert size={16} color={colors.warning} strokeWidth={2} />
                <Text style={[styles.noteText, { color: colors.text }]}>{w}</Text>
              </View>
            ))}
            {done.outdated_drafts ? (
              <T variant="muted">
                {done.outdated_drafts} email draft{done.outdated_drafts === 1 ? ' was' : 's were'} written from an older resume;
                they now show “Rewrite email”.
              </T>
            ) : null}
          </View>
        ) : null}
      </Card>

      {q.error ? <T variant="error">{errorMessage(q.error)}</T> : null}
      {q.data && !q.data.length ? <T variant="muted">No resume yet. Upload one to start matching jobs.</T> : null}
      {q.data?.map((r) => (
        <Card key={r.id}>
          <View style={styles.head}>
            <Text numberOfLines={2} style={[styles.name, { color: colors.text }]}>{r.name}</Text>
            {r.is_active ? (
              <View style={[styles.chip, { borderColor: colors.success }]}>
                <Text style={[styles.chipText, { color: colors.success }]}>Active</Text>
              </View>
            ) : null}
          </View>
          <T variant="muted">
            {[r.filename, `uploaded ${uploadedOn(r.created_at)}`, `${r.chars.toLocaleString('en-IN')} characters`,
              `${r.drafts} email${r.drafts === 1 ? '' : 's'} written`].filter(Boolean).join(' · ')}
          </T>
          {!r.is_active ? (
            <View style={styles.uploadRow}>
              <Pill
                label="Make active"
                primary
                busy={activate.isPending && activate.variables === r.id}
                onPress={() => activate.mutate(r.id)}
              />
              <Pill label="Delete" onPress={() => { remove.reset(); setDeleting(r); }} />
            </View>
          ) : null}
        </Card>
      ))}
      {activate.error ? <T variant="error">{errorMessage(activate.error)}</T> : null}

      <Sheet open={!!file} title="Name this resume" onClose={() => setFile(null)}>
        <View style={{ gap: spacing.md }}>
          <Field label="Name" value={name} onChangeText={setName} autoCapitalize="words" placeholder="e.g. AI Engineer, Oct 2026" />
          <T variant="muted">{file?.name}</T>
          {upload.isPending ? <T variant="muted">Reading your resume… (a scanned PDF takes a little longer)</T> : null}
          {upload.error ? <T variant="error">{errorMessage(upload.error)}</T> : null}
          <Button title="Upload and make active" busy={upload.isPending} disabled={!name.trim()} onPress={() => file && upload.mutate(file)} />
        </View>
      </Sheet>
      <Sheet open={!!deleting} title="Delete this resume?" onClose={() => setDeleting(null)}>
        <View style={{ gap: spacing.md }}>
          <T>“{deleting?.name}” and the email drafts written from it will be removed. Emails already sent are not affected.</T>
          {remove.error ? <T variant="error">{errorMessage(remove.error)}</T> : null}
          <Button kind="danger" title="Delete" busy={remove.isPending} onPress={() => deleting && remove.mutate(deleting.id)} />
          <Button kind="secondary" title="Cancel" onPress={() => setDeleting(null)} />
        </View>
      </Sheet>
    </Screen>
  );
}

const styles = StyleSheet.create({
  uploadRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.sm },
  note: { borderWidth: 1, borderRadius: radius.sm, padding: spacing.md, gap: spacing.xs },
  line: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm },
  noteText: { fontFamily: fonts.body, fontSize: 14, lineHeight: 20, flexShrink: 1 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  name: { fontFamily: fonts.semibold, fontSize: 17, flexShrink: 1 },
  chip: { borderWidth: 1, borderRadius: radius.pill, paddingVertical: 3, paddingHorizontal: 10 },
  chipText: { fontFamily: fonts.semibold, fontSize: 12 },
});
