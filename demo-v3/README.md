# Booking Agent: animated promo demo v3

A 62-second promo animation in **one self-contained HTML file**
(`index.html`). It's built with GSAP 3.13, which is inlined in the file, so
there's no build step and the page loads **no external URLs**. Open it
offline and it plays.

This is a demo for screen recording only. It doesn't send, post or email
anything.

![preview](preview.gif)

## Storyboard

| Time | Scene | What's on screen |
|---|---|---|
| 0–3 s | Title | Booking Agent, for Perth restaurants & local businesses |
| 3–6 s | 01 · The call | The owner's phone rings (ring sound) and he answers |
| 6–19 s | 02 · Booking Agent listens | In-call screen with REC badge; transcript panel. Booking details light up amber; useless chatter ("the traffic was terrible getting here", "a friend recommended you", "we're celebrating my dad's 60th") stays grey |
| 19–22.5 s | 03 · Chatter out | Call ends; the chatter is struck out |
| 22.5–30 s | 04 · WhatsApp | WhatsApp ping, then a dedicated phone scene with the real WhatsApp mobile UI (header reads **WhatsApp**). The cleaned summary is a chat message, held ~7 s. *Special requests: Not stated* (never guessed). Side card shows what was kept, dropped and not stated |
| 30–34.5 s | 05 · Calendar | Booking drops into Saturday 21 Nov, 7:00 PM |
| 34.5–36.5 s | Not just restaurants | Bridge card |
| 36.5–46 s | Car sales | Buyer books a viewing; WhatsApp shows only visit time, car model, price range, name, phone |
| 46–56.3 s | Car service & tinting | Driver asks a price, books; WhatsApp shows only service, car, price, booked time, name, phone |
| 56.3–62 s | End card | "Never miss a booking again. From $99/month. Free two-week trial for the first restaurant." |

Restaurant booking: **Sarah Johnson, Sat 21 Nov, 7:00 PM, 2 tables, 8 adults
+ 2 children, 1 child with a peanut allergy, 0423 456 789.** All names,
numbers and businesses are made up for the demo.

## Play it

Double-click `index.html` (Chrome, Edge, Safari or Firefox). It plays
automatically and scales to fit any 16:9 window.

| Control | Key | Action |
|---|---|---|
| Play / Pause | Space | |
| Replay | R | Restart from 0 |
| Sound on/off | S | Ring and WhatsApp ping (off by default: browsers block sound until you click) |
| | ← / → | Jump back / forward 1 s |
| | H | Hide / show the control bar |

URL options: `?record` hides the controls and cursor and holds the first
frame for 1 s; `?loop` loops; `?t=22` starts at 22 s; `?paused` starts
paused. Combine them, e.g. `index.html?record&loop`.

## Record it

**Screen recorder (with sound):** open `index.html`, click **Sound: on**,
press **H** to hide the controls, go full screen (Ctrl+Cmd+F on Mac, F11 on
Windows), start your recorder (Mac: Cmd+Shift+5; Windows: Win+Alt+R or OBS),
then press **R** to replay from the start. Stop after the end card (~63 s).

**Frame-perfect MP4 (no dropped frames):** `capture.mjs` steps through the
animation in a headless browser, encodes 1920×1080 MP4 and lays the ring and
ping sounds in at the exact cue times. Needs Node 18+ and ffmpeg.

```bash
cd demo-v3
npm i playwright && npx playwright install chromium   # once
node capture.mjs            # -> out/booking-agent-demo-v3.mp4
node capture.mjs --gif      # also out/preview.gif
node capture.mjs --fps 60 --width 3840                 # 4K 60 fps
```

`out/` is git-ignored.

## Sounds

The phone ring and WhatsApp ping must be CC0 sounds from Openverse. They are
embedded in `index.html` as base64 `data:` URIs in the `SOUNDS` object, so
the page still needs no network. Credits are in `SOUNDS.md`. If `SOUNDS` is
empty, the Sound button shows "n/a" and the demo plays silently.

## Editing

All content is in `index.html`:

- **Calls and WhatsApp messages:** the `SCENES` object. In a transcript line,
  `[k:…]` marks a booking detail (highlighted) and `[x:…]` marks chatter
  (grey, struck out at hang-up). A WhatsApp row with value `null` renders as
  *Not stated*.
- **Captions:** `#cap1` … `#cap7`.
- **Timing:** the timeline section of the script (times in seconds).
