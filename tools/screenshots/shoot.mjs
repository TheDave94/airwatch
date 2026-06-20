// AirWatch card screenshot harness.
//
// Self-contained: starts a tiny static server that serves harness.html and maps
// /airwatch_card_static/* to the shipped card bundle + icons, then renders the
// card (faithful fixture from gen.py) across collapsed/expanded x light/dark/custom
// themes and writes PNGs to docs/images/.
//
// Run:  python3 gen.py && node shoot.mjs        (or: npm run screenshots)
// Re-run after any change to airwatch-card.js or the band/consensus logic.

import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve, extname } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..');
const FRONTEND = join(REPO_ROOT, 'custom_components', 'airwatch', 'frontend');
const OUT = join(REPO_ROOT, 'docs', 'images');
const STATIC_BASE = '/airwatch_card_static/';

const MIME = { '.js': 'text/javascript', '.svg': 'image/svg+xml', '.html': 'text/html', '.css': 'text/css', '.json': 'application/json' };

// ---- theme custom-property maps (light / dark / a non-default "custom" theme) ----
const LIGHT  = { '--app-bg':'#eef0f2','--card-background-color':'#ffffff','--ha-card-background':'#ffffff','--primary-text-color':'#1c1c1c','--secondary-text-color':'#6f7780','--divider-color':'rgba(0,0,0,.12)','--primary-color':'#2E7DD1','--ha-card-border-radius':'12px' };
const DARK   = { '--app-bg':'#121417','--card-background-color':'#1c2025','--ha-card-background':'#1c2025','--primary-text-color':'#e6e8eb','--secondary-text-color':'#9aa3ad','--divider-color':'rgba(255,255,255,.12)','--primary-color':'#2E7DD1','--ha-card-border-radius':'12px' };
const CUSTOM = { '--app-bg':'#2a2140','--card-background-color':'#3a2f57','--ha-card-background':'#3a2f57','--primary-text-color':'#f3eefb','--secondary-text-color':'#c4b6e0','--divider-color':'rgba(255,255,255,.16)','--primary-color':'#c9a4ff','--ha-card-border-radius':'24px','--ha-card-box-shadow':'0 8px 24px rgba(120,70,200,.4)','--ha-card-border-color':'rgba(201,164,255,.3)' };

const SHOTS = [
  { name: 'collapsed-light',  theme: LIGHT,  expanded: false },
  { name: 'collapsed-dark',   theme: DARK,   expanded: false },
  { name: 'collapsed-custom', theme: CUSTOM, expanded: false },
  { name: 'expanded-light',   theme: LIGHT,  expanded: true },
  { name: 'expanded-dark',    theme: DARK,   expanded: true },
  { name: 'expanded-custom',  theme: CUSTOM, expanded: true },
];
const only = process.argv[2]; // optional: render a single shot by name

async function main() {
  const statesPath = join(HERE, 'states.json');
  if (!existsSync(statesPath)) {
    console.error('states.json missing — run `python3 gen.py` first.');
    process.exit(1);
  }
  const states = JSON.parse(await readFile(statesPath, 'utf8'));
  await mkdir(OUT, { recursive: true });

  // tiny static server: harness.html + the integration's frontend dir under STATIC_BASE
  const server = createServer(async (req, res) => {
    try {
      let url = decodeURIComponent(req.url.split('?')[0]);
      let file;
      if (url === '/' || url === '/harness.html') file = join(HERE, 'harness.html');
      else if (url.startsWith(STATIC_BASE)) file = join(FRONTEND, url.slice(STATIC_BASE.length));
      else { res.writeHead(404); return res.end('not found'); }
      const body = await readFile(file);
      res.writeHead(200, { 'content-type': MIME[extname(file)] || 'application/octet-stream' });
      res.end(body);
    } catch {
      res.writeHead(404); res.end('not found');
    }
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ deviceScaleFactor: 2, viewport: { width: 560, height: 1200 } });
  const page = await ctx.newPage();
  const errs = [];
  page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', (e) => errs.push(String(e.message)));

  await page.goto(`http://127.0.0.1:${port}/harness.html`, { waitUntil: 'load' });
  await page.waitForFunction(() => !!customElements.get('airwatch-card'));

  for (const shot of SHOTS) {
    if (only && shot.name !== only) continue;
    await page.evaluate(async ({ shot, states }) => {
      const stage = document.getElementById('stage');
      document.documentElement.removeAttribute('style');
      for (const [k, v] of Object.entries(shot.theme)) document.documentElement.style.setProperty(k, v);
      document.body.style.background = shot.theme['--app-bg'];
      stage.innerHTML = '';
      const card = document.createElement('airwatch-card');
      card.setConfig({ type: 'custom:airwatch-card', title: 'Air quality', expanded_default: shot.expanded });
      card.hass = { states, locale: { language: 'en' }, themes: { darkMode: false }, callWS: async () => [], connection: { subscribeMessage: async () => (() => {}) } };
      stage.appendChild(card);
      if (card.updateComplete) await card.updateComplete;
    }, { shot, states });
    await page.waitForTimeout(800);
    const el = await page.$('#stage');
    await el.screenshot({ path: join(OUT, `${shot.name}.png`) });
    console.log('shot:', shot.name);
  }

  if (errs.length) console.log('card console/page errors:', JSON.stringify(errs.slice(0, 8)));
  await browser.close();
  server.close();
}

main();
