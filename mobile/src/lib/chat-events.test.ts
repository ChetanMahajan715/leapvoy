import assert from 'node:assert/strict';
import { test } from 'node:test';

import { applyEvent, startTurn, type ChatState } from './chat-events.ts';

const empty: ChatState = { chatId: null, messages: [], streaming: false };

test('a turn: user message + streaming assistant text + card + done', () => {
  let s = startTurn(empty, 'show jobs', 'u1', 'a1');
  assert.equal(s.streaming, true);
  s = applyEvent(s, { type: 'chat', chat_id: 7 });
  s = applyEvent(s, { type: 'text', text: '9 jobs' });
  s = applyEvent(s, { type: 'card', card: { type: 'jobs', date: '2026-09-29', job_ids: [14], note: 'x' } });
  s = applyEvent(s, { type: 'text', text: ' today.' });
  s = applyEvent(s, { type: 'done', chat_id: 7 });
  assert.equal(s.chatId, 7);
  assert.equal(s.streaming, false);
  assert.deepEqual(
    s.messages.map((m) => [m.role, m.content, m.cards.length]),
    [['user', 'show jobs', 0], ['assistant', '9 jobs today.', 1]],
  );
});

test('an error ends the turn and is shown on the assistant message', () => {
  let s = startTurn(empty, 'hi', 'u1', 'a1');
  s = applyEvent(s, { type: 'error', message: 'The free AI is busy' });
  assert.equal(s.streaming, false);
  assert.equal(s.messages[1].error, 'The free AI is busy');
});

test('earlier messages are not touched by a new turn', () => {
  let s = startTurn(empty, 'one', 'u1', 'a1');
  s = applyEvent(applyEvent(s, { type: 'text', text: 'first' }), { type: 'done', chat_id: null });
  s = applyEvent(startTurn(s, 'two', 'u2', 'a2'), { type: 'text', text: 'second' });
  assert.deepEqual(s.messages.map((m) => m.content), ['one', 'first', 'two', 'second']);
});

test('the reply remembers which model answered', () => {
  let s = startTurn(empty, 'hi', 'u1', 'a1');
  s = applyEvent(s, { type: 'model', model: 'mistral/ministral-14b-latest', label: 'Ministral 14B' });
  s = applyEvent(s, { type: 'text', text: 'Hello' });
  assert.equal(s.messages[1].answeredBy, 'Ministral 14B');
});

test('a live status line shows while a tool works and goes away when the answer arrives', () => {
  let s = startTurn(empty, 'yesterday', 'u1', 'a1');
  s = applyEvent(s, { type: 'status', text: 'Reading Telegram…' });
  assert.equal(s.messages[1].status, 'Reading Telegram…');
  s = applyEvent(s, { type: 'card', card: { type: 'jobs', date: '2026-10-03', job_ids: [1] } });
  assert.equal(s.messages[1].status, undefined);
  s = applyEvent(applyEvent(s, { type: 'status', text: 'Writing…' }), { type: 'error', message: 'busy' });
  assert.equal(s.messages[1].status, undefined);
});
