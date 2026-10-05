/** Vibration, only at five important moments (user's choice, 4 Oct): an email sent or scheduled, a job ticked, a list
 * refreshed by pulling, an action that failed, and a long-press menu. Phones only (browsers don't vibrate); never
 * throws (some phones have vibration off or no motor). */
import * as Haptics from 'expo-haptics';
import { Platform } from 'react-native';

const phone = Platform.OS !== 'web';
const safe = (fn: () => Promise<void>) => () => {
  if (phone) fn().catch(() => {});
};

export const haptic = {
  /** An email was sent or scheduled. */
  sent: safe(() => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)),
  /** A job was ticked / unticked. */
  select: safe(() => Haptics.selectionAsync()),
  /** Pull-to-refresh finished. */
  refreshed: safe(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)),
  /** Something the user asked for failed (distinct double buzz). */
  error: safe(() => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error)),
  /** A long-press opened a menu. */
  longPress: safe(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium)),
};
