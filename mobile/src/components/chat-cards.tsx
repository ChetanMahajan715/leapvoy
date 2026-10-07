/** Cards inside chat replies: jobs (fit, email, send), Telegram posts, a job's email, Confirm proposals, scheduled emails. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Check,
  Clock,
  ExternalLink,
  FileText,
  Info,
  Link2,
  Mail,
  PenLine,
  Pencil,
  RefreshCw,
  Send as SendIcon,
  TriangleAlert,
  X,
} from 'lucide-react-native';
import { useState, type ReactNode } from 'react';
import { ActivityIndicator, Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { Pressy, ShimmerList } from '@/components/motion';
import { ScheduleSheet, type Choice } from '@/components/schedule-sheet';
import { Field } from '@/components/ui';
import { api, confirmNotes, errorMessage } from '@/lib/api';
import { useMe } from '@/lib/auth';
import { haptic } from '@/lib/haptics';
import { writeAndSchedule, type BulkResult, type Progress } from '@/lib/bulk';
import { useModels, usePicks } from '@/lib/models';
import type { Card } from '@/lib/chat-events';
import { istDay, istToday } from '@/lib/days';
import { verdictLabel } from '@/lib/labels';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors, type Colors } from '@/theme/use-colors';

export type Send = {
  id: number; job_id: number; to_email: string; to_emails?: string[]; status: string; send_at: string; sent_at: string | null;
  replied_at: string | null; test_mode: boolean; error: string | null; company?: string; role?: string;
  subject?: string; reply_snippet?: string | null;
};
type Draft = { status: string; subject: string; body: string; to_emails: string[]; issues: string[]; outdated: boolean;
  outdated_reason?: 'resume' | 'template' | null; edited?: boolean };
export type Job = {
  id: number; company: string; role: string; location: string | null; work_mode: string; experience: string | null;
  fit_score: number | null; verdict: string | null; flags: string[]; matched_skills: string[]; gaps: string[];
  apply_method: 'email' | 'link'; apply_links: string[]; draft: Draft | null; send: Send | null;
  salary: string | null; hr_emails: string[]; must_have_skills: string[]; apply_instructions: string | null;
  hr_name: string | null; post_text: string | null; posted_at: string | null;
  checked_with: string | null; // the resume that scored this job
};
/** One Telegram post as it was posted, plus what Leapvoy did with it (GET /posts). */
export type PostInfo = {
  id: number; tg_message_id: number; posted_at: string; channel: string; title: string; text: string;
  kind: 'fit' | 'pending' | 'skipped' | 'failed'; status: string; job_ids: number[]; has_email: boolean; has_link: boolean;
  emails: string[]; links: string[]; jobs: Job[];
};
type Action = { id: number; summary: string; status: 'pending' | 'done' | 'dismissed' | 'failed'; result: string | null };

const SHOWN = 3; // jobs shown before "Show N more"

export function when(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}

export function ChatCard({ card }: { card: Card }) {
  switch (card.type) {
    case 'jobs':
      return <JobsCard ids={card.job_ids} />;
    case 'draft':
      return <DraftCard jobId={card.job_id} />;
    case 'confirm':
      return <ConfirmCard actionId={card.action_id} />;
    case 'sends':
      return <SendsCard ids={card.send_ids} />;
    case 'posts':
      return <PostsCard ids={card.post_ids} />;
    default:
      return null;
  }
}

