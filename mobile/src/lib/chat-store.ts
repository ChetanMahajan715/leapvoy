/** The open chat: streams replies from POST /chat/stream (SSE over XHR, same code on web and Android). */
import EventSource from 'react-native-sse';
import { create } from 'zustand';

import { api, API_URL, tokens } from './api';
import { applyEvent, startTurn, type ChatState, type Msg, type StreamEvent } from './chat-events';
import { usePicks } from './models';
import { queryClient } from './query';

export const useChat = create<ChatState>(() => ({ chatId: null, messages: [], streaming: false }));

let stop: (() => void) | null = null; // ends the running stream (new chat / other chat opened)
let seq = 0;

export function resetChat() {
  stop?.();
  useChat.setState({ chatId: null, messages: [], streaming: false });
}

/** Load a saved chat (sidebar Recents). */
export async function openChat(id: number) {
  if (useChat.getState().chatId === id) return;
  resetChat();
  useChat.setState({ chatId: id });
  type Saved = (Omit<Msg, 'id'> & { id: number })[];
  const queryKey = ['chat', id, 'messages'];
  let data: Saved;
  try {
    data = await queryClient.fetchQuery({
      queryKey,
      queryFn: async () => (await api.get<Saved>(`/chats/${id}/messages`)).data,
      staleTime: 0, // always fresh when online
    });
  } catch (e) {
    const saved = queryClient.getQueryData<Saved>(queryKey); // offline: the copy saved on this device
    if (!saved) throw e;
    data = saved;
  }
  if (useChat.getState().chatId === id) useChat.setState({ messages: data.map((m) => ({ ...m, id: String(m.id) })) });
}

/** Resolves when the reply is finished (or failed). Incognito: the app sends the turns, the server keeps nothing. */
export function sendMessage(text: string, incognito: boolean): Promise<void> {
  const before = useChat.getState();
  if (before.streaming) return Promise.resolve();
  const history = incognito ? before.messages.slice(-40).map(({ role, content, cards }) => ({ role, content, cards })) : [];
  const model = usePicks.getState().chat; // model picker (null = Auto)
  const body = JSON.stringify({ message: text, chat_id: incognito ? null : before.chatId, incognito, history, model });
  seq += 1;
  useChat.setState(startTurn(before, text, `u${seq}`, `a${seq}`));
  const apply = (e: StreamEvent) => useChat.setState((s) => applyEvent(s, e));

  return new Promise((resolve) => {
    let over = false; // finished, or stopped by a new chat while renewing the token
    const connect = (retried: boolean) => {
      const es = new EventSource(`${API_URL}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${tokens.current()}` },
        body,
        pollingInterval: 0, // one request, never reconnect
      });
      const close = () => {
        es.removeAllEventListeners();
        es.close();
      };
      const finish = () => {
        close();
        over = true;
        stop = null;
        resolve();
      };
      stop = finish;
      es.addEventListener('message', (m) => {
        if (!m.data) return;
        const e = JSON.parse(m.data) as StreamEvent;
        apply(e);
        if (e.type === 'done' || e.type === 'error') finish();
      });
      es.addEventListener('error', async (err) => {
        const status = err.type === 'error' ? err.xhrStatus : 0;
        close();
        if (status === 401 && !retried && (await tokens.renew()) && !over) return connect(true);
        if (over) return;
        apply({
          type: 'error',
          message: status === 404 ? 'This chat no longer exists.' : "Can't reach Leapvoy. Check the connection and try again.",
        });
        finish();
      });
    };
    connect(false);
  });
}
