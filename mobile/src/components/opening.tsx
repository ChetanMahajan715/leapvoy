/** "Launch": the opening animation (about 1.7 s, once per app start; web: once per page load), approved by the user as a
 * browser preview on 7 Oct. Charge: the gold dot pops in and a ring pulses out. Leap: the path draws itself with a
 * soft light on its tip. Land: the paper plane glides in along the path, turns into the logo's pose, white flash.
 * Name: "Leapvoy" rises letter by letter. Shine: one gold glint crosses the name, then the app shows.
 * Every value is computed from one clock (ms). The plane's outline is recomputed point by point (no transformed
 * layers: Android hid one that started at scale 0). Geometry = brand/svg/app-icon.svg. A tap skips it; with
 * "remove animations" on, the still logo shows briefly instead. */
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
  withTiming,
  type SharedValue,
} from 'react-native-reanimated';
import Svg, { Circle, Defs, LinearGradient, Path, RadialGradient, Stop } from 'react-native-svg';

import { fonts, palette } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

const AnimatedPath = Animated.createAnimatedComponent(Path);
const AnimatedCircle = Animated.createAnimatedComponent(Circle);

const P = [[250, 742], [330, 520], [470, 400], [660, 352]];
const CURVE = 'M250 742 C 330 520, 470 400, 660 352';
const PLANE = [[-40, -120], [150, 0], [-40, 120], [0, 0]]; // white body
const WING = [[-40, -120], [0, 0], [-40, 120]]; // grey inner wing
const LENGTH = (() => {
  let len = 0;
  let prev = P[0];
  for (let i = 1; i <= 200; i++) {
    const t = i / 200;
    const u = 1 - t;
    const pt = [0, 1].map((k) => u ** 3 * P[0][k] + 3 * u * u * t * P[1][k] + 3 * u * t * t * P[2][k] + t ** 3 * P[3][k]);
    len += Math.hypot(pt[0] - prev[0], pt[1] - prev[1]);
    prev = pt;
  }
  return len;
})();
const END = 1700; // ms of the intro; then the curtain lifts
const SIZE = 104;
const VIEW = { x: 150, y: 180, w: 740, h: 660 }; // room for the whole plane (its tip was cut off before)
const WORD = 'Leapvoy'.split('');

const clamp = (x: number) => {
  'worklet';
  return Math.min(1, Math.max(0, x));
};
const span = (t: number, a: number, b: number) => {
  'worklet';
  return clamp((t - a) / (b - a));
};
const outCubic = (x: number) => {
  'worklet';
  return 1 - (1 - x) ** 3;
};
const inOut = (x: number) => {
  'worklet';
  return x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2;
};
const outBack = (x: number, k: number) => {
  'worklet';
  return 1 + (k + 1) * (x - 1) ** 3 + k * (x - 1) ** 2;
};
const bez = (u: number, i: number) => {
  'worklet';
  const m = 1 - u;
  return m * m * m * P[0][i] + 3 * m * m * u * P[1][i] + 3 * m * u * u * P[2][i] + u * u * u * P[3][i];
};
/** The plane at time t: from behind the end of the path, along its direction, into the logo's pose. */
const planePath = (t: number, pts: number[][]) => {
  'worklet';
  const l = span(t, 700, 1080);
  const e = outBack(l, 1.4);
  const x = 612 + 88 * e;
  const y = 368 - 38 * e;
  const a = ((-32 + 18 * outCubic(l)) * Math.PI) / 180;
  const s = 0.45 + 0.55 * e;
  const c = Math.cos(a);
  const n = Math.sin(a);
  return pts.map(([px, py], i) => `${i ? 'L' : 'M'}${x + s * (px * c - py * n)} ${y + s * (px * n + py * c)}`).join(' ') + ' Z';
};

let played = false; // once per app start (stays true while the app is in memory)

function Letter({ ch, i, clock, text }: { ch: string; i: number; clock: SharedValue<number>; text: string }) {
  const style = useAnimatedStyle(() => {
    const t = clock.value;
    const k = outCubic(span(t, 900 + i * 45, 1180 + i * 45));
    const glint = 1 - Math.min(1, Math.abs(span(t, 1300, 1650) * (WORD.length + 2) - 1 - i) / 1.2);
    return {
      opacity: k,
      transform: [{ translateY: (1 - k) * 14 }],
      color: interpolateColor(Math.max(0, glint), [0, 1], [text, palette.gold]),
    };
  });
  return <Animated.Text style={[styles.letter, style]}>{ch}</Animated.Text>;
}