export function useRefresh() {
  const qc = useQueryClient();
  return () =>
    Promise.all(['jobs', 'sends', 'posts'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
}

/** Ticked job ids (for "Write & schedule N emails"). */
export function usePicked() {
  const [picked, setPicked] = useState<number[]>([]);
  const toggle = (id: number) => {
    haptic.select();
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  };
  return { picked, setPicked, toggle };
}

/** "Tick jobs…" / "3 selected" + Select all / Clear, the same in chat, Recommended and All posts. */
export function SelectBar({ jobs, picked, onPick }: { jobs: Job[]; picked: number[]; onPick: (ids: number[]) => void }) {
  const selectable = jobs.filter(canEmail).map((j) => j.id);
  if (selectable.length < 2) return null;
  return (
    <View style={styles.spread}>
      <Small>{picked.length ? `${picked.length} selected` : 'Tick jobs to write & schedule them together'}</Small>
      {picked.length < selectable.length ? (
        <Pill label={`Select all ${selectable.length}`} onPress={() => onPick(selectable)} />
      ) : (
        <Pill label="Clear" onPress={() => onPick([])} />
      )}
    </View>
  );
}

/** A job card with a tick box when it can still get an email. */
export function JobItem({ job, picked, onToggle }: { job: Job; picked: number[]; onToggle: (id: number) => void }) {
  return canEmail(job) ? (
    <JobCard job={job} selected={picked.includes(job.id)} onSelect={() => onToggle(job.id)} />
  ) : (
    <JobCard job={job} />
  );
}

/** Jobs in a chat reply: same cards as the Jobs page, tick several (or Select all) → Write & schedule in one go. */
function JobsCard({ ids }: { ids: number[] }) {
  const [all, setAll] = useState(false);
  const { picked, setPicked, toggle } = usePicked();
  const q = useQuery({
    queryKey: ['jobs', 'ids', ids.join(',')],
    queryFn: async () => (await api.get<Job[]>('/jobs', { params: { ids: ids.join(',') } })).data,
  });
  if (!q.data) return <Loading error={q.error} />;
  return (
    <View style={{ gap: spacing.sm }}>
      <SelectBar jobs={q.data} picked={picked} onPick={setPicked} />
      {(all ? q.data : q.data.slice(0, SHOWN)).map((j) => (
        <JobItem key={j.id} job={j} picked={picked} onToggle={toggle} />
      ))}
      {q.data.length > SHOWN ? (
        <Pill label={all ? 'Show fewer' : `Show ${q.data.length - SHOWN} more`} onPress={() => setAll(!all)} />
      ) : null}
      {picked.length ? (
        <BulkBar inline jobs={q.data.filter((j) => picked.includes(j.id))} onDone={() => setPicked([])} />
      ) : null}
    </View>
  );
}

/** Posts in a chat reply (all posts of a day, or search results): same cards and selection as the Jobs page. */
function PostsCard({ ids }: { ids: number[] }) {
  const [all, setAll] = useState(false);
  const { picked, setPicked, toggle } = usePicked();
  const q = useQuery({
    queryKey: ['posts', 'ids', ids.join(',')],
    queryFn: async () => (await api.get<PostInfo[]>('/posts', { params: { ids: ids.join(',') } })).data,
  });
  if (!q.data) return <Loading error={q.error} />;
  const jobs = q.data.flatMap((p) => p.jobs);
  return (
    <View style={{ gap: spacing.sm }}>
      <SelectBar jobs={jobs} picked={picked} onPick={setPicked} />
      {(all ? q.data : q.data.slice(0, SHOWN)).map((p) => (
        <PostItem key={p.id} post={p} picked={picked} onToggle={toggle} />
      ))}
      {q.data.length > SHOWN ? (
        <Pill label={all ? 'Show fewer' : `Show ${q.data.length - SHOWN} more`} onPress={() => setAll(!all)} />
      ) : null}
      {picked.length ? <BulkBar inline jobs={jobs.filter((j) => picked.includes(j.id))} onDone={() => setPicked([])} /> : null}
    </View>
  );
}

/** How a post can be applied to: its jobs' way, else what the post itself contains. */
export function postMethod(p: PostInfo): 'email' | 'link' | 'none' {
  if (p.jobs.length) return p.jobs.some((j) => j.apply_method === 'email') ? 'email' : 'link';
  return p.has_email ? 'email' : p.has_link ? 'link' : 'none';
}

const URL_RE = /(https?:\/\/[^\s]+)/g;

/** Post text with tappable links, like Telegram (not `selectable`: on Android that blocks taps on the links). */
function PostText({ text }: { text: string }) {
  const { colors } = useColors();
  return (
    <Text style={[styles.body, { color: colors.text }]}>
      {text.split(URL_RE).map((part, i) =>
        i % 2 ? (
          <Text key={i} style={{ color: colors.primaryText, textDecorationLine: 'underline' }} onPress={() => Linking.openURL(part)}>
            {part}
          </Text>
        ) : (
          part
        ),
      )}
    </Text>
  );
}

/** One Telegram post: its job card(s), same as Recommended, or, when there is no job, a short card saying why. */
export function PostItem({ post, picked, onToggle }: { post: PostInfo; picked: number[]; onToggle: (id: number) => void }) {
  const { colors } = useColors();
  if (post.jobs.length === 1) return <JobItem job={post.jobs[0]} picked={picked} onToggle={onToggle} />;
  if (post.jobs.length) {
    return (
      <View style={{ gap: spacing.sm }}>
        <Text style={[styles.time, { color: colors.textMuted, paddingHorizontal: spacing.xs }]}>
          {`From one post · ${postedWhen(post.posted_at).replace('Posted ', '')} · ${post.jobs.length} jobs`}
        </Text>
        {post.jobs.map((j) => (
          <JobItem key={j.id} job={j} picked={picked} onToggle={onToggle} />
        ))}
      </View>
    );
  }
  return <PostOnlyCard post={post} />;
}

/** While a day has waiting posts, ask the server to check them, again and again until none wait (no 'Check now').
 * Waiting cards and the Jobs screen share this query per day, so the server gets one request per day at a time. */
export function useAutoCheck(day: string, waiting: boolean): 'checking' | 'paused' | null {
  const refresh = useRefresh();
  const q = useQuery({
    queryKey: ['check-day', day],
    queryFn: async () => {
      const r = (await api.post<{ checked: number; waiting: number; paused: boolean }>('/posts/check-day', { date: day }, { timeout: 120_000 })).data;
      await refresh(); // results appear on their own
      return r;
    },
    enabled: waiting,
    staleTime: 0,
    retry: false,
    refetchInterval: (query) => (query.state.data?.paused || query.state.error ? 60_000 : 5_000),
  });
  if (!waiting) return null;
  return q.data?.paused && !q.isFetching ? 'paused' : 'checking';
}

/** A post without a job card: same layout as a job: what it is, when, why (no score), how to apply, the post on tap.
 * Waiting posts are checked by themselves (useAutoCheck); only a failed post gets "Check again". Any post with an HR email gets
 * "Write email" even when skipped (weak match…): the AI reads it anyway, then writes the email → Send now / Schedule. */
function PostOnlyCard({ post }: { post: PostInfo }) {
  const { colors } = useColors();
  const refresh = useRefresh();
  const [open, setOpen] = useState(false);
  const check = useMutation({
    mutationFn: () => api.post(`/posts/${post.id}/check`, {}, { timeout: 180_000 }),
    onSuccess: () => refresh(),
  });
  const write = useMutation({
    mutationFn: async () => {
      const read = await api.post<PostInfo>(`/posts/${post.id}/check`, { force: true }, { timeout: 180_000 });
      const job = read.data.jobs.find((j) => j.apply_method === 'email');
      if (!job) throw new Error('The AI found no job with an email address in this post. Use the apply link or the post.');
      if (!job.draft) await api.post(`/jobs/${job.id}/draft`, { model: usePicks.getState().email }, { timeout: 180_000 });
    },
    onSuccess: () => refresh(), // on error this card stays, showing why (tapping again won't re-read the post)
  });
  const auto = useAutoCheck(istDay(post.posted_at), post.kind === 'pending');
  const busy = check.isPending || write.isPending;
  const tone = post.kind === 'failed' ? colors.error : auto === 'checking' ? colors.primary : colors.textMuted;
  const link = post.links[0];
  return (
    <View style={[styles.card, { backgroundColor: colors.glass, borderColor: colors.glassBorder, boxShadow: colors.cardShadow }]}>
      <View style={styles.titleRow}>
        <Text numberOfLines={2} style={[styles.title, { color: colors.text, flex: 1 }]}>{post.title}</Text>
        <Text style={[styles.time, { color: colors.textMuted }]}>{postedWhen(post.posted_at)}</Text>
      </View>
      <View style={[styles.status, { borderColor: tone }]}>
        {auto === 'checking' ? <ActivityIndicator size="small" color={tone} /> : <View style={[styles.dot, { backgroundColor: tone }]} />}
        <Text style={[styles.statusText, { color: tone }]}>
          {auto === 'checking' ? 'Checking with AI…' : auto === 'paused' ? 'Free AI used up for now, checks itself when it refills' : post.status}
        </Text>
      </View>
      {post.emails.length || link ? (
        <View style={[styles.apply, { backgroundColor: colors.background }]}>
          {post.emails.length ? <Meta icon={Mail}>{post.emails.join(', ')}</Meta> : null}
          {link ? <Meta icon={Link2}>Apply on {linkName(link)}</Meta> : null}
        </View>
      ) : null}
      {open ? (
        <View style={[styles.panel, { backgroundColor: colors.background, borderColor: colors.border }]}>
          <PanelHead icon={FileText} title="Original post" onClose={() => setOpen(false)} />
          <PostText text={post.text} />
        </View>
      ) : null}
      <View style={[styles.actions, { borderTopColor: colors.border }]}>
        <View style={styles.row}>
          {post.emails.length ? (
            <Pill label="Write email" icon={PenLine} primary busy={write.isPending} onPress={() => !busy && write.mutate()} />
          ) : null}
          {link ? (
            <Pill label="Open apply link" icon={ExternalLink} primary={!post.emails.length} onPress={() => Linking.openURL(link)} />
          ) : null}
          {post.kind === 'failed' ? (
            <Pill
              label="Check again"
              icon={RefreshCw}
              busy={check.isPending}
              onPress={() => !busy && check.mutate()}
            />
          ) : null}
        </View>
        <Toggle icon={FileText} label="Post" on={open} onPress={() => setOpen(!open)} />
      </View>
      {write.isPending ? <Small>Reading the post and writing your email. This can take a minute…</Small> : null}
      {check.error || write.error ? <Small color={colors.error}>{errorMessage(check.error ?? write.error)}</Small> : null}
    </View>
  );
}

export function DraftCard({ jobId }: { jobId: number }) {
  const q = useQuery({ queryKey: ['jobs', 'one', jobId], queryFn: async () => (await api.get<Job>(`/jobs/${jobId}`)).data });
  return q.data ? <JobCard job={q.data} emailOpen /> : <Loading error={q.error} />;
}

function fitColor(c: Colors, score: number | null) {
  return score === null ? c.textMuted : score >= 70 ? c.success : score >= 50 ? c.warning : c.textMuted;
}

export function sendStatus(s: Send): string {
  const test = s.test_mode ? ' · TEST (to your own inbox)' : '';
  if (s.replied_at) return `Replied ${when(s.replied_at)}`;
  if (s.status === 'scheduled') return `Scheduled for ${when(s.send_at)}${test}`;
  if (s.status === 'sent' && s.sent_at) return `Sent ${when(s.sent_at)}${test}`;
  if (s.status === 'failed') return `Failed: ${s.error ?? 'unknown error'}`;
  return s.status === 'cancelled' ? 'Cancelled' : s.status;
}

/** Small icon + text line (location, batch, salary, how to apply). */
function Meta({ icon: Icon, children, color }: { icon: typeof Check; children: ReactNode; color?: string }) {
  const { colors } = useColors();
  return (
    <View style={styles.meta}>
      <Icon size={14} color={color ?? colors.textMuted} strokeWidth={2} />
      <Text selectable style={[styles.small, { color: color ?? colors.text, flexShrink: 1 }]}>
        {children}
      </Text>
    </View>
  );
}

function Tag({ text, tone }: { text: string; tone: 'plain' | 'good' | 'gap' }) {
  const { colors } = useColors();
  const fg = tone === 'good' ? colors.success : tone === 'gap' ? colors.textMuted : colors.text;
  return (
    <View style={[styles.tag, { borderColor: tone === 'plain' ? colors.border : fg, backgroundColor: colors.background }]}>
      <Text style={[styles.tagText, { color: fg }]}>{tone === 'good' ? `✓ ${text}` : text}</Text>
    </View>
  );
}

/** Small outlined toggle with an icon (Email / Post). */
function Toggle({ icon: Icon, label, on, onPress }: { icon: typeof Check; label: string; on: boolean; onPress: () => void }) {
  const { colors } = useColors();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ expanded: on }}
      accessibilityLabel={`${on ? 'Hide' : 'Show'} ${label.toLowerCase()}`}
      onPress={onPress}
      hitSlop={4}
      style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [
        styles.toggle,
        { borderColor: on ? colors.primary : colors.border, backgroundColor: on ? colors.primarySoft : pressed || hovered ? colors.surfaceAlt : undefined },
      ]}>
      <Icon size={14} color={on ? colors.primaryText : colors.textMuted} strokeWidth={2} />
      <Text style={[styles.toggleText, { color: on ? colors.primaryText : colors.textMuted }]}>{label}</Text>
    </Pressable>
  );
}

