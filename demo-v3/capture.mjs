// Frame-perfect export of the promo demo to MP4 (with its sound effects) and an optional preview GIF.
//
//   npm i playwright && npx playwright install chromium   # once
//   node demo-v3/capture.mjs              # -> demo-v3/out/booking-agent-demo-v3.mp4
//   node demo-v3/capture.mjs --gif        # also writes demo-v3/out/preview.gif
//
// Needs ffmpeg on your PATH. Options: --fps 30 --width 1920 --out <dir>
import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const arg = (name, def) => { const i = process.argv.indexOf('--' + name); return i > -1 ? process.argv[i + 1] : def; };
const FPS = Number(arg('fps', 30));
const WIDTH = Number(arg('width', 1920));
const HEIGHT = Math.round(WIDTH * 9 / 16);
const OUT = resolve(arg('out', join(here, 'out')));
const GIF = process.argv.includes('--gif');
const ff = (args) => execFileSync('ffmpeg', ['-y', '-loglevel', 'error', ...args], { stdio: 'inherit' });

const frames = join(OUT, 'frames');
rmSync(frames, { recursive: true, force: true });
mkdirSync(frames, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT } });
await page.goto(pathToFileURL(join(here, 'index.html')).href + '?record&paused');
await page.waitForFunction(() => window.__demo);
await page.evaluate(() => document.fonts.ready);
const { duration, cues, sounds } = await page.evaluate(() => ({ duration: window.__demo.duration, cues: window.__demo.cues, sounds: window.__demo.sounds }));
const total = Math.ceil(duration * FPS);
for (let i = 0; i <= total; i++) {
  await page.evaluate((s) => window.__demo.seek(s), i / FPS);
  await page.screenshot({ path: join(frames, String(i).padStart(5, '0') + '.png') });
  if (i % FPS === 0) process.stdout.write(`\r${(i / FPS).toFixed(0)}s / ${duration}s`);
}
await browser.close();
console.log('\nencoding…');

// Sound track: place each cue (ring / ping) at its time on the timeline.
const files = {};
for (const [name, uri] of Object.entries(sounds || {})) {
  if (!uri) continue;
  const f = join(OUT, name + '.mp3');
  writeFileSync(f, Buffer.from(uri.split(',')[1], 'base64'));
  files[name] = f;
}
const used = (cues || []).filter((c) => files[c.name]);
const silent = join(OUT, 'video.mp4');
ff(['-framerate', String(FPS), '-i', join(frames, '%05d.png'), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', silent]);
const mp4 = join(OUT, 'booking-agent-demo-v3.mp4');
if (used.length) {
  const inputs = used.flatMap((c) => (c.name === 'ring' ? ['-stream_loop', '-1'] : []).concat(['-i', files[c.name]]));
  const chains = used.map((c, i) => `[${i + 1}:a]atrim=0:${c.len.toFixed(2)},afade=t=out:st=${Math.max(0, c.len - 0.15).toFixed(2)}:d=0.15,adelay=${Math.round(c.t * 1000)}:all=1[a${i}]`);
  const mix = `${used.map((_, i) => `[a${i}]`).join('')}amix=inputs=${used.length}:normalize=0,apad[aout]`;
  ff(['-i', silent, ...inputs, '-filter_complex', [...chains, mix].join(';'), '-map', '0:v', '-map', '[aout]',
    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', mp4]);
} else {
  ff(['-i', silent, '-c', 'copy', '-movflags', '+faststart', mp4]);
  console.log('(no sound files embedded in index.html yet, so the MP4 is silent)');
}
console.log('wrote', mp4);

if (GIF) {
  const gif = join(OUT, 'preview.gif');
  ff(['-i', mp4, '-vf', 'fps=10,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer:bayer_scale=4', gif]);
  console.log('wrote', gif);
}
