import assert from 'node:assert/strict';
import { test } from 'node:test';

import { verdictLabel } from './labels.ts';

test('professional fit names', () => {
  assert.deepEqual(
    ['TOP PRIORITY', 'STRONG MATCH', 'APPLY', 'MAYBE', 'SKIP', null].map(verdictLabel),
    ['Excellent fit', 'Strong fit', 'Good fit', 'Possible fit', 'Not a fit', null],
  );
});
