/** Chat state + the events streamed by POST /chat/stream (pure, so it's tested with node --test). */

export type Card =
  | { type: 'jobs'; date: string; job_ids: number[]; note?: string }
  | { type: 'draft'; job_id: number; note?: string }
  | { type: 'confirm'; action_id: number; note?: string }
  | { type: 'sends'; send_ids: number[]; note?: string }
  | { type: 'posts'; post_ids: number[]; note?: string };

export type Msg = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  cards: Card[];
  error?: string;
  answeredBy?: string; // model picker: which model wrote this reply
  status?: string; // live only: what a tool is doing right now ("Reading Telegram…")
};

export type ChatState = { chatId: number | null; messages: Msg[]; streaming: boolean };

export type StreamEvent =
  | { type: 'chat'; chat_id: number | null; incognito?: boolean }
  | { type: 'text'; text: string }
  | { type: 'card'; card: Card }
  | { type: 'model'; model: string; label: string }
  | { type: 'status'; text: string }
  | { type: 'done'; chat_id: number | null; message_id?: number; title?: string }
  | { type: 'error'; message: string };

export function startTurn(s: ChatState, text: string, userId: string, assistantId: string): ChatState {
  return {
    ...s,
    streaming: true,
    messages: [
      ...s.messages,
      { id: userId, role: 'user', content: text, cards: [] },
      { id: assistantId, role: 'assistant', content: '', cards: [] },
    ],
  };
}

function updateLast(s: ChatState, change: (m: Msg) => Msg): ChatState {
  const last = s.messages.at(-1);
  return last ? { ...s, messages: [...s.messages.slice(0, -1), change(last)] } : s;
}

export function applyEvent(s: ChatState, e: StreamEvent): ChatState {
  switch (e.type) {
    case 'chat':
      return { ...s, chatId: e.chat_id };
    case 'text':
      return updateLast(s, (m) => ({ ...m, content: m.content + e.text, status: undefined }));
    case 'card':
      return updateLast(s, (m) => ({ ...m, cards: [...m.cards, e.card], status: undefined }));
    case 'status':
      return updateLast(s, (m) => ({ ...m, status: e.text }));
    case 'model':
      return updateLast(s, (m) => ({ ...m, answeredBy: e.label }));
    case 'done':
      return { ...updateLast(s, (m) => ({ ...m, status: undefined })), streaming: false, chatId: e.chat_id };
    case 'error':
      return { ...updateLast(s, (m) => ({ ...m, error: e.message, status: undefined })), streaming: false };
  }
}
