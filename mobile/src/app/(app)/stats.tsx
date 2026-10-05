/** Stats: the funnel as tiles, fit breakdown, per email account, and per-day bars (posts and emails as two charts:
 * different scales never share an axis). Test-mode emails are counted apart. */
import { useQuery } from '@tanstack/react-query';
import { CalendarDays } from 'lucide-react-native';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Pill } from '@/components/chat-cards';
import { DateTimePicker } from '@/components/date-time-picker';
import { Sheet } from '@/components/sheet';
import { Card, Choice, Screen, T } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { dateLabel, dayTitle, istToday } from '@/lib/days';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

type Day = { date: string; posts: number; sent: number };
type Stats = {
  days_back: number; from: string; to: string;
  funnel: { posts: number; checked: number; fit: number; sent: number; replies: number; reply_rate: number };
  fit_breakdown: Record<string, number>;
  test_sent: number;
  senders: { email: string; sent: number; replies: number; reply_rate: number }[];
  days: Day[];
};
type Period = string; // '7' | '30' | '90' days, or one India day 'YYYY-MM-DD'

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  const { colors } = useColors();
  return (
    <View style={[styles.tile, { backgroundColor: colors.background, borderColor: colors.border }]}>
      <Text style={[styles.tileValue, { color: colors.text }]}>{value}</Text>
      <Text style={[styles.tileLabel, { color: colors.textMuted }]}>{label}</Text>
      {sub ? <Text style={[styles.tileSub, { color: colors.textMuted }]}>{sub}</Text> : null}
    </View>
  );
}

/** One series per day: rounded bar tops on a baseline, 2px gaps, the highest day labelled, tap/hover for the value. */
function DayBars({ title, days, pick, unit }: { title: string; days: Day[]; pick: (d: Day) => number; unit: string }) {
  const { colors } = useColors();
  const [focus, setFocus] = useState<number | null>(null);
  const values = days.map(pick);
  const max = Math.max(1, ...values);
  const top = values.indexOf(Math.max(...values));
  const shown = focus ?? top;
  const gap = days.length > 30 ? 1 : 2;
  if (!values.some(Boolean)) {
    return (
      <View style={{ gap: spacing.xs }}>
        <Text style={[styles.chartTitle, { color: colors.text }]}>{title}</Text>
        <Text style={[styles.tileSub, { color: colors.textMuted }]}>{`No ${unit} in this period yet.`}</Text>
      </View>
    );
  }
  return (
    <View style={{ gap: spacing.xs }}>
      <View style={styles.spread}>
        <Text style={[styles.chartTitle, { color: colors.text }]}>{title}</Text>
        <Text style={[styles.tileSub, { color: colors.textMuted }]}>
          {`${dateLabel(days[shown].date)}: ${values[shown]} ${unit}${focus === null && values[shown] ? ' (highest)' : ''}`}
        </Text>
      </View>
      <View style={[styles.plot, { borderBottomColor: colors.border, gap }]}>
        {days.map((d, i) => (
          <Pressable
            key={d.date}
            accessibilityRole="button"
            accessibilityLabel={`${dateLabel(d.date)}: ${values[i]} ${unit}`}
            onPress={() => setFocus(i)}
            onHoverIn={() => setFocus(i)}
            onHoverOut={() => setFocus(null)}
            style={styles.slot}>
            <View
              style={[
                styles.bar,
                {
                  height: values[i] ? Math.max(3, (values[i] / max) * 100) : 0,
                  backgroundColor: colors.chart,
                  opacity: focus === null || focus === i ? 1 : 0.45,
                },
              ]}
            />
          </Pressable>
        ))}
      </View>
      <View style={styles.spread}>
        <Text style={[styles.axis, { color: colors.textMuted }]}>{dateLabel(days[0].date)}</Text>
        <Text style={[styles.axis, { color: colors.textMuted }]}>{dateLabel(days[days.length - 1].date)}</Text>
      </View>
    </View>
  );
}

