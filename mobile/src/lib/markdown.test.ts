import assert from 'node:assert/strict';
import { test } from 'node:test';

import { parseMarkdown } from './markdown.ts';

test('paragraphs with bold and code', () => {
  assert.deepEqual(parseMarkdown('**Allvest** fits `81/100`.\n\nSecond.'), [
    { kind: 'p', spans: [{ text: 'Allvest', bold: true }, { text: ' fits ' }, { text: '81/100', code: true }, { text: '.' }] },
    { kind: 'p', spans: [{ text: 'Second.' }] },
  ]);
});

test('bullet and numbered lists become list items', () => {
  assert.deepEqual(
    parseMarkdown('Top jobs:\n- Allvest\n* GoComet\n2. Rengy'),
    [
      { kind: 'p', spans: [{ text: 'Top jobs:' }] },
      { kind: 'li', mark: '•', spans: [{ text: 'Allvest' }] },
      { kind: 'li', mark: '•', spans: [{ text: 'GoComet' }] },
      { kind: 'li', mark: '2.', spans: [{ text: 'Rengy' }] },
    ],
  );
});

test('lines of one paragraph stay together; unclosed ** stays literal', () => {
  assert.deepEqual(parseMarkdown('one\ntwo **x'), [{ kind: 'p', spans: [{ text: 'one\ntwo **x' }] }]);
});

test('headings are shown as bold paragraphs', () => {
  assert.deepEqual(parseMarkdown('### Why'), [{ kind: 'p', spans: [{ text: 'Why', bold: true }] }]);
});
