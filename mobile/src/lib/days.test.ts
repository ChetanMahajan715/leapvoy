import assert from 'node:assert/strict';
import { test } from 'node:test';

import { dayTitle, groupByIstDay, istDay, istToday, shiftDay } from './days.ts';

test('today is the India date, even when UTC is still yesterday', () => {
  assert.equal(istToday(new Date('2026-09-30T20:00:00Z')), '2026-10-01'); // 1:30 AM IST
  assert.equal(istToday(new Date('2026-09-30T18:00:00Z')), '2026-09-30'); // 11:30 PM IST
});

test('days move across month ends', () => {
  assert.equal(shiftDay('2026-10-01', -1), '2026-09-30');
  assert.equal(shiftDay('2026-12-31', 1), '2027-01-01');
});

test('titles: Today, Yesterday, then a date', () => {
  assert.equal(dayTitle('2026-10-01', '2026-10-01'), 'Today');
  assert.equal(dayTitle('2026-09-30', '2026-10-01'), 'Yesterday');
  assert.equal(dayTitle('2026-09-29', '2026-10-01'), 'Tue 29 Sep');
});

test('an instant belongs to its India day; Tomorrow is named too', () => {
  assert.equal(istDay('2026-10-02T19:00:00Z'), '2026-10-03'); // 12:30 AM IST
  assert.equal(dayTitle('2026-10-04', '2026-10-03'), 'Tomorrow');
});

test('emails grouped by India day, newest or oldest first', () => {
  const sends = [
    { id: 1, at: '2026-10-02T04:00:00Z' }, // 2 Oct, 9:30 AM IST
    { id: 2, at: '2026-10-02T19:00:00Z' }, // 3 Oct, 12:30 AM IST
    { id: 3, at: '2026-10-02T10:00:00Z' }, // 2 Oct, 3:30 PM IST
  ];
  const newest = groupByIstDay(sends, (s) => s.at, 'newest');
  assert.deepEqual(newest.map((g) => [g.day, g.items.map((s) => s.id)]), [['2026-10-03', [2]], ['2026-10-02', [3, 1]]]);
  const oldest = groupByIstDay(sends, (s) => s.at, 'oldest');
  assert.deepEqual(oldest.map((g) => [g.day, g.items.map((s) => s.id)]), [['2026-10-02', [1, 3]], ['2026-10-03', [2]]]);
});
