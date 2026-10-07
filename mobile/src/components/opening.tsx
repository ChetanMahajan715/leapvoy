/** "The Leap": the opening animation (about 1.6 s, once per app start; web: once per page load). The brand arrow's dot
 * charges up, the curve draws itself with a soft gold trail, the arrowhead lands with a spring, "Leapvoy" rises in letter
 * by letter with a gold glint rippling through, then everything gives way to the app, which loaded underneath meanwhile.
 * A tap skips it; with "remove animations" on, a still logo shows briefly instead. Geometry = brand/svg/notification-icon.svg. */
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import Animated, {
  Easing,
  interpolateColor,
  useAnimatedProps,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
  type SharedValue,
} from 'react-native-reanimated';
import Svg, { Circle, Defs, G, LinearGradient, Path, Stop } from 'react-native-svg';

import { fonts, palette } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

const AnimatedPath = Animated.createAnimatedComponent(Path);
const AnimatedCircle = Animated.createAnimatedComponent(Circle);

const CURVE = 'M250 742 C 330 520, 470 400, 660 352';
const HEAD = 'M-40 -120 L150 0 L-40 120 L0 0 Z';
const LENGTH = (() => {
  // the curve's length, so the "drawing" dash is exactly as long as the line
  const p = [[250, 742], [330, 520], [470, 400], [660, 352]];
  let len = 0;
  let prev = p[0];
  for (let i = 1; i <= 200; i++) {
    const t = i / 200;
    const u = 1 - t;
    const pt = [0, 1].map((k) => u ** 3 * p[0][k] + 3 * u * u * t * p[1][k] + 3 * u * t * t * p[2][k] + t ** 3 * p[3][k]);
    len += Math.hypot(pt[0] - prev[0], pt[1] - prev[1]);
    prev = pt;
  }
  return len;
})();
const HIDDEN = LENGTH + 80; // dash offset that hides the line, round caps included
const SIZE = 92;
const WORD = 'Leapvoy'.split('');
const ease = Easing.bezier(0.65, 0, 0.35, 1);
const RISE_END = 0.32 + (WORD.length - 1) * 0.035; // seconds until the last letter is up
const GLINT_END = 0.42 + (WORD.length - 1) * 0.05;

let played = false; // once per app start (stays true while the app is in memory)

function Letter({ ch, i, rise, glint, text }: { ch: string; i: number; rise: SharedValue<number>; glint: SharedValue<number>; text: string }) {
  const style = useAnimatedStyle(() => {
    // rise / glint count seconds: each letter starts 35 ms (rise) / 50 ms (glint) after the previous one
    const r = 1 - (1 - Math.min(Math.max((rise.value - i * 0.035) / 0.32, 0), 1)) ** 3;
    const g = Math.min(Math.max((glint.value - i * 0.05) / 0.42, 0), 1);
    const peak = 1 - Math.abs(g * 2 - 1); // 0 → 1 → 0: the glint passing through this letter
    return {
      opacity: r,
      transform: [{ translateY: (1 - r) * 14 }],
      color: interpolateColor(peak, [0, 1], [text, palette.spark]),
    };
  });
  return <Animated.Text style={[styles.letter, style]}>{ch}</Animated.Text>;
}

