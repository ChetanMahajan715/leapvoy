import { create } from 'zustand';

import { resetChat } from './chat-store';
import { storage } from './storage';

const SIDEBAR_KEY = 'leapvoy.sidebar';

type UI = {
  /** Laptop: sidebar hidden via the panel button (remembered). */
  sidebarCollapsed: boolean;
  /** Incognito chat: this conversation is not saved to history (resets with every new chat, like Claude). */
  incognito: boolean;
};

export const useUI = create<UI>(() => ({ sidebarCollapsed: false, incognito: false }));

export async function loadUI() {
  if ((await storage.get(SIDEBAR_KEY)) === 'collapsed') useUI.setState({ sidebarCollapsed: true });
}

export async function setSidebarCollapsed(collapsed: boolean) {
  useUI.setState({ sidebarCollapsed: collapsed });
  await storage.set(SIDEBAR_KEY, collapsed ? 'collapsed' : 'open');
}

/** Switching incognito on/off starts a fresh chat (a saved chat never turns private halfway). */
export function toggleIncognito() {
  resetChat();
  useUI.setState((s) => ({ incognito: !s.incognito }));
}

/** New chat (logo or button): leave incognito, like starting fresh. */
export function newChat() {
  resetChat();
  useUI.setState({ incognito: false });
}
