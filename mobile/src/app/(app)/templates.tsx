/** Your email template: preview it as HR receives it (parts colour-coded), edit it as plain text with {tags} and a live
 * preview, and keep every version (switch back, or to the approved default, any time). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { StyleSheet, Text, TextInput, View, type TextStyle } from 'react-native';

import { Pill, type Job } from '@/components/chat-cards';
import { Button, Card, Screen, T } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors, type Colors } from '@/theme/use-colors';

type Kind = 'fixed' | 'profile' | 'job' | 'ai';
type Part = { kind: Kind; text: string };
type Parts = { job: { id: number; company: string; role: string } | null; subject: Part[]; body: Part[] };
type Editor = {
  active: string; text: string; default_text: string;
  tags: { tag: string; means: string; ai: boolean }[];
  versions: { id: number; version: number; created_at: string; is_active: boolean }[];
};

function look(c: Colors, kind: Kind): TextStyle {
  if (kind === 'profile') return { backgroundColor: c.primarySoft, color: c.text };
  if (kind === 'job') return { backgroundColor: c.surfaceAlt, color: c.text, fontFamily: fonts.semibold };
  if (kind === 'ai') return { color: c.primaryText, fontStyle: 'italic' };
  return { color: c.text };
}

const LEGEND: [Kind, string, string][] = [
  ['fixed', 'Your wording', 'fixed text; the AI never changes it'],
  ['profile', 'Your profile', 'name, phone, LinkedIn, GitHub (Setup → Profile)'],
  ['job', 'From the job', 'role, company, HR name, a subject the post asks for'],
  ['ai', 'Written by the AI', 'for each job, only from your active resume'],
];

function when(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata' });
}

function Letter({ parts }: { parts: Parts }) {
  const { colors } = useColors();
  const line = (ps: Part[]) => (
    <Text style={[styles.mail, { color: colors.text }]}>
      {ps.map((p, i) => (
        <Text key={i} style={look(colors, p.kind)}>{p.text}</Text>
      ))}
    </Text>
  );
  return (
    <View style={[styles.letter, { backgroundColor: colors.background, borderColor: colors.border }]}>
      <View style={styles.subjectRow}>
        <Text style={[styles.subjectLabel, { color: colors.textMuted }]}>Subject</Text>
        <View style={{ flex: 1 }}>{line(parts.subject)}</View>
      </View>
      <View style={[styles.divider, { backgroundColor: colors.border }]} />
      {line(parts.body)}
    </View>
  );
}

export default function Templates() {
  const { colors } = useColors();
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<number | null>(null);
  const [draft, setDraft] = useState<string | null>(null); // the text being edited; null = not editing
  const [sel, setSel] = useState<{ start: number; end: number } | null>(null); // null: cursor not placed yet
  const [debounced, setDebounced] = useState('');
  const [savedNote, setSavedNote] = useState<string | null>(null);

  const jobs = useQuery({
    queryKey: ['jobs', 'day', 'today'],
    queryFn: async () => (await api.get<Job[]>('/jobs', { params: { date: 'today' } })).data,
  });
  // staleTime 0: always ask the server when the screen opens (a saved copy could show an old active version)
  const editor = useQuery({ queryKey: ['templates'], queryFn: async () => (await api.get<Editor>('/templates')).data, staleTime: 0 });
  const current = useQuery({
    queryKey: ['template', jobId, editor.data?.active],
    queryFn: async () => (await api.get<Parts>('/template', { params: jobId ? { job_id: jobId } : {} })).data,
    enabled: draft === null,
    staleTime: 0,
  });
  useEffect(() => {
    if (draft === null) return;
    const t = setTimeout(() => setDebounced(draft), 450);
    return () => clearTimeout(t);
  }, [draft]);
  const live = useQuery({
    queryKey: ['template-preview', debounced, jobId],
    queryFn: async () => (await api.post<Parts>('/templates/preview', { text: debounced, job_id: jobId })).data,
    enabled: draft !== null && debounced.length > 0,
    retry: false,
  });

  const done = (e: Editor, note: string) => {
    qc.setQueryData(['templates'], e);
    void Promise.all(['template', 'jobs', 'posts'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
    setDraft(null);
    setSavedNote(note);
  };
  const save = useMutation({
    mutationFn: async (text: string) => (await api.post<Editor>('/templates', { text })).data,
    onSuccess: (e) => done(e, `Saved as version ${e.versions[0]?.version}. New emails use it; emails already written show “Rewrite email”.`),
  });
  const useVersion = useMutation({
    mutationFn: async (id: number | 'default') =>
      (await api.post<Editor>(id === 'default' ? '/templates/default' : `/templates/${id}/activate`)).data,
    onSuccess: (e) => done(e, e.active === 'default-v1' ? 'Using the approved default template.' : `Using ${e.active.replace('custom-v', 'version ')}.`),
  });

  const e = editor.data;
  const emailJobs = (jobs.data ?? []).filter((j) => j.apply_method === 'email').slice(0, 6);
  const insert = (tag: string) => {
    if (draft === null) return;
    if (!sel) {
      // no cursor yet: add it at the end, on its own line
      setDraft(`${draft.replace(/\s+$/, '')}\n${tag}`);
      return;
    }
    setDraft(draft.slice(0, sel.start) + tag + draft.slice(sel.end));
    setSel({ start: sel.start + tag.length, end: sel.start + tag.length });
  };
  const shown = draft !== null ? live.data : current.data;
  const liveError = draft !== null && live.error ? errorMessage(live.error) : null;

  return (
    <Screen>
      <Card>
        <T variant="heading">Your email template</T>
        <T variant="muted">
          Every application email uses this template. The AI only writes the highlighted parts, for each job, from your
          resume. Nothing is sent without your approval.
        </T>
        <View style={{ gap: spacing.sm }}>
          {LEGEND.map(([kind, label, what]) => (
            <View key={kind} style={styles.legendRow}>
              <Text style={[styles.swatch, look(colors, kind), kind === 'fixed' && { borderWidth: 1, borderColor: colors.border }]}>{label}</Text>
              <Text style={[styles.legendText, { color: colors.textMuted }]}>{what}</Text>
            </View>
          ))}
        </View>
        {e ? (
          <T variant="muted">
            {e.active === 'default-v1' ? 'Now using: the approved default template.' : `Now using: your ${e.active.replace('custom-v', 'version ')}.`}
          </T>
        ) : null}
        {savedNote ? <T style={{ color: colors.success }}>{savedNote}</T> : null}
        {draft === null && e ? (
          <View style={styles.row}>
            <Pill label="Edit template" primary onPress={() => { save.reset(); setSavedNote(null); setSel(null); setDraft(e.text); setDebounced(e.text); }} />
          </View>
        ) : null}
      </Card>

      {draft !== null && e ? (
        <Card>
          <T variant="heading">Edit</T>
          <T variant="muted">
            First line is the subject. Tap a tag to insert it where the cursor is. Keep the three AI tags: the AI writes
            them from your resume.
          </T>
          <View style={styles.row}>
            {e.tags.map((t) => (
              <Pill key={t.tag} label={t.tag} primary={t.ai} onPress={() => insert(t.tag)} />
            ))}
          </View>
          <View style={{ gap: 2 }}>
            {e.tags.map((t) => (
              <Text key={t.tag} style={[styles.legendText, { color: colors.textMuted }]}>{`${t.tag}: ${t.means}`}</Text>
            ))}
          </View>
          <TextInput
            accessibilityLabel="Email template"
            multiline
            value={draft}
            onChangeText={setDraft}
            onSelectionChange={(ev) => setSel(ev.nativeEvent.selection)}
            autoCapitalize="none"
            autoCorrect={false}
            textAlignVertical="top"
            style={[styles.editor, { color: colors.text, backgroundColor: colors.background, borderColor: liveError ? colors.error : colors.border }]}
          />
          {liveError ? <T variant="error">{liveError}</T> : null}
          {save.error ? <T variant="error">{errorMessage(save.error)}</T> : null}
          <Button title="Save as a new version" busy={save.isPending} disabled={!!liveError || draft.trim() === e.text.trim()} onPress={() => save.mutate(draft)} />
          <View style={styles.row}>
            <Pill label="Start from the default" onPress={() => setDraft(e.default_text)} />
            <Pill label="Cancel" onPress={() => setDraft(null)} />
          </View>
        </Card>
      ) : null}

      <Card>
        <T variant="heading">{draft !== null ? 'Live preview' : 'Preview with'}</T>
        <View style={styles.row}>
          <Pill label="Sample job" primary={jobId === null} onPress={() => setJobId(null)} />
          {emailJobs.map((j) => (
            <Pill key={j.id} label={`${j.company} · ${j.role}`} primary={jobId === j.id} onPress={() => setJobId(j.id)} />
          ))}
        </View>
        {!emailJobs.length && jobs.data ? <T variant="muted">No email jobs today yet; the sample job is shown.</T> : null}
        {current.error && draft === null ? <T variant="error">{errorMessage(current.error)}</T> : null}
        {shown ? <Letter parts={shown} /> : liveError ? null : <T variant="muted">Loading…</T>}
        <T variant="muted">Plus your active resume attached as a PDF.</T>
      </Card>

      {e ? (
        <Card>
          <T variant="heading">Versions</T>
          <View style={[styles.version, { borderColor: colors.border }]}>
            <Text style={[styles.versionText, { color: colors.text }]}>Approved default</Text>
            {e.active === 'default-v1' ? (
              <Text style={[styles.chip, { color: colors.success, borderColor: colors.success }]}>Active</Text>
            ) : (
              <Pill label="Use this" onPress={() => useVersion.mutate('default')} />
            )}
          </View>
          {e.versions.map((v) => (
            <View key={v.id} style={[styles.version, { borderColor: colors.border }]}>
              <Text style={[styles.versionText, { color: colors.text }]}>{`Version ${v.version} · saved ${when(v.created_at)}`}</Text>
              {v.is_active ? (
                <Text style={[styles.chip, { color: colors.success, borderColor: colors.success }]}>Active</Text>
              ) : (
                <Pill label="Use this" busy={useVersion.isPending && useVersion.variables === v.id} onPress={() => useVersion.mutate(v.id)} />
              )}
            </View>
          ))}
          {!e.versions.length ? <T variant="muted">Your saved versions will show here.</T> : null}
          {useVersion.error ? <T variant="error">{errorMessage(useVersion.error)}</T> : null}
        </Card>
      ) : editor.error ? (
        <T variant="error">{errorMessage(editor.error)}</T>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  legendRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' },
  swatch: { fontFamily: fonts.semibold, fontSize: 13, paddingVertical: 2, paddingHorizontal: 8, borderRadius: radius.sm, overflow: 'hidden' },
  legendText: { fontFamily: fonts.body, fontSize: 13, flexShrink: 1 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  letter: { borderWidth: 1, borderRadius: radius.sm, padding: spacing.md, gap: spacing.sm },
  subjectRow: { flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start' },
  subjectLabel: { fontFamily: fonts.semibold, fontSize: 13, paddingTop: 2 },
  divider: { height: 1 },
  mail: { fontFamily: fonts.body, fontSize: 14, lineHeight: 22 },
  editor: { minHeight: 380, borderWidth: 1, borderRadius: radius.sm, padding: spacing.md, fontFamily: fonts.mono, fontSize: 13, lineHeight: 20 },
  version: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm, borderTopWidth: 1, paddingTop: spacing.sm },
  versionText: { fontFamily: fonts.body, fontSize: 14, flexShrink: 1 },
  chip: { fontFamily: fonts.semibold, fontSize: 12, borderWidth: 1, borderRadius: radius.pill, paddingVertical: 3, paddingHorizontal: 10 },
});
