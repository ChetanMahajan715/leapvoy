/** "When should it go out?": one floating window for every schedule / move: quick choices or a calendar. */
import { CalendarDays, Clock, Send, Sunrise } from 'lucide-react-native';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { DateTimePicker } from '@/components/date-time-picker';
import { Sheet } from '@/components/sheet';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

export type Choice = { when: string; label: string };
type Quick = 'now' | 'hour' | 'tomorrow';

const QUICK: Record<Quick, Choice & { icon: typeof Clock; sub: string }> = {
  now: { when: 'now', label: 'now', icon: Send, sub: 'Spaced 3–8 minutes apart' },
  hour: { when: 'in 1 hour', label: 'in 1 hour', icon: Clock, sub: 'From now' },
  tomorrow: { when: 'tomorrow 10am', label: 'tomorrow at 10 AM', icon: Sunrise, sub: 'A good time for HR inboxes' },
};

export function ScheduleSheet({
  open,
  title = 'When should it go out?',
  quick = ['now', 'tomorrow'],
  onChoose,
  onClose,
}: {
  open: boolean;
  title?: string;
  quick?: Quick[];
  onChoose: (c: Choice) => void;
  onClose: () => void;
}) {
  const { colors } = useColors();
  const [calendar, setCalendar] = useState(false);
  const close = () => {
    setCalendar(false);
    onClose();
  };
  const choose = (c: Choice) => {
    setCalendar(false);
    onChoose(c);
  };
  const option = (key: string, Icon: typeof Clock, label: string, sub: string, onPress: () => void) => (
    <Pressable
      key={key}
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [
        styles.option,
        { borderColor: colors.border, backgroundColor: pressed || hovered ? colors.surfaceAlt : colors.background },
      ]}>
      <View style={[styles.icon, { backgroundColor: colors.primarySoft }]}>
        <Icon size={18} color={colors.primaryText} strokeWidth={2} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={[styles.label, { color: colors.text }]}>{label}</Text>
        <Text style={[styles.sub, { color: colors.textMuted }]}>{sub}</Text>
      </View>
    </Pressable>
  );
  return (
    <Sheet open={open} title={calendar ? 'Pick date & time' : title} onClose={close}>
      {calendar ? (
        <DateTimePicker onPick={(when, label) => choose({ when, label: `on ${label}` })} onCancel={() => setCalendar(false)} />
      ) : (
        <View style={{ gap: spacing.sm }}>
          {quick.map((k) => {
            const q = QUICK[k];
            return option(k, q.icon, q.label[0].toUpperCase() + q.label.slice(1), q.sub, () => choose(q));
          })}
          {option('pick', CalendarDays, 'Pick date & time', 'Any day and time (India time)', () => setCalendar(true))}
        </View>
      )}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  option: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderWidth: 1, borderRadius: radius.md, padding: spacing.md },
  icon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  label: { fontFamily: fonts.semibold, fontSize: 15 },
  sub: { fontFamily: fonts.body, fontSize: 12, marginTop: 2 },
});
