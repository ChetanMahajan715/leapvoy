/** Keyboard handling: react-native-keyboard-controller in our own app builds; React Native's built-ins in Expo Go
 * (which doesn't include that library's native code) and on web (the browser handles it). */
import type { ReactNode } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, TurboModuleRegistry, View, type ViewStyle } from 'react-native';

type KC = typeof import('react-native-keyboard-controller');

const kc: KC | null =
  Platform.OS !== 'web' && TurboModuleRegistry.get('KeyboardController')
    ? // eslint-disable-next-line @typescript-eslint/no-require-imports -- only loaded when its native part exists
      require('react-native-keyboard-controller')
    : null;

export function KeyboardRoot({ children }: { children: ReactNode }) {
  return kc ? <kc.KeyboardProvider>{children}</kc.KeyboardProvider> : children;
}

/** Lifts its content above the keyboard (chat composer). */
export function AvoidKeyboard({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  if (Platform.OS === 'web') return <View style={style}>{children}</View>;
  const Avoid = kc ? kc.KeyboardAvoidingView : KeyboardAvoidingView;
  return (
    <Avoid behavior="padding" style={style}>
      {children}
    </Avoid>
  );
}

/** A scroll view that keeps the focused input visible above the keyboard (forms). */
export const KeyboardScroll = kc ? kc.KeyboardAwareScrollView : ScrollView;
