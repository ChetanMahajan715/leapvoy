/** Small shared motion pieces, so every screen moves the same way (web and phone). Animations follow the phone's
 * "remove animations" setting (Reanimated's default). */
import { useEffect, type ReactNode } from 'react';
import {
  Pressable,
  StyleSheet,
  View,
  type PressableProps,
  type PressableStateCallbackType,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import Animated, {
  Easing,
  FadeIn,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withTiming,
} from 'react-native-reanimated';

import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

/** A Pressable that gives a soft "push" on touch (97%, slightly dimmed; eased on the web). */
export function Pressy({
  style,
  children,
  scaleTo = 0.97,
  ...props
}: Omit<PressableProps, 'style'> & { style?: PressableProps['style']; scaleTo?: number }) {
  return (
    <Pressable
      {...props}
      style={(state: PressableStateCallbackType) => [
        typeof style === 'function' ? style(state) : style,
        styles.ease,
        state.pressed && !props.disabled ? { transform: [{ scale: scaleTo }], opacity: 0.88 } : null,
      ]}>
      {children}
    </Pressable>
  );
}

function Dot({ delay }: { delay: number }) {
  const { colors } = useColors();
  const y = useSharedValue(0);
  useEffect(() => {
    y.set(withDelay(delay, withRepeat(withSequence(
      withTiming(1, { duration: 300, easing: Easing.out(Easing.quad) }),
      withTiming(0, { duration: 300, easing: Easing.in(Easing.quad) }),
      withTiming(0, { duration: 240 }),
    ), -1)));
  }, [delay, y]);
  const style = useAnimatedStyle(() => ({ opacity: 0.35 + y.value * 0.65, transform: [{ translateY: -y.value * 4 }] }));
  return <Animated.View style={[styles.dot, { backgroundColor: colors.primary }, style]} />;
}

/** "The AI is working": three bouncing dots, plus what it is doing right now when a step takes a while. */
export function Thinking({ status }: { status?: string }) {
  const { colors } = useColors();
  return (
    <Animated.View entering={FadeIn.duration(200)} style={styles.thinking}>
      <View style={styles.dots}>
        <Dot delay={0} />
        <Dot delay={140} />
        <Dot delay={280} />
      </View>
      {status ? (
        <Animated.Text key={status} entering={FadeIn.duration(250)} style={[styles.status, { color: colors.textMuted }]}>
          {status}
        </Animated.Text>
      ) : null}
    </Animated.View>
  );
}

/** Grey placeholder shaped like the real content, with a light sweep, while a list loads. */
export function Shimmer({ height = 120, style }: { height?: number; style?: StyleProp<ViewStyle> }) {
  const { colors } = useColors();
  const t = useSharedValue(0);
  useEffect(() => {
    t.set(withRepeat(withTiming(1, { duration: 1200, easing: Easing.inOut(Easing.quad) }), -1, true));
  }, [t]);
  const anim = useAnimatedStyle(() => ({ opacity: 0.45 + t.value * 0.45 }));
  return (
    <Animated.View style={[styles.shimmer, { height, backgroundColor: colors.surfaceAlt }, anim, style]}>
      <View style={[styles.bar, { width: '55%', backgroundColor: colors.border }]} />
      <View style={[styles.bar, { width: '35%', backgroundColor: colors.border }]} />
      <View style={[styles.bar, { width: '80%', backgroundColor: colors.border, marginTop: 'auto' }]} />
    </Animated.View>
  );
}

/** Three placeholders, the usual "loading a list" view. */
export function ShimmerList({ count = 3, height }: { count?: number; height?: number }) {
  return (
    <View style={{ gap: spacing.md }} accessibilityLabel="Loading">
      {Array.from({ length: count }, (_, i) => (
        <Shimmer key={i} height={height} />
      ))}
    </View>
  );
}

/** Fades a block in when it first appears (lists, screens). */
export function FadeInBlock({ children, delay = 0, style }: { children: ReactNode; delay?: number; style?: StyleProp<ViewStyle> }) {
  return (
    <Animated.View entering={FadeIn.duration(220).delay(delay)} style={style}>
      {children}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  // web: the push eases in and out; phones apply it instantly (crisp, no lag)
  ease: { transitionProperty: 'transform, opacity', transitionDuration: '120ms' } as ViewStyle,
  thinking: { gap: spacing.xs, alignSelf: 'flex-start', paddingVertical: spacing.xs },
  dots: { flexDirection: 'row', gap: 6, height: 14, alignItems: 'flex-end' },
  dot: { width: 7, height: 7, borderRadius: 4 },
  status: { fontFamily: fonts.body, fontSize: 13 },
  shimmer: { borderRadius: radius.lg, padding: spacing.lg, gap: spacing.sm },
  bar: { height: 10, borderRadius: 5 },
});
