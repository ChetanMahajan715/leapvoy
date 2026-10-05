import assert from 'node:assert/strict';
import { test } from 'node:test';

import { dayLabel, groupByDay } from './group-by-day.ts';

const NOW = new Date(2026, 8, 30, 21, 0); // Wed 30 Sep 2026, 9 PM (local time)

test('today, yesterday, then dates like Claude', () => {
  assert.equal(dayLabel(new Date(2026, 8, 30, 0, 5), NOW), 'Today');
  assert.equal(dayLabel(new Date(2026, 8, 29, 23, 59), NOW), 'Yesterday');
  assert.equal(dayLabel(new Date(2026, 8, 26, 12, 0), NOW), 'Sep 26');
  assert.equal(dayLabel(new Date(2025, 11, 31, 12, 0), NOW), 'Dec 31, 2025');
});

test('groups newest first, keeping order inside a day', () => {
  const chats = [
    { id: 1, updated_at: new Date(2026, 8, 26, 10).toISOString() },
    { id: 2, updated_at: new Date(2026, 8, 30, 9).toISOString() },
    { id: 3, updated_at: new Date(2026, 8, 30, 18).toISOString() },
    { id: 4, updated_at: new Date(2026, 8, 29, 8).toISOString() },
  ];
  const groups = groupByDay(chats, NOW);
  assert.deepEqual(
    groups.map((g) => [g.label, g.items.map((c) => c.id)]),
    [
      ['Today', [3, 2]],
      ['Yesterday', [4]],
      ['Sep 26', [1]],
    ],
  );
});

test('no chats → no groups', () => {
  assert.deepEqual(groupByDay([], NOW), []);
});
