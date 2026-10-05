/** Month calendar (India days) + quick times or a typed time, for sending. dateOnly: just pick a day (Jobs date jump);
 * pastOnly: up to today (jobs already posted) instead of from today (sending). Same on web and phones. */
import { ChevronLeft, ChevronRight } from 'lucide-react-native';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { IconButton } from '@/components/icon-button';
import { monthGrid, parseTime, timeLabel, whenText } from '@/lib/calendar';
import { dateLabel, istToday } from '@/lib/days';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
  'November', 'December'];
const QUICK = [['09:00', '9 AM'], ['10:00', '10 AM'], ['11:00', '11 AM'], ['12:00', '12 PM'], ['14:00', '2 PM'],
  ['17:00', '5 PM']] as const;

export function DateTimePicker({
  onPick,
  onCancel,
  dateOnly,
  pastOnly,
  initialDay,
}: {
  /** when: sent to the server ("2026-10-03 11:00", India time), or the day "2026-10-03" when dateOnly; label: shown. */
  onPick: (when: string, label: string) => void;
  onCancel?: () => void;
  dateOnly?: boolean;
  pastOnly?: boolean;
  initialDay?: string;
}) {
  const { colors } = useColors();
  const today = istToday();
  const start = initialDay ?? today;
  const [view, setView] = useState({ y: Number(start.slice(0, 4)), m: Number(start.slice(5, 7)) });
  const [day, setDay] = useState<string | null>(null);
  const [time, setTime] = useState<string>('10:00');
  const [typed, setTyped] = useState('');
  const typedTime = typed.trim() ? parseTime(typed) : null;
  const finalTime = typed.trim() ? typedTime : time;

  const step = (by: number) => {
    const m0 = view.m - 1 + by;
    setView({ y: view.y + Math.floor(m0 / 12), m: ((m0 % 12) + 12) % 12 + 1 });
  };
  const thisMonth = Number(today.slice(0, 4)) * 12 + Number(today.slice(5, 7));
  const canGoBack = pastOnly || view.y * 12 + view.m > thisMonth;
  const canGoForward = !pastOnly || view.y * 12 + view.m < thisMonth;

  return (
    <View style={styles.box}>
      <View style={styles.head}>
        {canGoBack ? <IconButton icon={ChevronLeft} label="Previous month" onPress={() => step(-1)} /> : <View style={styles.gap} />}
        <Text style={[styles.month, { color: colors.text }]}>
          {MONTHS[view.m - 1]} {view.y}
        </Text>
        {canGoForward ? <IconButton icon={ChevronRight} label="Next month" onPress={() => step(1)} /> : <View style={styles.gap} />}
      </View>
      <View style={styles.week}>
        {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => (
          <Text key={i} style={[styles.cell, styles.dow, { color: colors.textMuted }]}>
            {d}
          </Text>
        ))}
      </View>
      {monthGrid(view.y, view.m).map((week, i) => (
        <View key={i} style={styles.week}>
          {week.map((d, j) => {
            if (!d) return <View key={j} style={styles.cell} />;
            const past = pastOnly ? d > today : d < today; // not selectable
            const on = d === (dateOnly ? initialDay : day);
            return (
              <Pressable
                key={j}
                accessibilityRole="button"
                accessibilityLabel={d}
                accessibilityState={{ disabled: past, selected: on }}
                disabled={past}
                onPress={() => (dateOnly ? onPick(d, dateLabel(d)) : setDay(d))}
                style={[
                  styles.cell,
                  styles.dayCell,
                  on && { backgroundColor: colors.primary },
                  d === today && !on && { borderWidth: 1, borderColor: colors.primary },
                ]}>
                <Text style={{ fontFamily: fonts.semibold, color: on ? colors.onPrimary : past ? colors.border : colors.text }}>
                  {Number(d.slice(8))}
                </Text>
              </Pressable>
            );
          })}
        </View>
      ))}

      {dateOnly ? null : (
      <>
      <Text style={[styles.label, { color: colors.text }]}>Time (India)</Text>
      <View style={styles.row}>
        {QUICK.map(([value, label]) => {
          const on = !typed.trim() && time === value;
          return (
            <Pressable
              key={value}
              accessibilityRole="radio"
              accessibilityState={{ selected: on }}
              onPress={() => {
                setTyped('');
                setTime(value);
              }}
              style={[styles.chip, { borderColor: on ? colors.primary : colors.border, backgroundColor: on ? colors.primary : colors.surface }]}>
              <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color: on ? colors.onPrimary : colors.text }}>{label}</Text>
            </Pressable>
          );
        })}
        <TextInput
          value={typed}
          onChangeText={setTyped}
          placeholder="or type 2:30 pm"
          placeholderTextColor={colors.textMuted}
          style={[styles.input, { color: colors.text, borderColor: typed && !typedTime ? colors.error : colors.border,
            backgroundColor: colors.surface }]}
        />
      </View>

      <View style={styles.row}>
        <Pressable
          accessibilityRole="button"
          disabled={!day || !finalTime}
          onPress={() => day && finalTime && onPick(whenText(day, finalTime), timeLabel(day, finalTime))}
          style={[styles.chip, { backgroundColor: colors.primary, borderColor: colors.primary, opacity: day && finalTime ? 1 : 0.5 }]}>
          <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color: colors.onPrimary }}>
            {day && finalTime ? `Use ${timeLabel(day, finalTime)}` : !day ? 'Pick a day' : 'Check the time'}
          </Text>
        </Pressable>
        {onCancel ? (
          <Pressable accessibilityRole="button" onPress={onCancel} style={[styles.chip, { borderColor: colors.border, backgroundColor: colors.surface }]}>
            <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color: colors.text }}>Back</Text>
          </Pressable>
        ) : null}
      </View>
      </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { gap: spacing.xs, width: '100%' },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  gap: { width: 36 },
  month: { fontFamily: fonts.semibold, fontSize: 15 },
  week: { flexDirection: 'row' },
  cell: { flex: 1, height: 36, alignItems: 'center', justifyContent: 'center', textAlign: 'center' },
  dow: { fontFamily: fonts.body, fontSize: 12, lineHeight: 36 },
  dayCell: { borderRadius: 18 },
  label: { fontFamily: fonts.semibold, fontSize: 13, marginTop: spacing.sm },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.sm, marginTop: spacing.xs },
  chip: { borderWidth: 1, borderRadius: radius.pill, paddingVertical: 7, paddingHorizontal: spacing.md, minHeight: 34, justifyContent: 'center' },
  input: { borderWidth: 1, borderRadius: radius.pill, paddingVertical: 7, paddingHorizontal: spacing.md, minWidth: 130,
    fontFamily: fonts.body, fontSize: 13 },
});