export function Opening() {
  const { colors } = useColors();
  const reduced = useReducedMotion();
  const [show, setShow] = useState(!played);
  const clock = useSharedValue(0); // ms since the start
  const curtain = useSharedValue(1);

  useEffect(() => {
    if (!show) return;
    played = true;
    if (reduced) {
      clock.value = END;
      curtain.value = withDelay(400, withTiming(0, { duration: 250 }));
      const t = setTimeout(() => setShow(false), 700);
      return () => clearTimeout(t);
    }
    clock.value = withTiming(END, { duration: END, easing: Easing.linear });
    curtain.value = withDelay(END + 80, withTiming(0, { duration: 260, easing: Easing.bezier(0.4, 0, 0.2, 1) }));
    const t = setTimeout(() => setShow(false), END + 380);
    return () => clearTimeout(t);
  }, [show, reduced, clock, curtain]);

  // Charge
  const dotProps = useAnimatedProps(() => ({ r: 56 * Math.max(0, outBack(span(clock.value, 0, 320), 2.2)) }));
  const ringProps = useAnimatedProps(() => {
    const r = span(clock.value, 60, 520);
    return { r: 56 + 90 * outCubic(r), opacity: r > 0 && r < 1 ? 0.7 * (1 - r) : 0 };
  });
  // Leap
  const curveProps = useAnimatedProps(() => ({ strokeDashoffset: (LENGTH + 70) * (1 - inOut(span(clock.value, 200, 820))) }));
  const cometProps = useAnimatedProps(() => {
    const d = inOut(span(clock.value, 200, 820));
    const fade = d > 0 && d < 1 ? 0.85 : Math.max(0, 0.85 * (1 - span(clock.value, 820, 980)));
    return { cx: bez(d, 0), cy: bez(d, 1), opacity: d > 0 ? fade : 0 };
  });
  // Land
  const planeProps = useAnimatedProps(() => ({ d: planePath(clock.value, PLANE), opacity: clamp(span(clock.value, 700, 1080) * 3) }));
  const wingProps = useAnimatedProps(() => ({ d: planePath(clock.value, WING), opacity: clamp(span(clock.value, 700, 1080) * 3) }));
  const burstProps = useAnimatedProps(() => {
    const f = span(clock.value, 980, 1260);
    return { r: 40 + 110 * outCubic(f), opacity: f > 0 && f < 1 ? 0.55 * (1 - f) : 0 };
  });
  const curtainStyle = useAnimatedStyle(() => ({ opacity: curtain.value }));

  if (!show) return null;
  const skip = () => {
    curtain.set(withTiming(0, { duration: 180 })); // .set(): the React Compiler-safe way to write a shared value
    setTimeout(() => setShow(false), 200);
  };
  const height = (SIZE * VIEW.h) / VIEW.w;
  return (
    <Animated.View style={[StyleSheet.absoluteFill, styles.curtain, { backgroundColor: colors.background }, curtainStyle]}>
      <Pressable accessibilityLabel="Skip the opening animation" onPress={skip} style={styles.center}>
        <View style={styles.lockup}>
          <Svg width={SIZE} height={height} viewBox={`${VIEW.x} ${VIEW.y} ${VIEW.w} ${VIEW.h}`}>
            <Defs>
              <LinearGradient id="arc" x1="0" y1="1" x2="1" y2="0">
                <Stop offset="0" stopColor={palette.spark} />
                <Stop offset="1" stopColor={palette.amber} />
              </LinearGradient>
              <RadialGradient id="soft">
                <Stop offset="0" stopColor={palette.spark} stopOpacity={0.9} />
                <Stop offset="1" stopColor={palette.spark} stopOpacity={0} />
              </RadialGradient>
              <RadialGradient id="flash">
                <Stop offset="0" stopColor={colors.logoPlane} stopOpacity={0.9} />
                <Stop offset="1" stopColor={colors.logoPlane} stopOpacity={0} />
              </RadialGradient>
            </Defs>
            <AnimatedCircle cx={250} cy={742} fill="none" stroke={palette.gold} strokeWidth={8} animatedProps={ringProps} />
            <AnimatedPath d={CURVE} fill="none" stroke="url(#arc)" strokeWidth={66} strokeLinecap="round"
              strokeDasharray={[LENGTH + 70, LENGTH + 70]} animatedProps={curveProps} />
            <AnimatedCircle r={70} fill="url(#soft)" animatedProps={cometProps} />
            <AnimatedCircle cx={250} cy={742} fill={palette.spark} animatedProps={dotProps} />
            <AnimatedCircle cx={760} cy={300} fill="url(#flash)" animatedProps={burstProps} />
            <AnimatedPath d={planePath(0, PLANE)} fill={colors.logoPlane} animatedProps={planeProps} />
            <AnimatedPath d={planePath(0, WING)} fill={colors.logoWing} animatedProps={wingProps} />
          </Svg>
          <View style={styles.word}>
            {WORD.map((ch, i) => (
              <Letter key={i} ch={ch} i={i} clock={clock} text={colors.text} />
            ))}
          </View>
        </View>
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  curtain: { zIndex: 1000 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  lockup: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  word: { flexDirection: 'row' },
  letter: { fontFamily: fonts.heading, fontSize: 40, letterSpacing: -0.5 },
});
