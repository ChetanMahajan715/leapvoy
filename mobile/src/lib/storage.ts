import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

// Phones: Android Keystore (expo-secure-store). Web: localStorage, the web app is only reachable over Tailscale.
export const storage = {
  async get(key: string): Promise<string | null> {
    if (Platform.OS === 'web') {
      try {
        return globalThis.localStorage?.getItem(key) ?? null;
      } catch {
        return null;
      }
    }
    return SecureStore.getItemAsync(key);
  },
  async set(key: string, value: string): Promise<void> {
    if (Platform.OS === 'web') {
      try {
        globalThis.localStorage?.setItem(key, value);
      } catch {
        // private mode / blocked storage: stay signed in for this tab only
      }
      return;
    }
    await SecureStore.setItemAsync(key, value);
  },
  async remove(key: string): Promise<void> {
    if (Platform.OS === 'web') {
      try {
        globalThis.localStorage?.removeItem(key);
      } catch {
        // nothing stored
      }
      return;
    }
    await SecureStore.deleteItemAsync(key);
  },
};
