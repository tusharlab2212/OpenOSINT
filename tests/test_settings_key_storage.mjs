/**
 * Web UI settings — Batch 2 F10: the OpenAI-compatible API key never lives in
 * localStorage. The real loadSettings / saveLocalSettings / clearAllKeys methods are
 * extracted from openosint/web/index.html and run against fake storages.
 *
 * Run: node tests/test_settings_key_storage.mjs
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';

const html = readFileSync(path.resolve(import.meta.dirname, '..', 'openosint', 'web', 'index.html'), 'utf8');
function method(name) {
  const m = html.match(new RegExp(`\\n    ${name}\\(\\) \\{\\n[\\s\\S]*?\\n    \\},\\n`));
  if (!m) throw new Error(`${name} not found in index.html`);
  return m[0].trim().replace(/,$/, '');
}
const SRC = ['loadSettings', 'saveLocalSettings', 'clearAllKeys'].map(method).join(',\n');

class FakeStorage {
  constructor(init = {}) { this.data = { ...init }; }
  getItem(k) { return k in this.data ? this.data[k] : null; }
  setItem(k, v) { this.data[k] = String(v); }
  removeItem(k) { delete this.data[k]; }
}

function app(local = {}, session = {}) {
  globalThis.localStorage = new FakeStorage(local);
  globalThis.sessionStorage = new FakeStorage(session);
  const obj = eval(`({${SRC}})`);
  obj.settings = { chatModel: 'claude', ollamaModel: 'llama3.2', ollamaHost: 'http://localhost:11434',
                   openaiBaseUrl: '', openaiModel: '', openaiApiKey: '' };
  obj.byok = { provider: 'anthropic', apiKey: '', baseUrl: '', model: '' };
  obj.byokToolKeys = {};
  return obj;
}
const localSettings = () => JSON.parse(localStorage.getItem('openosint_settings') || '{}');

let passed = 0, failed = 0;
function assert(cond, label) {
  if (cond) { console.log(`  ✓ ${label}`); passed++; }
  else { console.error(`  ✗ ${label}`); failed++; }
}

console.log('\nOpenAI-compatible key storage');

// A key saved in localStorage by an older version is moved to sessionStorage, once.
let a = app({ openosint_settings: JSON.stringify({ openaiBaseUrl: 'http://gw.invalid/v1', openaiApiKey: 'sk-legacy' }) });
a.loadSettings();
assert(a.settings.openaiApiKey === 'sk-legacy', 'legacy key still usable this session');
assert(sessionStorage.getItem('openosint_openai_key') === 'sk-legacy', 'legacy key moved to sessionStorage');
assert(!('openaiApiKey' in localSettings()), 'legacy key removed from localStorage (not kept in both)');
assert(localSettings().openaiBaseUrl === 'http://gw.invalid/v1', 'other settings stay in localStorage');

// A key already in this session wins over a stale legacy copy, which is still removed.
a = app({ openosint_settings: JSON.stringify({ openaiApiKey: 'sk-stale' }) }, { openosint_openai_key: 'sk-session' });
a.loadSettings();
assert(a.settings.openaiApiKey === 'sk-session', 'session key wins over a stale legacy key');
assert(!('openaiApiKey' in localSettings()), 'stale legacy key removed from localStorage');

// Saving never writes the key to localStorage.
a = app();
a.loadSettings();
a.settings.openaiApiKey = 'sk-new';
a.settings.openaiModel = 'm';
a.saveLocalSettings();
assert(!localStorage.getItem('openosint_settings').includes('sk-new'), 'save: key never written to localStorage');
assert(localSettings().openaiModel === 'm', 'save: other settings persisted');
assert(sessionStorage.getItem('openosint_openai_key') === 'sk-new', 'save: key kept in sessionStorage');
a.settings.openaiApiKey = '';
a.saveLocalSettings();
assert(sessionStorage.getItem('openosint_openai_key') === null, 'save with empty key removes it');

// A new tab (empty sessionStorage) starts without the key.
a = app({ openosint_settings: JSON.stringify({ openaiModel: 'm' }) });
a.loadSettings();
assert(a.settings.openaiApiKey === '' && a.settings.openaiModel === 'm', 'new session: no key, settings restored');

// Clear all keys also clears this one.
a = app({}, { openosint_openai_key: 'sk-x', openosint_byok: '{}', openosint_tool_keys: '{}' });
a.loadSettings();
a.clearAllKeys();
assert(a.settings.openaiApiKey === '' && sessionStorage.getItem('openosint_openai_key') === null, 'clearAllKeys clears the OpenAI-compatible key');

// Corrupt storage does not break loading.
a = app({ openosint_settings: '{not json' });
let threw = false;
try { a.loadSettings(); } catch { threw = true; }
assert(!threw && a.settings.openaiApiKey === '', 'corrupt localStorage is ignored safely');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
