/** Phone notifications (the installed Android app). The server sends them through Expo's push service; this registers
 * the phone after sign-in and opens the right screen when one is tapped. The web app has the same notifications in its
 * inbox (Notifications screen), since browsers can't receive these pushes. */
import * as Notifications from 'expo-notifications';
import { router } from 'expo-router';
import { useEffect } from 'react';
import { Platform } from 'react-native';

import { api } from './api';
import { markRead, noteTarget, type Note } from './notifications';
import { queryClient } from './query';

const native = Platform.OS === 'android';

// Android categories: the user can mute any of them in the phone's own settings too (ids match the server's channelId)
const CHANNELS: [string, string][] = [
  ['jobs', 'New jobs'],
  ['replies', 'Replies to your emails'],
  ['sending', 'Sending'],
  ['account', 'Account and security'],
];

if (native) {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldPlaySound: true,
      shouldSetBadge: false,
      shouldShowBanner: true,
      shouldShowList: true,
    }),
  });
}

/** After sign-in: channels, permission (asked once), then this phone's push token to the server. Never throws. */
export async function registerPush(): Promise<void> {
  if (!native) return;
  try {
    for (const [id, name] of CHANNELS) {
      await Notifications.setNotificationChannelAsync(id, { name, importance: Notifications.AndroidImportance.HIGH });
    }
    let { status } = await Notifications.getPermissionsAsync();
    if (status !== 'granted') status = (await Notifications.requestPermissionsAsync()).status;
    if (status !== 'granted') {
      await api.post('/push-token', { token: null }); // turned off: the server stops pushing to this phone
      return;
    }
    const { data } = await Notifications.getExpoPushTokenAsync(); // project id comes from the EAS build
    await api.post('/push-token', { token: data });
  } catch {
    // Expo Go (no push on Android since SDK 53) or offline: the in-app inbox still has every notification
  }
}

function open(response: Notifications.NotificationResponse | null) {
  if (!response) return;
  const data = response.notification.request.content.data as Note['data'] & { id?: number };
  if (typeof data?.id === 'number') {
    markRead([data.id])
      .then(() => queryClient.invalidateQueries({ queryKey: ['notifications'] }))
      .catch(() => {});
  }
  const target = noteTarget(data ?? {});
  if (target) router.navigate(target);
}

/** In the signed-in app: register once, and follow taps (also the tap that opened the app). */
export function usePush() {
  useEffect(() => {
    if (!native) return;
    void registerPush();
    Notifications.getLastNotificationResponseAsync().then(open).catch(() => {});
    const sub = Notifications.addNotificationResponseReceivedListener(open);
    return () => sub.remove();
  }, []);
}
