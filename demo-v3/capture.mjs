// Frame-perfect export of the promo demo to MP4 (and an optional preview GIF).
//
//   npm i -D playwright        # once, if you don't already have it
//   npx playwright install chromium
//   node demo-v3/capture.mjs                 # -> demo-v3/out/booking-agent-demo-v3.mp4
//   node demo-v3/capture.mjs --gif           # also writes a small preview GIF
//
// Needs ffmpeg on your PATH. Options: --fps 30 --width 1920 --out <dir>
import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const arg = (name, def) => {
  const i = process.argv.indexOf('--' + name);
  return i > -1 ? process.argv[i + 1] : def;
};
const FPS = Number(arg('fps', 30));
const WIDTH = Number(arg('width', 1920));
const HEIGHT = Math.round(WIDTH * 9 / 16);
const OUT = resolve(arg('out', join(here, 'out')));
const GIF = process.argv.includes('--gif');

const frames = join(OUT, 'frames');
rmSync(frames, { recursive: true, force: true });
mkdirSync(frames, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT } });
await page.goto(pathToFileURL(join(here, 'index.html')).href + '?record&paused');
await page.waitForFunction(() => window.__demo);
await page.evaluate(() => document.fonts.ready);
const duration = await page.evaluate(() => window.__demo.duration);
const total = Math.ceil(duration * FPS);

for (let i = 0; i <= total; i++) {
  await page.evaluate((s) => window.__demo.seek(s), i / FPS);
  await page.screenshot({ path: join(frames, String(i).padStart(5, '0') + '.png') });
  if (i % FPS === 0) process.stdout.write(`\r${(i / FPS).toFixed(0)}s / ${duration}s`);
}
await browser.close();
console.log('\nencoding…');

const mp4 = join(OUT, 'booking-agent-demo-v3.mp4');
execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(FPS), '-i', join(frames, '%05d.png'),
  '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-movflags', '+faststart', mp4], { stdio: 'inherit' });
console.log('wrote', mp4);

if (GIF) {
  const gif = join(OUT, 'preview.gif');
  const vf = 'fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4';
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', mp4, '-vf', vf, gif], { stdio: 'inherit' });
  console.log('wrote', gif);
}
