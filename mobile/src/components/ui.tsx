/** Small UI kit. Every color comes from the theme tokens (brand/theme/theme.ts), none hard-coded. */
import { Eye, EyeOff } from 'lucide-react-native';
import { useState, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
  type TextStyle,
} from 'react-native';
import Animated, { FadeIn } from 'react-native-reanimated';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Pressy } from '@/components/motion';
import { KeyboardScroll } from '@/lib/keyboard';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

/** Full screen with safe areas; the keyboard never covers inputs (keyboard-controller on phones). */
export function Screen({ children, center }: { children: ReactNode; center?: boolean }) {
  const { colors } = useColors();
  const Scroll = Platform.OS === 'web' ? ScrollView : KeyboardScroll;
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={['bottom', 'left', 'right']}>
      <Scroll
        contentContainerStyle={[styles.screen, center && styles.center]}
        keyboardShouldPersistTaps="handled">
        <Animated.View entering={FadeIn.duration(220)} style={styles.column}>
          {children}
        </Animated.View>
      </Scroll>
    </SafeAreaView>
  );
}

export function T({
  children,
  variant = 'body',
  style,
}: {
  children: ReactNode;
  variant?: 'title' | 'heading' | 'body' | 'muted' | 'mono' | 'error';
  style?: TextStyle;
}) {
  const { colors } = useColors();
  const base: Record<string, TextStyle> = {
    title: { fontFamily: fonts.heading, fontSize: 28, color: colors.text, letterSpacing: -0.3 },
    heading: { fontFamily: fonts.semibold, fontSize: 17, color: colors.text },
    body: { fontFamily: fonts.body, fontSize: 15, lineHeight: 22, color: colors.text },
    muted: { fontFamily: fonts.body, fontSize: 14, lineHeight: 20, color: colors.textMuted },
    mono: { fontFamily: fonts.mono, fontSize: 16, color: colors.text, letterSpacing: 1 },
    error: { fontFamily: fonts.semibold, fontSize: 14, color: colors.error },
  };
  return <Text style={[base[variant], style]}>{children}</Text>;
}

export function Button({
  title,
  onPress,
  kind = 'primary',
  busy,
  disabled,
}: {
  title: string;
  onPress: () => void;
  kind?: 'primary' | 'secondary' | 'danger';
  busy?: boolean;
  disabled?: boolean;
}) {
  const { colors } = useColors();
  const bg = { primary: colors.primary, secondary: colors.glass, danger: colors.glass }[kind];
  const fg = { primary: colors.onPrimary, secondary: colors.text, danger: colors.error }[kind];
  const edge = { primary: colors.primary, secondary: colors.border, danger: colors.border }[kind];
  return (
    <Pressy
      accessibilityRole="button"
      onPress={onPress}
      disabled={busy || disabled}
      style={({ pressed }) => [
        styles.button,
        { backgroundColor: bg, borderColor: edge, opacity: disabled ? 0.5 : pressed ? 0.85 : 1 },
        kind !== 'primary' ? { alignSelf: 'flex-start' } : null, // secondary / danger: compact pills; main actions stay full width
        kind === 'primary' && !disabled ? { boxShadow: colors.buttonGlow } : null,
      ]}>
      {busy ? (
        <ActivityIndicator color={fg} />
      ) : (
        <Text style={{ fontFamily: fonts.semibold, fontSize: 16, color: fg }}>{title}</Text>
      )}
    </Pressy>
  );
}

/** A labelled text box. Password boxes get an eye: press and hold it to see what you typed, let go to hide it. */
export function Field({ label, secureTextEntry, ...props }: TextInputProps & { label: string }) {
  const { colors } = useColors();
  const [peek, setPeek] = useState(false);
  const Icon = peek ? EyeOff : Eye;
  return (
    <View style={{ gap: spacing.xs }}>
      <T variant="muted">{label}</T>
      <View>
        <TextInput
          placeholderTextColor={colors.textMuted}
          autoCapitalize="none"
          autoCorrect={false}
          {...props}
          secureTextEntry={secureTextEntry && !peek}
          style={[
            styles.input,
            secureTextEntry && { paddingRight: 48 },
            { color: colors.text, backgroundColor: colors.inset, borderColor: colors.border, fontFamily: fonts.body },
          ]}
        />
        {secureTextEntry ? (
          <Pressy
            accessibilityRole="button"
            accessibilityLabel="Hold to show the password"
            onPressIn={() => setPeek(true)}
            onPressOut={() => setPeek(false)}
            hitSlop={8}
            style={styles.eye}>
            <Icon size={20} color={peek ? colors.primaryText : colors.textMuted} strokeWidth={1.8} />
          </Pressy>
        ) : null}
      </View>
    </View>
  );
}

/** Glass card: translucent surface, a faint gold edge and a soft shadow (the same on web and phones). */
export function Card({ children }: { children: ReactNode }) {
  const { colors } = useColors();
  return (
    <View style={[styles.card, { backgroundColor: colors.glass, borderColor: colors.glassBorder, boxShadow: colors.cardShadow }]}>
      {children}
    </View>
  );
}

/** Page title + a short muted line under it ("Today" · "33 posts · 6 recommended"). */
export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: ReactNode }) {
  const { colors } = useColors();
  return (
    <View style={styles.header}>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={{ fontFamily: fonts.heading, fontSize: 24, letterSpacing: -0.3, color: colors.text }}>{title}</Text>
        {subtitle ? <Text style={{ fontFamily: fonts.body, fontSize: 14, color: colors.textMuted }}>{subtitle}</Text> : null}
      </View>
      {right}
    </View>
  );
}

/** Pill buttons, e.g. Light · Dark · System. */
export function Choice<V extends string>({
  options,
  value,
  onChange,
}: {
  options: { label: string; value: V }[];
  value: V;
  onChange: (v: V) => void;
}) {
  const { colors } = useColors();
  return (
    <View style={styles.row}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <Pressy
            key={o.value}
            accessibilityRole="radio"
            accessibilityState={{ selected: on }}
            onPress={() => onChange(o.value)}
            style={[
              styles.pill,
              { backgroundColor: on ? colors.primarySoft : colors.glass, borderColor: on ? colors.primary : colors.border },
            ]}>
            <Text style={{ fontFamily: fonts.semibold, color: on ? colors.primaryText : colors.textMuted }}>{o.label}</Text>
          </Pressy>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flexGrow: 1, padding: spacing.lg, alignItems: 'center' },
  center: { justifyContent: 'center' },
  column: { width: '100%', maxWidth: 760, gap: spacing.lg },
  button: { minHeight: 46, borderRadius: radius.pill, borderWidth: 1, alignItems: 'center', justifyContent: 'center',
    paddingHorizontal: spacing.xl },
  eye: { position: 'absolute', right: 0, top: 0, bottom: 0, width: 48, alignItems: 'center', justifyContent: 'center' },
  input: { minHeight: 46, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: spacing.md, fontSize: 16 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.md },
  header: { flexDirection: 'row', alignItems: 'flex-end', gap: spacing.md, marginBottom: spacing.xs },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  pill: { borderWidth: 1, borderRadius: radius.pill, paddingVertical: spacing.sm, paddingHorizontal: spacing.lg },
});
