import assert from 'node:assert/strict';
import { test } from 'node:test';

import { monthGrid, parseTime, timeLabel, whenText } from './calendar.ts';

test('October 2026 starts on a Thursday (Mon-first weeks)', () => {
  const weeks = monthGrid(2026, 10);
  assert.deepEqual(weeks[0], [null, null, null, '2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04']);
  assert.equal(weeks.at(-1)?.filter(Boolean).at(-1), '2026-10-31');
  assert.ok(weeks.every((w) => w.length === 7));
});

test('typed times: 24h, am/pm, and nonsense', () => {
  assert.equal(parseTime('14:30'), '14:30');
  assert.equal(parseTime('9'), '09:00');
  assert.equal(parseTime('2:05 pm'), '14:05');
  assert.equal(parseTime('12 am'), '00:00');
  assert.equal(parseTime('12:15pm'), '12:15');
  assert.equal(parseTime('25:00'), null);
  assert.equal(parseTime('soon'), null);
});

test('what the server gets and what the user reads', () => {
  assert.equal(whenText('2026-10-03', '11:00'), '2026-10-03 11:00');
  assert.equal(timeLabel('2026-10-03', '14:30'), 'Sat 3 Oct, 2:30 PM');
});