/** Title bar of an opened section (original post / email) with ✕ right at its top, no scrolling down to close. */
function PanelHead({ icon: Icon, title, onClose }: { icon: typeof Check; title: string; onClose: () => void }) {
  const { colors } = useColors();
  return (
    <View style={[styles.panelHead, { borderBottomColor: colors.border }]}>
      <View style={styles.meta}>
        <Icon size={14} color={colors.primaryText} strokeWidth={2} />
        <Text style={[styles.subject, { color: colors.text }]}>{title}</Text>
      </View>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Close ${title.toLowerCase()}`}
        onPress={onClose}
        hitSlop={8}
        style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [
          styles.close,
          { backgroundColor: pressed || hovered ? colors.surfaceAlt : undefined },
        ]}>
        <X size={16} color={colors.textMuted} strokeWidth={2.2} />
      </Pressable>
    </View>
  );
}

/** Can this job get an email now (email job, nothing scheduled/sent yet)? Used by multi-select too. */
export function canEmail(job: Job): boolean {
  return job.apply_method === 'email' && !(job.send && ['scheduled', 'sending', 'sent'].includes(job.send.status));
}

/** "2 Oct, 2:06 pm" (India time). */
function shortWhen(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata' });
}

/** "Posted 3:11 pm" today, "Posted 2 Oct, 3:11 pm" on other days (India time): when the original post went up. */
function postedWhen(iso: string): string {
  const time = new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata' });
  return istDay(iso) === istToday() ? `Posted ${time}` : `Posted ${shortWhen(iso)}`;
}

/** Batch / Salary / Apply as aligned rows in a soft inset box. */
function FactRows({ rows }: { rows: [string, ReactNode][] }) {
  const { colors } = useColors();
  if (!rows.length) return null;
  return (
    <View style={[styles.factBox, { backgroundColor: colors.inset }]}>
      {rows.map(([label, value]) => (
        <View key={label} style={styles.factRow}>
          <Text style={[styles.factLabel, { color: colors.textMuted }]}>{label}</Text>
          <View style={{ flex: 1 }}>{typeof value === 'string' ? <Text selectable style={[styles.small, { color: colors.text }]}>{value}</Text> : value}</View>
        </View>
      ))}
    </View>
  );
}

/** "Google Form" / "careers.acme.com", what an apply link is, at a glance. */
function linkName(url: string): string {
  if (/forms\.gle|docs\.google\.com\/forms/.test(url)) return 'Google Form';
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return 'Apply link';
  }
}

/** Fit at a glance: "92 · Excellent fit", coloured by score. */
function FitPill({ score, verdict }: { score: number | null; verdict: string | null }) {
  const { colors } = useColors();
  const c = fitColor(colors, score);
  return (
    <View style={[styles.fitPill, { borderColor: c, backgroundColor: c === colors.success ? colors.successSoft : c === colors.warning ? colors.warningSoft : colors.inset }]}>
      <Text style={[styles.fitPillScore, { color: c }]}>{score ?? '–'}</Text>
      {verdict ? <Text style={[styles.fitPillText, { color: c }]}>{verdictLabel(verdict)}</Text> : null}
    </View>
  );
}

/** Small heading inside Details. */
function Section({ title, children }: { title: string; children: ReactNode }) {
  const { colors } = useColors();
  return (
    <View style={{ gap: 6 }}>
      <Text style={[styles.sectionTitle, { color: colors.textMuted }]}>{title}</Text>
      {children}
    </View>
  );
}

/** Tick box used on cards (select job) and in Details (which HR addresses). */
function TickBox({ on, big }: { on: boolean; big?: boolean }) {
  const { colors } = useColors();
  return (
    <View style={[styles.box, big && styles.bigBox, { borderColor: colors.primary, backgroundColor: on ? colors.primary : undefined }]}>
      {on ? <Check size={big ? 14 : 12} color={colors.onPrimary} strokeWidth={3} /> : null}
    </View>
  );
}

/** One job, easy to scan: role · company · time, fit, key facts, how to apply, one main button.
 * Why it fits, requirements and which HR addresses sit behind Details; the email and the original post behind their buttons. */
export function JobCard({
  job,
  emailOpen,
  selected,
  onSelect,
}: {
  job: Job;
  emailOpen?: boolean;
  /** Multi-select: shows a tick box when given. */
  selected?: boolean;
  onSelect?: () => void;
}) {
  const { colors } = useColors();
  const refresh = useRefresh();
  const testMode = useMe().data?.test_mode ?? true; // unknown yet → assume the safe default
  const [open, setOpen] = useState<'details' | 'email' | 'post' | null>(emailOpen ? 'email' : null);
  const [scheduling, setScheduling] = useState(false);
  const [ask, setAsk] = useState<Choice | null>(null);
  const d = job.draft;
  const all = d?.to_emails ?? job.hr_emails;
  const [chosen, setChosen] = useState<string[]>(all); // which addresses get the email (all, together)
  const [notes, setNotes] = useState<string[] | null>(null); // "you emailed this address 3 days ago"…: send anyway?
  const [editing, setEditing] = useState(false); // pencil icon: the user writes the email themselves
  const [subject, setSubject] = useState('');
  const [text, setText] = useState('');
  const write = useMutation({
    mutationFn: () => // the AI writes it (with the "Write emails with" pick): can take a while
      api.post(`/jobs/${job.id}/draft`, { model: usePicks.getState().email }, { timeout: 180_000 }),
    onSuccess: () => refresh().then(() => setOpen('email')),
  });
  const schedule = useMutation({
    mutationFn: ({ when: w, confirm }: { when: string; confirm?: boolean }) =>
      api.post(`/jobs/${job.id}/schedule`, { when: w, to: chosen, confirm: !!confirm }),
    onSuccess: () => {
      haptic.sent();
      setNotes(null);
      return refresh().then(() => setAsk(null));
    },
    onError: (e) => setNotes(confirmNotes(e)), // warnings, not errors: shown with "Send anyway"
  });
  const save = useMutation({
    mutationFn: () => api.put(`/jobs/${job.id}/draft`, { subject, body: text }),
    onSuccess: () => refresh().then(() => setEditing(false)),
  });

  const s = job.send;
  const waiting = !!s && ['scheduled', 'sending'].includes(s.status); // change it (edit / move), don't queue another
  const delivered = !!s && ['sent', 'unknown'].includes(s.status);
  const active = waiting || delivered; // the addresses it went (or goes) to are shown
  const canSend = d && d.status !== 'needs_review' && !d.outdated && !waiting && chosen.length > 0;
  // after a test: "Send to company" (test mode off) or "Send test again"; after a real email: "Resend"
  const sendLabel = s?.status === 'failed' ? 'Try again'
    : !delivered ? 'Send now'
    : s?.test_mode ? (testMode ? 'Send test again' : 'Send to company')
    : 'Resend';
  const startEdit = () => {
    if (!d) return;
    setSubject(d.subject);
    setText(d.body);
    setEditing(true);
  };
  const where = [job.company, job.location, job.work_mode !== 'unknown' ? job.work_mode : null].filter(Boolean).join(' · ');
  const toggleTo = (e: string) => setChosen(chosen.includes(e) ? chosen.filter((x) => x !== e) : [...chosen, e]);
  const flip = (k: 'details' | 'email' | 'post') => setOpen(open === k ? null : k);
  const error = write.error ?? save.error ?? (notes ? null : schedule.error);
  const link = job.apply_links[0];
  const emailState = !d ? 'Email not written yet' : d.outdated ? (d.outdated_reason === 'template' ? 'Template changed, rewrite it' : 'Old resume, rewrite it') : d.status === 'needs_review' ? 'Email needs review' : 'Email ready';

  return (
    <View style={[styles.card, { backgroundColor: colors.glass, borderColor: selected ? colors.primary : colors.glassBorder, boxShadow: colors.cardShadow }]}>
      <View style={styles.head}>
        {onSelect ? (
          <Pressable
            accessibilityRole="checkbox"
            accessibilityLabel={`Select ${job.company} · ${job.role}`}
            accessibilityState={{ checked: !!selected }}
            onPress={onSelect}
            hitSlop={12}
            style={styles.tick}>
            <TickBox on={!!selected} big />
          </Pressable>
        ) : null}
        <View style={{ flex: 1, gap: 2 }}>
          <View style={styles.titleRow}>
            <Text numberOfLines={2} style={[styles.title, { color: colors.text, flex: 1 }]}>{job.role}</Text>
            {job.posted_at ? <Text style={[styles.time, { color: colors.textMuted }]}>{postedWhen(job.posted_at)}</Text> : null}
          </View>
          <Text numberOfLines={1} style={[styles.small, { color: colors.textMuted }]}>{where}</Text>
          {job.fit_score !== null ? <View style={{ marginTop: 6 }}><FitPill score={job.fit_score} verdict={job.verdict} /></View> : null}
          {job.checked_with ? (
            <Text numberOfLines={1} style={[styles.time, { color: colors.textMuted, marginTop: 4 }]}>
              Checked with: {job.checked_with}
            </Text>
          ) : null}
        </View>
      </View>

      <FactRows
        rows={[
          ...(job.experience ? [['Batch', job.experience] as [string, ReactNode]] : []),
          ...(job.salary ? [['Salary', job.salary] as [string, ReactNode]] : []),
          [
            'Apply',
            job.apply_method === 'email' ? (
              <Text selectable style={[styles.small, { color: colors.text }]}>
                {(active ? (job.send?.to_emails ?? all) : chosen.length ? chosen : all).join(', ') || 'No email address'}
                {!active ? (
                  <Text style={{ color: d && !d.outdated && d.status !== 'needs_review' ? colors.success : colors.textMuted }}>{` · ${emailState}`}</Text>
                ) : null}
                {link ? <Text style={{ color: colors.textMuted }}>{`\nAlso: apply on ${linkName(link)}`}</Text> : null}
              </Text>
            ) : link ? (
              `On ${linkName(link)}`
            ) : (
              'See the post for how to apply'
            ),
          ],
        ]}
      />

      {job.send ? (
        <View style={[styles.banner, { backgroundColor: colors.primarySoft }]}>
          <Clock size={14} color={colors.primaryText} strokeWidth={2} />
          <Text style={[styles.small, { color: colors.text, flexShrink: 1 }]}>{sendStatus(job.send)}</Text>
        </View>
      ) : null}

      {open === 'details' ? (
        <View style={[styles.panel, { backgroundColor: colors.background, borderColor: colors.border }]}>
          <PanelHead icon={Info} title="Details" onClose={() => setOpen(null)} />
          {job.matched_skills.length || job.gaps.length || job.flags.length ? (
            <Section title="WHY THIS SCORE">
              <View style={styles.tags}>
                {job.matched_skills.slice(0, 6).map((s) => (
                  <Tag key={`m-${s}`} text={s} tone="good" />
                ))}
                {job.gaps.slice(0, 4).map((s) => (
                  <Tag key={`g-${s}`} text={`gap: ${s}`} tone="gap" />
                ))}
              </View>
              {job.flags.length ? <Meta icon={TriangleAlert} color={colors.warning}>{job.flags.join(' · ')}</Meta> : null}
            </Section>
          ) : null}
          {job.must_have_skills.length ? (
            <Section title="REQUIREMENTS">
              <View style={styles.tags}>
                {job.must_have_skills.map((s) => (
                  <Tag key={s} text={s} tone="plain" />
                ))}
              </View>
            </Section>
          ) : null}
          {job.apply_method === 'email' && all.length > 1 && !waiting ? (
            <Section title="SEND TO (ONE EMAIL TO ALL TICKED)">
              {all.map((e) => (
                <Pressable
                  key={e}
                  accessibilityRole="checkbox"
                  accessibilityState={{ checked: chosen.includes(e) }}
                  onPress={() => toggleTo(e)}
                  style={styles.check}>
                  <TickBox on={chosen.includes(e)} />
                  <Text style={[styles.small, { color: colors.text }]}>{e}</Text>
                </Pressable>
              ))}
            </Section>
          ) : null}
          {job.apply_instructions ? (
            <Section title="HOW TO APPLY">
              <Text selectable style={[styles.small, { color: colors.text }]}>{job.apply_instructions}</Text>
            </Section>
          ) : null}
          {d?.status === 'needs_review' ? <Meta icon={TriangleAlert} color={colors.warning}>Email needs review: {d.issues.join('; ')}</Meta> : null}
        </View>
      ) : null}
      {open === 'email' && d ? (
        <View style={[styles.panel, { backgroundColor: colors.background, borderColor: colors.border }]}>
          <PanelHead icon={Mail} title="Email" onClose={() => { setEditing(false); setOpen(null); }} />
          {editing ? (
            <View style={{ gap: spacing.sm }}>
              <Field label="Subject" value={subject} onChangeText={setSubject} />
              <Field label="Email" value={text} onChangeText={setText} multiline textAlignVertical="top"
                style={{ minHeight: 220 }} />
              <View style={styles.row}>
                <Pill label="Save" primary busy={save.isPending} onPress={() => save.mutate()} />
                <Pill label="Cancel" onPress={() => setEditing(false)} />
              </View>
              <Small>{waiting ? 'The scheduled email goes out with your version, at the same time.' : 'Your version is the one that gets sent for this job.'}</Small>
            </View>
          ) : (
            <>
              <View style={styles.titleRow}>
                <Small>To: {(s && active ? (s.to_emails ?? [s.to_email]) : chosen).join(', ')}</Small>
                {s?.status !== 'sending' ? (
                  <Pressable accessibilityRole="button" accessibilityLabel="Edit this email" onPress={startEdit} hitSlop={8}
                    style={styles.close}>
                    <Pencil size={16} color={colors.primaryText} strokeWidth={2} />
                  </Pressable>
                ) : null}
              </View>
              {d.edited ? <Small color={colors.primaryText}>Edited by you</Small> : null}
              <Text selectable style={[styles.subject, { color: colors.text }]}>{d.subject}</Text>
              <Text selectable style={[styles.body, { color: colors.text }]}>{d.body}</Text>
              {s?.status !== 'sending' ? (
                <View style={styles.row}>
                  <Pill label="Rewrite email" icon={PenLine} busy={write.isPending} onPress={() => write.mutate()} />
                </View>
              ) : null}
            </>
          )}
        </View>
      ) : null}
      {open === 'post' && job.post_text ? (
        <View style={[styles.panel, { backgroundColor: colors.background, borderColor: colors.border }]}>
          <PanelHead icon={FileText} title="Original post" onClose={() => setOpen(null)} />
          <PostText text={job.post_text} />
        </View>
      ) : null}

      {ask && notes ? (
        <View style={[styles.ask, { backgroundColor: colors.warningSoft }]}>
          {notes.map((n) => (
            <Meta key={n} icon={TriangleAlert} color={colors.text}>{n}</Meta>
          ))}
          <Text style={[styles.body, { color: colors.text }]}>{`Send to ${chosen.join(', ')} ${ask.label} anyway?`}</Text>
          <View style={styles.row}>
            <Pill label="Send anyway" primary busy={schedule.isPending} onPress={() => schedule.mutate({ when: ask.when, confirm: true })} />
            <Pill label="Cancel" onPress={() => { setNotes(null); setAsk(null); }} />
          </View>
        </View>
      ) : ask ? (
        <View style={[styles.ask, { backgroundColor: colors.primarySoft }]}>
          <Text style={[styles.body, { color: colors.text }]}>
            {testMode
              ? `Test mode: this goes to your own inbox (not ${chosen.join(', ')}) ${ask.label}. Confirm?`
              : `Send one email to ${chosen.join(', ')} ${ask.label}? Nothing goes out until you confirm.`}
          </Text>
          <View style={styles.row}>
            <Pill label="Confirm" primary busy={schedule.isPending} onPress={() => schedule.mutate({ when: ask.when })} />
            <Pill label="Cancel" onPress={() => setAsk(null)} />
          </View>
        </View>
      ) : (
        <View style={[styles.actions, { borderTopColor: colors.border }]}>
          <View style={styles.row}>
            {job.apply_method === 'link' && link ? (
              <Pill label="Open apply link" icon={ExternalLink} primary onPress={() => Linking.openURL(link)} />
            ) : null}
            {job.apply_method === 'email' && (!d || d.outdated || d.status === 'needs_review') && !waiting ? (
              <Pill label={d ? 'Rewrite email' : 'Write email'} icon={PenLine} primary busy={write.isPending} onPress={() => write.mutate()} />
            ) : null}
            {canSend ? (
              <>
                <Pill label={sendLabel} icon={SendIcon} primary onPress={() => setAsk({ when: 'now', label: 'now' })} />
                <Pill label="Schedule" icon={Clock} onPress={() => setScheduling(true)} />
              </>
            ) : null}
            {job.apply_method === 'email' && link ? (
              <Pill label="Open apply link" icon={ExternalLink} onPress={() => Linking.openURL(link)} />
            ) : null}
          </View>
          <View style={styles.row}>
            <Toggle icon={Info} label="Details" on={open === 'details'} onPress={() => flip('details')} />
            {d ? <Toggle icon={Mail} label="Email" on={open === 'email'} onPress={() => flip('email')} /> : null}
            {job.post_text ? <Toggle icon={FileText} label="Post" on={open === 'post'} onPress={() => flip('post')} /> : null}
          </View>
        </View>
      )}
      {d && all.length > 1 && !active && !chosen.length ? <Small color={colors.warning}>Tick at least one email address (Details).</Small> : null}
      {error ? <Small color={colors.error}>{errorMessage(error)}</Small> : null}
      <ScheduleSheet
        open={scheduling}
        quick={['tomorrow']}
        onClose={() => setScheduling(false)}
        onChoose={(c) => {
          setScheduling(false);
          setAsk(c);
        }}
      />
    </View>
  );
}

/** "Write & schedule N emails" → when? (floating window) → confirm → progress → results.
 * Jobs screen: sticky at the bottom; chat: inline under the job cards. */
export function BulkBar({ jobs, onDone, inline }: { jobs: Job[]; onDone: () => void; inline?: boolean }) {
  const { colors } = useColors();
  const qc = useQueryClient();
  const testMode = useMe().data?.test_mode ?? true;
  const [stage, setStage] = useState<'idle' | 'confirm' | 'running' | 'done'>('idle');
  const [choosing, setChoosing] = useState(false);
  const [plan, setPlan] = useState<Choice | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [results, setResults] = useState<BulkResult[]>([]);
  const emailModel = usePicks((s) => s.email);
  const modelName = useModels().data?.models.find((m) => m.id === emailModel)?.label ?? 'Auto (best available)';
  const n = jobs.length;
  const toWrite = jobs.filter((j) => !j.draft || j.draft.outdated).length;

  const run = async () => {
    if (!plan) return;
    setStage('running');
    const done = await writeAndSchedule(jobs, plan.when, setProgress, emailModel);
    if (done.some((r) => r.ok)) haptic.sent();
    setResults(done);
    await Promise.all([qc.invalidateQueries({ queryKey: ['jobs'] }), qc.invalidateQueries({ queryKey: ['sends'] })]);
    setStage('done');
  };

  return (
    <View
      style={[
        inline ? styles.bulkInline : styles.bulk,
        { backgroundColor: colors.glass, borderColor: inline ? colors.primary : colors.glassBorder },
      ]}>
      <View style={styles.inner}>
        {stage === 'idle' ? (
          <View style={styles.spread}>
            <Small color={colors.text}>{n} selected</Small>
            <View style={styles.row}>
              <Pill label="Clear" onPress={onDone} />
              <Pill label={`Write & schedule ${n} email${n > 1 ? 's' : ''}`} primary onPress={() => setChoosing(true)} />
            </View>
          </View>
        ) : stage === 'confirm' && plan ? (
          <View style={{ gap: spacing.sm }}>
            <Small color={colors.text}>
              {toWrite ? `Write ${toWrite} email${toWrite > 1 ? 's' : ''} with ${modelName}, then send` : 'Send'} {n} email
              {n > 1 ? 's' : ''} to each job&apos;s email addresses {plan.label}, 3–8 min apart (your daily limit; extra ones move
              to the next morning).{testMode ? ' Test mode: they all go to your own inbox.' : ''}
            </Small>
            <View style={styles.row}>
              <Pill label="Confirm" primary onPress={run} />
              <Pill label="Back" onPress={() => setStage('idle')} />
            </View>
          </View>
        ) : stage === 'running' ? (
          <View style={styles.row}>
            <ActivityIndicator color={colors.primary} />
            <Small color={colors.text}>
              {progress
                ? `${progress.phase === 'writing' ? 'Writing' : 'Scheduling'} ${progress.index + 1} of ${progress.total}: ${progress.job.company}…`
                : 'Starting…'}
            </Small>
          </View>
        ) : (
          <View style={{ gap: spacing.xs }}>
            <Small color={colors.text}>
              Done: {results.filter((r) => r.ok).length} of {results.length} scheduled.
            </Small>
            {results.map((r) => (
              <Small key={r.job.id} color={r.ok ? colors.success : colors.error}>
                {r.ok ? '✓' : '✗'} {r.job.company}: {r.ok ? when(r.note) : r.note}
              </Small>
            ))}
            <View style={styles.row}>
              <Pill label="Close" primary onPress={onDone} />
            </View>
          </View>
        )}
      </View>
      <ScheduleSheet
        open={choosing}
        title={`When should the ${n} email${n > 1 ? 's' : ''} go out?`}
        onClose={() => setChoosing(false)}
        onChoose={(c) => {
          setChoosing(false);
          setPlan(c);
          setStage('confirm');
        }}
      />
    </View>
  );
}

function ConfirmCard({ actionId }: { actionId: number }) {
  const { colors } = useColors();
  const qc = useQueryClient();
  const refresh = useRefresh();
  const q = useQuery({
    queryKey: ['action', actionId],
    queryFn: async () => (await api.get<Action>(`/actions/${actionId}`)).data,
  });
  const act = useMutation({
    mutationFn: (verb: 'confirm' | 'dismiss') => api.post<Action>(`/actions/${actionId}/${verb}`),
    onSuccess: (r, verb) => {
      if (verb === 'confirm') haptic.sent();
      qc.setQueryData(['action', actionId], r.data);
      return refresh();
    },
    onError: () => q.refetch(), // e.g. already confirmed on the other device
  });
  const a = q.data;
  if (!a) return <Loading error={q.error} />;
  const done = { done: `✓ Done${a.result ? `: ${a.result}` : ''}`, dismissed: 'Dismissed', failed: `Failed: ${a.result}` };
  return (
    <View style={[styles.card, { backgroundColor: colors.glass, borderColor: a.status === 'pending' ? colors.primary : colors.glassBorder, boxShadow: colors.cardShadow }]}>
      <Text style={[styles.body, { color: colors.text }]}>{a.summary}</Text>
      {a.status === 'pending' ? (
        <View style={styles.row}>
          <Pill label="Confirm" primary busy={act.isPending && act.variables === 'confirm'} onPress={() => act.mutate('confirm')} />
          <Pill label="Dismiss" busy={act.isPending && act.variables === 'dismiss'} onPress={() => act.mutate('dismiss')} />
        </View>
      ) : (
        <Small color={a.status === 'done' ? colors.success : a.status === 'failed' ? colors.error : colors.textMuted}>
          {done[a.status]}
        </Small>
      )}
      {act.error ? <Small color={colors.error}>{errorMessage(act.error)}</Small> : null}
    </View>
  );
}

function SendsCard({ ids }: { ids: number[] }) {
  const { colors } = useColors();
  const q = useQuery({
    queryKey: ['sends', 'scheduled'],
    queryFn: async () => (await api.get<Send[]>('/sends', { params: { status: 'scheduled' } })).data,
  });
  if (!q.data) return <Loading error={q.error} />;
  const rows = q.data.filter((s) => ids.includes(s.id));
  return (
    <View style={[styles.card, { backgroundColor: colors.glass, borderColor: colors.glassBorder, boxShadow: colors.cardShadow }]}>
      {rows.length === 0 ? <Small>None of these are scheduled any more.</Small> : null}
      {rows.map((s) => (
        <View key={s.id}>
          <Text style={[styles.title, { color: colors.text }]}>
            {s.company} · {s.role}
          </Text>
          <Small>
            #{s.id} · {when(s.send_at)} · {(s.to_emails ?? [s.to_email]).join(', ')}
            {s.test_mode ? ' · TEST' : ''}
          </Small>
        </View>
      ))}
    </View>
  );
}

export function Small({ children, color }: { children: ReactNode; color?: string }) {
  const { colors } = useColors();
  return <Text style={[styles.small, { color: color ?? colors.textMuted }]}>{children}</Text>;
}

/** While loading: grey placeholders shaped like cards. On failure: what went wrong, and Retry when we can. */
export function Loading({ error, retry, count = 2 }: { error: unknown; retry?: () => void; count?: number }) {
  const { colors } = useColors();
  if (!error) return <ShimmerList count={count} />;
  return (
    <View style={{ gap: spacing.sm, alignItems: 'flex-start' }}>
      <Small color={colors.error}>{errorMessage(error)}</Small>
      {retry ? <Pill label="Retry" icon={RefreshCw} onPress={retry} /> : null}
    </View>
  );
}

export function Pill({
  label,
  onPress,
  primary,
  busy,
  icon: Icon,
}: {
  label: string;
  onPress: () => void;
  primary?: boolean;
  busy?: boolean;
  icon?: typeof Check;
}) {
  const { colors } = useColors();
  const fg = primary ? colors.onPrimary : colors.text;
  return (
    <Pressy
      accessibilityRole="button"
      onPress={onPress}
      disabled={busy}
      style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [
        styles.pill,
        {
          backgroundColor: primary ? colors.primary : pressed || hovered ? colors.surfaceAlt : colors.glass,
          borderColor: primary ? colors.primary : colors.border,
          opacity: pressed ? 0.85 : 1,
        },
        primary ? { boxShadow: colors.buttonGlow } : null,
      ]}>
      {busy ? (
        <ActivityIndicator size="small" color={fg} />
      ) : (
        <View style={styles.pillInner}>
          {Icon ? <Icon size={14} color={fg} strokeWidth={2} /> : null}
          <Text style={[styles.pillText, { color: fg }]}>{label}</Text>
        </View>
      )}
    </Pressy>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.sm },
  head: { flexDirection: 'row', gap: spacing.md, alignItems: 'flex-start' },
  tick: { paddingTop: 1 },
  titleRow: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm },
  time: { fontFamily: fonts.body, fontSize: 12, lineHeight: 21 },
  facts: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', columnGap: spacing.md, rowGap: spacing.xs },
  fitPill: { flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderRadius: radius.pill, paddingVertical: 3,
    paddingHorizontal: 10, alignSelf: 'flex-start' },
  fitPillScore: { fontFamily: fonts.heading, fontSize: 13 },
  fitPillText: { fontFamily: fonts.semibold, fontSize: 12 },
  apply: { borderRadius: radius.sm, paddingVertical: spacing.sm, paddingHorizontal: spacing.md, gap: 2 },
  factBox: { borderRadius: radius.md, paddingVertical: spacing.sm, paddingHorizontal: spacing.md, gap: 5 },
  factRow: { flexDirection: 'row', gap: spacing.md },
  factLabel: { fontFamily: fonts.semibold, fontSize: 13, lineHeight: 19, width: 54 },
  sectionTitle: { fontFamily: fonts.semibold, fontSize: 11, letterSpacing: 0.6 },
  status: { flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', borderWidth: 1,
    borderRadius: radius.pill, paddingVertical: 3, paddingHorizontal: 10 },
  dot: { width: 7, height: 7, borderRadius: 4 },
  statusText: { fontFamily: fonts.semibold, fontSize: 12 },
  metaRow: { flexDirection: 'row', flexWrap: 'wrap', columnGap: spacing.lg, rowGap: spacing.xs },
  meta: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  tag: { borderWidth: 1, borderRadius: radius.pill, paddingVertical: 3, paddingHorizontal: 10 },
  tagText: { fontFamily: fonts.body, fontSize: 12 },
  banner: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, borderRadius: radius.sm, padding: spacing.sm },
  panel: { borderWidth: 1, borderRadius: radius.sm, padding: spacing.md, paddingTop: spacing.xs, gap: spacing.md },
  panelHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: 1,
    paddingBottom: spacing.xs, marginBottom: spacing.xs },
  close: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center' },
  actions: { borderTopWidth: 1, paddingTop: spacing.md, marginTop: spacing.xs, flexDirection: 'row', flexWrap: 'wrap',
    justifyContent: 'space-between', alignItems: 'center', gap: spacing.sm },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 5, borderWidth: 1, borderRadius: radius.pill, paddingVertical: 5,
    paddingHorizontal: 10 },
  toggleText: { fontFamily: fonts.semibold, fontSize: 12 },
  title: { fontFamily: fonts.semibold, fontSize: 16, lineHeight: 22 },
  small: { fontFamily: fonts.body, fontSize: 13, lineHeight: 19 },
  body: { fontFamily: fonts.body, fontSize: 14, lineHeight: 21 },
  subject: { fontFamily: fonts.semibold, fontSize: 14 },
  email: { borderWidth: 1, borderRadius: radius.sm, padding: spacing.md, gap: spacing.xs, marginTop: spacing.xs },
  ask: { borderRadius: radius.sm, padding: spacing.md, gap: spacing.sm, marginTop: spacing.xs },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.sm },
  pill: { borderWidth: 1, borderRadius: radius.pill, paddingVertical: 7, paddingHorizontal: spacing.md, minHeight: 34, justifyContent: 'center' },
  pillText: { fontFamily: fonts.semibold, fontSize: 13 },
  pillInner: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  post: { borderLeftWidth: 3, paddingLeft: spacing.md, gap: 3, marginVertical: spacing.xs },
  check: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: 3 },
  box: { width: 18, height: 18, borderRadius: 4, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  bigBox: { width: 22, height: 22, borderRadius: 6 },
  spread: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  bulk: { borderTopWidth: 1, paddingVertical: spacing.md, paddingHorizontal: spacing.lg },
  bulkInline: { borderWidth: 1, borderRadius: radius.lg, padding: spacing.md },
  inner: { width: '100%', maxWidth: 760, alignSelf: 'center' },
});