export default function StatsScreen() {
  const { colors } = useColors();
  const today = istToday();
  const [period, setPeriod] = useState<Period>('7');
  const [table, setTable] = useState(false);
  const [calendar, setCalendar] = useState(false);
  const oneDay = period.includes('-');
  const q = useQuery({
    queryKey: ['stats', period],
    queryFn: async () =>
      (await api.get<Stats>('/stats', { params: oneDay ? { date: period } : { days: Number(period) } })).data,
  });
  const st = q.data;
  const f = st?.funnel;
  const fitMax = st ? Math.max(1, ...Object.values(st.fit_breakdown)) : 1;

  return (
    <Screen>
      <Choice<Period>
        value={period}
        onChange={setPeriod}
        options={[
          { label: 'Today', value: today },
          { label: 'Last 7 days', value: '7' },
          { label: '30 days', value: '30' },
          { label: '90 days', value: '90' },
          ...(oneDay && period !== today ? [{ label: dateLabel(period), value: period }] : []),
        ]}
      />
      <View style={styles.row}>
        <Pill label="Pick a day" icon={CalendarDays} onPress={() => setCalendar(true)} />
      </View>
      <Sheet open={calendar} title="Stats for one day" onClose={() => setCalendar(false)}>
        <DateTimePicker
          dateOnly
          pastOnly
          initialDay={oneDay ? period : today}
          onPick={(d) => {
            setCalendar(false);
            setPeriod(d);
          }}
        />
      </Sheet>
      {q.error ? <T variant="error">{errorMessage(q.error)}</T> : null}
      {!st || !f ? (
        !q.error ? <T variant="muted">Loading…</T> : null
      ) : (
        <>
          <Card>
            <T variant="heading">{oneDay ? `From post to reply · ${dayTitle(period, today)}` : 'From post to reply'}</T>
            <View style={styles.tiles}>
              <Tile label="Posts read" value={String(f.posts)} />
              <Tile label="Checked by AI" value={String(f.checked)} />
              <Tile label="Fit your resume" value={String(f.fit)} />
              <Tile label="Emails sent" value={String(f.sent)} />
              <Tile label="Replies" value={String(f.replies)} />
              <Tile label="Reply rate" value={f.sent ? `${f.reply_rate}%` : '-'} sub={f.sent ? undefined : 'after the first email'} />
            </View>
            {st.test_sent ? (
              <T variant="muted">{`${st.test_sent} test-mode email${st.test_sent === 1 ? '' : 's'} went to your own inbox (not counted above).`}</T>
            ) : null}
          </Card>

          <Card>
            <T variant="heading">Fit breakdown</T>
            {Object.entries(st.fit_breakdown).map(([label, n]) => (
              <View key={label} style={styles.fitRow}>
                <Text style={[styles.fitLabel, { color: colors.text }]}>{label}</Text>
                <View style={[styles.track, { backgroundColor: colors.surfaceAlt }]}>
                  <View style={[styles.fill, { width: `${(n / fitMax) * 100}%`, backgroundColor: colors.chart }]} />
                </View>
                <Text style={[styles.fitCount, { color: colors.text }]}>{n}</Text>
              </View>
            ))}
          </Card>

          {!oneDay ? (
          <Card>
            <DayBars title="Posts read per day" days={st.days} pick={(d) => d.posts} unit="posts" />
            <DayBars title="Emails sent per day" days={st.days} pick={(d) => d.sent} unit="emails" />
            <View style={styles.row}>
              <Pill label={table ? 'Hide table' : 'Show as table'} onPress={() => setTable(!table)} />
            </View>
            {table ? (
              <View style={{ gap: 2 }}>
                {[...st.days].reverse().map((d) => (
                  <View key={d.date} style={[styles.tableRow, { borderBottomColor: colors.border }]}>
                    <Text style={[styles.cell, { color: colors.text, flex: 1 }]}>{dateLabel(d.date)}</Text>
                    <Text style={[styles.cell, { color: colors.text }]}>{`${d.posts} posts`}</Text>
                    <Text style={[styles.cell, { color: colors.text }]}>{`${d.sent} sent`}</Text>
                  </View>
                ))}
              </View>
            ) : null}
          </Card>
          ) : null}

          <Card>
            <T variant="heading">By email account</T>
            {st.senders.length ? (
              st.senders.map((a) => (
                <View key={a.email} style={[styles.tableRow, { borderBottomColor: colors.border }]}>
                  <Text numberOfLines={1} style={[styles.cell, { color: colors.text, flex: 1 }]}>{a.email}</Text>
                  <Text style={[styles.cell, { color: colors.text }]}>{`${a.sent} sent`}</Text>
                  <Text style={[styles.cell, { color: colors.text }]}>{`${a.replies} replies`}</Text>
                  <Text style={[styles.cell, { color: colors.textMuted }]}>{a.sent ? `${a.reply_rate}%` : '0%'}</Text>
                </View>
              ))
            ) : (
              <T variant="muted">No email account connected yet (Setup → Email accounts).</T>
            )}
          </Card>
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  tile: { flexGrow: 1, flexBasis: '30%', borderWidth: 1, borderRadius: radius.sm, padding: spacing.md, gap: 2 },
  tileValue: { fontFamily: fonts.heading, fontSize: 26 },
  tileLabel: { fontFamily: fonts.semibold, fontSize: 13 },
  tileSub: { fontFamily: fonts.body, fontSize: 12 },
  fitRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  fitLabel: { fontFamily: fonts.body, fontSize: 14, width: 96 },
  track: { flex: 1, height: 10, borderRadius: 5, overflow: 'hidden' },
  fill: { height: 10, borderRadius: 5 },
  fitCount: { fontFamily: fonts.semibold, fontSize: 14, minWidth: 28, textAlign: 'right' },
  spread: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' },
  chartTitle: { fontFamily: fonts.semibold, fontSize: 15 },
  plot: { flexDirection: 'row', alignItems: 'flex-end', height: 104, borderBottomWidth: 1, paddingTop: 4 },
  slot: { flex: 1, height: '100%', justifyContent: 'flex-end' },
  bar: { borderTopLeftRadius: 4, borderTopRightRadius: 4 },
  axis: { fontFamily: fonts.body, fontSize: 11 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  tableRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderBottomWidth: 1, paddingVertical: 6 },
  cell: { fontFamily: fonts.body, fontSize: 14 },
});
