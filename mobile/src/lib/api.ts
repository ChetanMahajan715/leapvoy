import { create, isAxiosError, type AxiosError, type InternalAxiosRequestConfig } from 'axios';

import { storage } from './storage';

// Default from the build (EXPO_PUBLIC_API_URL: the laptop while testing, "/api" for the server's web app). The APK can
// point anywhere without a rebuild: sign-in → "Server" (the laptop now, the Oracle server later), saved on the device.
const DEFAULT_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';
const SERVER_KEY = 'leapvoy.server';
export let API_URL = DEFAULT_URL;

export const api = create({ baseURL: API_URL, timeout: 20000 });

export function setApiUrl(url: string | null) {
  API_URL = (url || DEFAULT_URL).trim().replace(/\/+$/, '');
  api.defaults.baseURL = API_URL;
}

/** Before signing in: the address chosen on this device, if any. */
export async function loadServer() {
  setApiUrl(await storage.get(SERVER_KEY));
}

export async function saveServer(url: string | null) {
  setApiUrl(url);
  if (url && API_URL !== DEFAULT_URL) await storage.set(SERVER_KEY, API_URL);
  else await storage.remove(SERVER_KEY);
}

export const defaultServer = () => DEFAULT_URL;

type Hooks = {
  accessToken: () => string | null;
  refresh: () => Promise<string | null>; // new access token, or null → signed out
};
let hooks: Hooks = { accessToken: () => null, refresh: async () => null };
let refreshing: Promise<string | null> | null = null;

/** Called once by the auth store, so the API client can read and renew tokens. */
export function connectAuth(h: Hooks) {
  hooks = h;
}

api.interceptors.request.use(async (config) => {
  // Right after opening, the login is still being confirmed: wait for it instead of failing with 401 first
  // (never for /auth/ itself: the confirmation request would wait for itself).
  const token = hooks.accessToken() ?? (refreshing && !config.url?.startsWith('/auth/') ? await refreshing : null);
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

/** For requests axios can't make (chat streaming, image upload): the token, and one shared renewal. */
export const tokens = {
  current: () => hooks.accessToken(),
  renew: () => (refreshing ??= hooks.refresh().finally(() => (refreshing = null))),
};

// Access tokens live 15 min: on a 401, renew once (shared by parallel requests) and retry.
api.interceptors.response.use(undefined, async (error: AxiosError) => {
  const config = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined;
  if (error.response?.status !== 401 || !config || config._retried || config.url?.startsWith('/auth/')) {
    throw error;
  }
  config._retried = true;
  const token = await tokens.renew();
  if (!token) throw error;
  config.headers.Authorization = `Bearer ${token}`;
  return api(config);
});

/** A readable message from any API error (FastAPI puts it in `detail`) or our own thrown Error. */
/** A 409 {"confirm": [...]} answer: not an error but things the user should know (e.g. "you emailed this address
 * 3 days ago") before deciding to send anyway. null for anything else. */
export function confirmNotes(e: unknown): string[] | null {
  if (!isAxiosError(e) || e.response?.status !== 409) return null;
  const detail = (e.response.data as { detail?: { confirm?: string[] } })?.detail;
  return Array.isArray(detail?.confirm) ? detail.confirm : null;
}

export function errorMessage(e: unknown, fallback = 'Something went wrong. Please try again.'): string {
  if (isAxiosError(e)) {
    if (!e.response) return `Can't reach Leapvoy at ${API_URL}. Is the server running (and Tailscale on)?`;
    if (e.response.status === 429) return 'Too many attempts. Wait a minute and try again.';
    const detail = (e.response.data as { detail?: unknown })?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return 'Please check the fields (password needs at least 10 characters).';
    return fallback;
  }
  return e instanceof Error && e.message ? e.message : fallback;
}
