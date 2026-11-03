// Extract the app's module script for a syntax check, and confirm every DOM id it
// references exists in the HTML. Run: node tests/syntax.mjs
import { readFileSync, writeFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, '..', 'index.html'), 'utf8');

const m = html.match(/<script type="module">([\s\S]*?)<\/script>/);
if (!m) { console.error('FAIL: no module script found'); process.exit(1); }
writeFileSync(join(here, '_app.mjs'), m[1]);
console.log('extracted module script:', m[1].length, 'chars ->', '_app.mjs');

// every id the script touches must exist in the markup
const ids = new Set([...m[1].matchAll(/getElementById\('([^']+)'\)/g)].map(x => x[1]));
const missing = [...ids].filter(id => !new RegExp(`id="${id}"`).test(html));
console.log('ids referenced  :', [...ids].sort().join(', '));
console.log(missing.length ? 'FAIL missing ids: ' + missing.join(', ') : 'OK all referenced ids present');

// every vendor file the script needs must exist
const imports = [...m[1].matchAll(/from '\.\/([^']+)'/g)].map(x => x[1]);
for (const f of imports) {
  try { readFileSync(join(here, '..', f)); console.log('OK  vendor:', f); }
  catch { console.log('FAIL missing vendor:', f); }
}
