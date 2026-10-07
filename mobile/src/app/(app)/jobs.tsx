import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useFocusEffect, useLocalSearchParams } from 'expo-router';
import { CalendarDays, ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react-native';
import { useCallback, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import {
  BulkBar,
  JobItem,
  Pill,
  postMethod,
  PostItem,
  SelectBar,
  Small,
  useAutoCheck,
  usePicked,
  type Job,
  type PostInfo,
} from '@/components/chat-cards';
import { DateTimePicker } from '@/components/date-time-picker';
import { IconButton } from '@/components/icon-button';
import { ModelPicker } from '@/components/model-picker';
import { ServerList } from '@/components/server-list';
import { Sheet } from '@/components/sheet';
import { api, errorMessage } from '@/lib/api';
import { dayTitle, istToday, shiftDay } from '@/lib/days';
import { markJobsSeen } from '@/lib/new-jobs';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

type Kind = 'all' | 'email' | 'link';
type View_ = 'posts' | 'recommended';
type Fetched = { new_posts: number; checked: number; waiting: number; paused: boolean; problem: string | null };

function fetchedText(f: Fetched): string {
  if (f.problem) return f.problem;
  const parts = [`${f.new_posts} new post${f.new_posts === 1 ? '' : 's'} read`, `${f.checked} checked`];
  if (f.waiting) parts.push(f.paused ? `${f.waiting} wait for the free AI to refill` : `${f.waiting} still being checked`);
  return parts.join(' · ');
}

/** Pill-shaped switch (All posts | Recommended, All | Email | Link). */
function Segment<K extends string>({ options, value, onChange }: { options: [K, string][]; value: K; onChange: (k: K) => void }) {
  const { colors } = useColors();
  return (
    <View style={[styles.segment, { backgroundColor: colors.glass, borderColor: colors.border }]}>
      {options.map(([k, label]) => {
        const on = k === value;
        return (
          <Pressable
            key={k}
            accessibilityRole="radio"
            accessibilityState={{ selected: on }}
            onPress={() => onChange(k)}
            style={[styles.segmentItem, on && { backgroundColor: colors.primarySoft, borderColor: colors.primary }]}>
            <Text style={[styles.segmentText, { color: on ? colors.primaryText : colors.textMuted }]}>{label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const isDay = (d?: string) => !!d && /^\d{4}-\d{2}-\d{2}$/.test(d);

/** One India day: every Telegram post (newest first) or the jobs recommended for the resume (best first). */
export default function Jobs() {
  const { colors } = useColors();
  const qc = useQueryClient();
  const today = istToday();
  const { date } = useLocalSearchParams<{ date?: string }>(); // a notification opens its job's day
  const [day, setDay] = useState(isDay(date) ? date! : today);
  const [opened, setOpened] = useState(date);
  if (date !== opened) {
    // a notification opened another day while Jobs was already open
    setOpened(date);
    if (isDay(date)) setDay(date!);
  }
  const [view, setView] = useState<View_>('recommended');
  const [kind, setKind] = useState<Kind>('all');
  const { picked, setPicked, toggle } = usePicked();
  const [calendar, setCalendar] = useState(false);
  const [fetched, setFetched] = useState<Fetched | null>(null);
  const q = useQuery({
    queryKey: ['jobs', 'day', day],
    queryFn: async () => (await api.get<Job[]>('/jobs', { params: { date: day } })).data,
  });
  const pq = useQuery({
    queryKey: ['posts', 'day', day],
    queryFn: async () => (await api.get<PostInfo[]>('/posts', { params: { date: day } })).data,
  });
  const fetchNew = useMutation({
    mutationFn: async () => (await api.post<Fetched>('/jobs/fetch', { date: day }, { timeout: 120_000 })).data,
    onSuccess: async (f) => {
      setFetched(f);
      await Promise.all(['jobs', 'posts'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
    },
  });
  useFocusEffect(useCallback(() => void markJobsSeen(), [])); // clears the "new jobs" badge

  const all = q.data ?? [];
  const posts = pq.data ?? [];
  const jobCount = posts.reduce((n, p) => n + p.jobs.length, 0);
  const waiting = posts.filter((p) => p.kind === 'pending').length;
  const resumes = useQuery({
    queryKey: ['resumes'],
    queryFn: async () => (await api.get<{ name: string; is_active: boolean }[]>('/resumes')).data,
  });
  const primary = resumes.data?.find((r) => r.is_active)?.name;
  useAutoCheck(day, posts.some((p) => p.kind === 'pending')); // Recommended fills in by itself too
  // Both tabs share the Email / Link filter, the model picker and selection
  const count = (k: Kind) =>
    view === 'posts'
      ? k === 'all' ? posts.length : posts.filter((p) => postMethod(p) === k).length
      : k === 'all' ? all.length : all.filter((j) => j.apply_method === k).length;
  const shown = kind === 'all' ? all : all.filter((j) => j.apply_method === kind);
  const shownPosts = kind === 'all' ? posts : posts.filter((p) => postMethod(p) === kind);
  const shownJobs = view === 'posts' ? shownPosts.flatMap((p) => p.jobs) : shown;
  const switchView = (v: View_) => {
    setPicked([]);
    setView(v);
  };
  const changeDay = (d: string) => {
    setPicked([]);
    setFetched(null);
    setDay(d);
  };

  const header = (
    <View style={{ gap: spacing.md }}>
      <View style={styles.bar}>
        <View style={styles.dayNav}>
          <IconButton icon={ChevronLeft} label="Previous day" onPress={() => changeDay(shiftDay(day, -1))} />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Pick a date"
            onPress={() => setCalendar(true)}
            style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [
              styles.dayButton,
              { backgroundColor: pressed || hovered ? colors.surfaceAlt : undefined },
            ]}>
            <View>
              <View style={styles.dayLine}>
                <Text style={[styles.day, { color: colors.text }]}>{dayTitle(day, today)}</Text>
                <CalendarDays size={18} color={colors.primaryText} strokeWidth={2} />
              </View>
              {pq.data && q.data ? (
                <Text style={[styles.daySub, { color: colors.textMuted }]}>{`${posts.length} posts · ${jobCount} jobs · ${all.length} recommended`}</Text>
              ) : null}
            </View>
          </Pressable>
          {day < today ? (
            <IconButton icon={ChevronRight} label="Next day" onPress={() => changeDay(shiftDay(day, 1))} />
          ) : null}
          {day !== today ? <Pill label="Today" onPress={() => changeDay(today)} /> : null}
        </View>
        <Pill label="Fetch" icon={RefreshCw} busy={fetchNew.isPending} onPress={() => fetchNew.mutate()} />
      </View>
      {fetched || fetchNew.error ? (
        <View style={[styles.note, { backgroundColor: fetched?.problem || fetchNew.error ? colors.surfaceAlt : colors.primarySoft }]}>
          <Small color={fetchNew.error ? colors.error : colors.text}>
            {fetchNew.error ? errorMessage(fetchNew.error) : fetched ? fetchedText(fetched) : ''}
          </Small>
        </View>
      ) : null}
      {waiting && primary ? (
        <View style={[styles.note, { backgroundColor: colors.primarySoft }]}>
          <Small color={colors.text}>{`Checking ${waiting} ${waiting === 1 ? 'post' : 'posts'} with your resume "${primary}"…`}</Small>
        </View>
      ) : null}

      <Segment
        options={[['recommended', `Recommended ${all.length}`], ['posts', `All posts ${pq.data?.length ?? ''}`.trim()]]}
        value={view}
        onChange={switchView}
      />

      <View style={styles.bar}>
        <Segment
          options={[['all', `All ${count('all')}`], ['email', `Email ${count('email')}`], ['link', `Link / form ${count('link')}`]]}
          value={kind}
          onChange={setKind}
        />
        <ModelPicker kind="email" prefix="Emails:" />
      </View>
      {view === 'posts' ? <Small>{"Every Telegram post of the day, newest first, with Telegram's time."}</Small> : null}
      <SelectBar jobs={shownJobs} picked={picked} onPick={setPicked} />

      <Sheet open={calendar} title="Show jobs from" onClose={() => setCalendar(false)}>
        <DateTimePicker
          dateOnly
          pastOnly
          initialDay={day}
          onPick={(d) => {
            setCalendar(false);
            changeDay(d);
          }}
        />
      </Sheet>
    </View>
  );

  const footer = picked.length ? (
    <BulkBar jobs={shownJobs.filter((j: Job) => picked.includes(j.id))} onDone={() => setPicked([])} />
  ) : null;

  return view === 'posts' ? (
    <ServerList
      query={pq}
      keyOf={(p) => p.id}
      items={shownPosts}
      renderItem={(p) => <PostItem post={p} picked={picked} onToggle={toggle} />}
      empty={`No Telegram posts saved for ${dayTitle(day, today)}. Tap Fetch to read Telegram now.`}
      header={header}
      footer={footer}
    />
  ) : (
    <ServerList
      query={q}
      items={shown}
      keyOf={(j) => j.id}
      renderItem={(j) => <JobItem job={j} picked={picked} onToggle={toggle} />}
      empty={`No jobs recommended for your resume on ${dayTitle(day, today)}. See All posts, or tap Fetch to read new posts.`}
      header={header}
      footer={footer}
    />
  );
}

const styles = StyleSheet.create({
  bar: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  dayNav: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  dayButton: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: 6, paddingHorizontal: spacing.sm,
    borderRadius: radius.sm },
  day: { fontFamily: fonts.heading, fontSize: 24, letterSpacing: -0.3 },
  dayLine: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  daySub: { fontFamily: fonts.body, fontSize: 14, marginTop: 2 },
  note: { borderRadius: radius.sm, paddingVertical: spacing.sm, paddingHorizontal: spacing.md },
  segment: { flexDirection: 'row', borderRadius: radius.pill, padding: 3, borderWidth: 1 },
  segmentItem: { paddingVertical: 6, paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1,
    borderColor: 'transparent' },
  segmentText: { fontFamily: fonts.semibold, fontSize: 13 },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.sm },
});