export function Opening() {
  const { colors } = useColors();
  const reduced = useReducedMotion();
  const [show, setShow] = useState(!played);
  const dot = useSharedValue(0);
  const pulse = useSharedValue(0);
  const draw = useSharedValue(0);
  const head = useSharedValue(0);
  const rise = useSharedValue(0);
  const glint = useSharedValue(0);
  const away = useSharedValue(0);
  const curtain = useSharedValue(1);

  useEffect(() => {
    if (!show) return;
    played = true;
    if (reduced) {
      dot.value = draw.value = head.value = 1;
      rise.value = RISE_END;
      curtain.value = withDelay(400, withTiming(0, { duration: 250 }));
      const t = setTimeout(() => setShow(false), 700);
      return () => clearTimeout(t);
    }
    dot.value = withDelay(20, withSpring(1, { damping: 9, stiffness: 260 }));
    pulse.value = withDelay(50, withTiming(1, { duration: 500, easing: Easing.out(Easing.quad) }));
    draw.value = withDelay(200, withTiming(1, { duration: 400, easing: ease }));
    head.value = withDelay(550, withSpring(1, { damping: 7, stiffness: 240 }));
    rise.value = withDelay(680, withTiming(RISE_END, { duration: RISE_END * 1000, easing: Easing.linear }));
    glint.value = withDelay(1000, withTiming(GLINT_END, { duration: GLINT_END * 1000, easing: Easing.linear }));
    away.value = withDelay(1350, withTiming(1, { duration: 300, easing: Easing.bezier(0.4, 0, 0.2, 1) }));
    curtain.value = withDelay(1450, withTiming(0, { duration: 350 }));
    const t = setTimeout(() => setShow(false), 1850);
    return () => clearTimeout(t);
  }, [show, reduced, dot, pulse, draw, head, rise, glint, away, curtain]);

  const dotProps = useAnimatedProps(() => ({ r: 62 * dot.value }));
  const pulseProps = useAnimatedProps(() => ({ r: 62 * (0.6 + pulse.value * 2), opacity: (1 - pulse.value) * 0.8 }));
  const curveProps = useAnimatedProps(() => ({ strokeDashoffset: HIDDEN * (1 - draw.value) }));
  const trailProps = useAnimatedProps(() => ({
    strokeDashoffset: HIDDEN * (1 - draw.value),
    opacity: 0.28 - 0.18 * Math.max(0, draw.value - 0.6) / 0.4,
  }));
  // the arrowhead lives in the same drawing as the curve and animates the same way (Android didn't draw a separate
  // layer that started at scale 0): it fades in while a gold glow around it shrinks away, so it seems to land
  const headProps = useAnimatedProps(() => ({ opacity: Math.min(1, head.value * 2) }));
  const headGlowProps = useAnimatedProps(() => ({
    strokeWidth: Math.max(0, 70 * (1 - head.value)),
    opacity: head.value > 0.01 ? Math.max(0, 0.5 * (1 - head.value)) : 0,
  }));
  const lockupStyle = useAnimatedStyle(() => ({ opacity: 1 - away.value, transform: [{ scale: 1 - away.value * 0.06 }] }));
  const curtainStyle = useAnimatedStyle(() => ({ opacity: curtain.value }));

  if (!show) return null;
  const skip = () => {
    curtain.set(withTiming(0, { duration: 180 })); // .set(): the React Compiler-safe way to write a shared value
    setTimeout(() => setShow(false), 200);
  };
  const viewBox = '140 260 640 600';
  const height = (SIZE * 600) / 640;
  return (
    <Animated.View style={[StyleSheet.absoluteFill, styles.curtain, { backgroundColor: colors.background }, curtainStyle]}>
      <Pressable accessibilityLabel="Skip the opening animation" onPress={skip} style={styles.center}>
        <Animated.View style={[styles.lockup, lockupStyle]}>
          <View style={{ width: SIZE, height }}>
            <Svg width={SIZE} height={height} viewBox={viewBox} style={StyleSheet.absoluteFill}>
              <Defs>
                <LinearGradient id="leap" x1="0" y1="1" x2="1" y2="0">
                  <Stop offset="0" stopColor={colors.primary} />
                  <Stop offset="1" stopColor={palette.spark} />
                </LinearGradient>
              </Defs>
              <AnimatedCircle cx={250} cy={742} fill="none" stroke={palette.spark} strokeWidth={10} animatedProps={pulseProps} />
              <AnimatedPath d={CURVE} fill="none" stroke={palette.spark} strokeWidth={130} strokeLinecap="round"
                strokeDasharray={[LENGTH, HIDDEN * 2]} animatedProps={trailProps} />
              <AnimatedPath d={CURVE} fill="none" stroke="url(#leap)" strokeWidth={72} strokeLinecap="round"
                strokeDasharray={[LENGTH, HIDDEN * 2]} animatedProps={curveProps} />
              <AnimatedCircle cx={250} cy={742} fill="url(#leap)" animatedProps={dotProps} />
              <G transform="translate(700 330) rotate(-14)">
                <AnimatedPath d={HEAD} fill="none" stroke={palette.spark} strokeLinejoin="round" animatedProps={headGlowProps} />
                <AnimatedPath d={HEAD} fill={palette.spark} animatedProps={headProps} />
              </G>
            </Svg>
          </View>
          <View style={styles.word}>
            {WORD.map((ch, i) => (
              <Letter key={i} ch={ch} i={i} rise={rise} glint={glint} text={colors.text} />
            ))}
          </View>
        </Animated.View>
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  curtain: { zIndex: 1000 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  lockup: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  word: { flexDirection: 'row' },
  letter: { fontFamily: fonts.heading, fontSize: 40, letterSpacing: -0.5 },
});
