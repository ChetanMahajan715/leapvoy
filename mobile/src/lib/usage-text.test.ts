import assert from 'node:assert/strict';
import { test } from 'node:test';

import { usageText, type ModelInfo } from './usage-text.ts';

const base: ModelInfo = {
  id: 'groq/openai/gpt-oss-20b', label: 'GPT-OSS 20B', maker: 'OpenAI · on Groq', note: '', used_today: 0,
  left_pct: 100, state: 'ok', back_at: null,
};

test('Groq models show the share left today', () => {
  assert.equal(usageText({ ...base, left_pct: 72 }), '72% left today');
  assert.equal(usageText({ ...base, left_pct: 12, state: 'low' }), 'Only 12% left today');
});

test('no usage left, with when it comes back (local time)', () => {
  const back = new Date(2026, 9, 1, 21, 40).toISOString();
  assert.equal(usageText({ ...base, left_pct: 0, state: 'empty', back_at: back }), 'No usage left, back at 9:40 PM');
  assert.equal(usageText({ ...base, left_pct: 0, state: 'empty', back_at: null }), 'No usage left');
});

test('providers without a published free limit show what was used', () => {
  const mistral = { ...base, left_pct: null, used_today: 12_345 };
  assert.equal(usageText(mistral), '12.3k tokens used today');
  assert.equal(usageText({ ...mistral, used_today: 0 }), 'Not used today');
  assert.equal(usageText({ ...mistral, state: 'busy' }), 'Busy for a moment. Try again shortly');
});

test('after the wait some usage is coming back', () => {
  assert.equal(usageText({ ...base, left_pct: 0, state: 'low' }), 'Almost used up. Some usage is coming back');
});
