import { useQuery } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import * as Device from 'expo-device';
import { Platform } from 'react-native';
import { create } from 'zustand';

import { api, connectAuth, tokens } from './api';
import { clearCache } from './query';
import { storage } from './storage';

const REFRESH_KEY = 'leapvoy.refresh';

type Tokens = { access_token: string; refresh_token: string };
type AuthState = {
  status: 'loading' | 'signedOut' | 'signedIn';
  accessToken: string | null;
  /** Just signed up → offer 2-step sign-in once (Set up / Skip). */
  offer2fa: boolean;
  init: () => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  /** Throws NeedsCode when the account has 2-step sign-in on and no code was given. */
  signIn: (email: string, password: string, code?: string) => Promise<void>;
  signOut: () => Promise<void>;
};

export class NeedsCode extends Error {}

export type Me = { id: string; email: string; totp_enabled: boolean; test_mode: boolean; delete_after: string | null };

/** The signed-in account (shared cache: sidebar, settings, send confirmations). */
export function useMe() {
  // staleTime 0: account state (2FA, test mode, deletion) must come from the server, not a saved copy
  return useQuery({ queryKey: ['me'], queryFn: async () => (await api.get<Me>('/me')).data, staleTime: 0 });
}

/** "Pixel 7" on phones, "Web (Windows)" on the laptop, shown in Settings → Logged-in devices. */
export function deviceName(): string {
  if (Platform.OS === 'web') return `Web${Device.osName ? ` (${Device.osName})` : ''}`;
  return Device.modelName ?? Device.deviceName ?? 'Android phone';
}

/** Forget the login and this account's saved data on the device. */
async function endSession() {
  await storage.remove(REFRESH_KEY);
  useAuth.setState({ accessToken: null, status: 'signedOut' });
  await clearCache();
}

async function renew(): Promise<string | null> {
  const refresh_token = await storage.get(REFRESH_KEY);
  if (!refresh_token) return null;
  try {
    const { data } = await api.post<Tokens>('/auth/refresh', { refresh_token });
    await storage.set(REFRESH_KEY, data.refresh_token);
    useAuth.setState({ accessToken: data.access_token, status: 'signedIn' });
    return data.access_token;
  } catch (e) {
    if (isAxiosError(e) && !e.response) {
      // Server unreachable (offline / Tailscale off): stay signed in and show the saved copy; renew on the next request.
      useAuth.setState({ status: 'signedIn' });
      return null;
    }
    await endSession(); // session ended or revoked
    return null;
  }
}

async function keep(tokens: Tokens) {
  await storage.set(REFRESH_KEY, tokens.refresh_token);
  useAuth.setState({ accessToken: tokens.access_token, status: 'signedIn' });
}

export const useAuth = create<AuthState>(() => ({
  status: 'loading',
  accessToken: null,
  offer2fa: false,
  init: async () => {
    // Signed in before → open right away with the saved copy and confirm the login in the background
    // (waiting for a slow or switched-off server kept the splash up for up to 20 s). A login that really ended still
    // lands on the sign-in screen, as soon as the server says so.
    if (await storage.get(REFRESH_KEY)) {
      useAuth.setState({ status: 'signedIn' });
      void tokens.renew();
    } else {
      useAuth.setState({ status: 'signedOut' });
    }
  },
  signUp: async (email, password) => {
    const { data } = await api.post<Tokens>('/auth/signup', { email, password, device_name: deviceName() });
    useAuth.setState({ offer2fa: true });
    await keep(data);
  },
  signIn: async (email, password, code) => {
    try {
      const body = { email, password, device_name: deviceName(), ...(code ? { code } : {}) };
      await keep((await api.post<Tokens>('/auth/login', body)).data);
    } catch (e) {
      if (isAxiosError(e) && e.response?.data?.detail === 'totp_required') throw new NeedsCode();
      throw e;
    }
  },
  signOut: async () => {
    try {
      await api.post('/auth/logout');
    } catch {
      // offline or already logged out: still forget the tokens here
    }
    await endSession();
  },
}));

connectAuth({ accessToken: () => useAuth.getState().accessToken, refresh: renew });
