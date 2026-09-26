# Nyx Spectrum — shared design system

One system, three artboards, three authors. Everything below is fixed. Do not
invent alternatives to it: divergence between artboards is the one failure mode
that cannot be fixed later without redrawing everything.

---

## 0. The product

**Nyx Ichos** is a local-first AI workspace that runs on the user's own machine.
Purple/black wizard aesthetic, an owl-ish wizard mascot called Ichnos, a
"Strands" 3D memory graph, a chat, an agents roster, a model switcher.

The brief, verbatim from the owner:

> 3-d, lots of animations, hundreds of colors, transitions between pages and
> transitions between when you click the button on the site and when you get
> into the actual AI (make these change each time). I want to make the user
> experience amazing and intuitive. The site looks bland and could use an
> update. Make most parts 3d or 2d with lots of color. Think of abstract shapes.

So: **maximalist, dimensional, spectral.** Not timid. But every colour comes
out of the ramp below — "hundreds of colours" is a *system*, not confetti.

---

## 1. Ground and surfaces

The app's real tokens (from `frontend/nyx-pulse/src/theme.css`) — these are
inherited, not invented, so the redesign still reads as the same product:

```
--ink-void   #07060f   deepest ground, behind everything
--ink-base   #0d0b18   page ground
--ink-panel  #161826   panel surface   (the app's existing --color-bg)
--ink-raise  #1e2133   raised card
--ink-line   rgba(233,233,237,.10)   hairline

text primary    #f3f5fe
text secondary  #cfd3e5
text muted      #9397ab
text faint      #75798c
```

Write these as literal values inline. Do not use CSS custom properties for
them — a literal value paints while the artboard streams in.

## 2. The spectral ramp — the "hundreds of colours" engine

Every hue in the design is one function of one angle:

```
tone(h)   =  oklch(0.74 0.176 h)     the colour itself
deep(h)   =  oklch(0.50 0.150 h)     its shadow side
glow(h)   =  oklch(0.87 0.130 h)     its lit edge / text on dark
veil(h,a) =  oklch(0.74 0.176 h / a) translucent wash
```

Fixed lightness and chroma, hue is the only variable → any two colours in the
system are automatically harmonious. That is what makes a hundred colours look
composed instead of chaotic.

**Home hue is 292** — that is the app's existing accent `#9184d9` in oklch.

Named stations (use these for anything that needs identity):

| h   | name     | used for   |
|-----|----------|------------|
| 292 | Amethyst | home, primary action, Strands |
| 318 | Orchid   | Agents |
| 348 | Rose     | alerts, Power |
| 22  | Ember    | Models |
| 62  | Amber    | warnings, Skills |
| 142 | Fern     | ok states, Dashboard |
| 192 | Cyan     | Chat |
| 252 | Cobalt   | Settings |

For runs of many items, **do not pick from the table** — sweep it:
`h = 292 + index * 37` (mod 360). Thirty items give thirty distinct, related
hues. Conic and linear gradients should interpolate hue continuously
(`linear-gradient(in oklch longer hue, ...)` where it helps) so a single shape
carries dozens of colours by itself.

## 3. Type

```html
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=Sora:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
```

- Display / headings: `"Syne", "Space Grotesk", system-ui, sans-serif` — 700/800,
  `letter-spacing: -0.03em` at large sizes. Syne is wide and slightly strange;
  that is why it is here.
- Body / UI: `"Sora", system-ui, -apple-system, "Segoe UI", sans-serif` — 300/400/500.
- Mono / specs: `"JetBrains Mono", Consolas, monospace`.
- Never Inter, Roboto, Arial. Never emoji.

Scale: 76/48/30/20/15/13.5/12/10.5. Small labels are 10.5px,
`letter-spacing:.16em`, uppercase, `#75798c`.

## 4. Depth

`perspective: 1200px` on any container holding a tilted child;
`transform-style: preserve-3d` where children stack in Z.

Shadow recipe — three cues, always stacked. One drop shadow reads as a sticker;
three read as a surface under a light:

```css
box-shadow:
  inset 0 1px 0 rgba(255,255,255,.10),          /* lit top edge */
  0 1px 0 rgba(0,0,0,.55),                      /* contact      */
  0 18px 44px -22px rgba(0,0,0,.92);            /* ambient      */
```

Active / focused things add two more, in their own hue:

```css
  0 0 0 1px oklch(0.74 0.176 var(--h) / .28),   /* hue ring  */
  0 0 64px -14px oklch(0.74 0.176 var(--h) / .40); /* bloom  */
```

Radii: 8 (controls, inherited from the app) · 14 (cards) · 22 (panels) · 999 (pills).

## 5. Motion

One easing everywhere so the whole app moves like one object:

```
--ease:  cubic-bezier(.22, 1, .36, 1)
--pop:   cubic-bezier(.34, 1.56, .64, 1)   /* press / arrive only */
```

Durations: micro 180ms · state change 320ms · panel 420ms · full launch 1200ms.

Ambient loops (drifting shapes, rotating rings): 18–44s, `linear`, `infinite`,
`transform`/`opacity` only — never animate width, top, filter or box-shadow in
a loop. Stagger siblings by `animation-delay` so nothing pulses in lockstep.

Every animation must be defined in `<helmet><style>` as a `@keyframes`, and
referenced by class. Inline `animation:` on a hundred elements is unreadable.

## 6. The abstract shape library

CSS only — no images, no external assets. Use these; each artboard should carry
at least three.

**Orb** — sphere with an off-centre highlight:
```css
background: radial-gradient(circle at 32% 28%, oklch(0.90 0.13 var(--h)) 0%, oklch(0.74 0.176 var(--h)) 34%, oklch(0.38 0.13 var(--h)) 100%);
border-radius: 50%;
box-shadow: inset -8px -12px 28px rgba(0,0,0,.55), 0 0 70px -18px oklch(0.74 0.176 var(--h) / .6);
```

**Halo** — a hue wheel ring, the single best "hundreds of colours" object:
```css
background: conic-gradient(from 0deg, oklch(.74 .176 0), oklch(.74 .176 60), oklch(.74 .176 120), oklch(.74 .176 180), oklch(.74 .176 240), oklch(.74 .176 300), oklch(.74 .176 360));
border-radius: 50%;
mask: radial-gradient(circle, transparent 58%, #000 60%);
-webkit-mask: radial-gradient(circle, transparent 58%, #000 60%);
```

**Shard** — angular glass plate:
```css
clip-path: polygon(18% 0%, 100% 12%, 84% 100%, 0% 78%);
background: linear-gradient(140deg, oklch(.74 .176 var(--h) / .30), oklch(.74 .176 calc(var(--h) + 48) / .10));
box-shadow: inset 0 0 0 1px oklch(.87 .13 var(--h) / .35);
```

**Lattice** — a receding floor plane, the cheapest convincing 3D in the set:
```css
transform: perspective(700px) rotateX(66deg);
background:
  repeating-linear-gradient(90deg, oklch(.74 .176 292 / .22) 0 1px, transparent 1px 56px),
  repeating-linear-gradient(0deg,  oklch(.74 .176 292 / .16) 0 1px, transparent 1px 56px);
mask: linear-gradient(#000, transparent 72%);
-webkit-mask: linear-gradient(#000, transparent 72%);
```

**Ribbon** — long rounded bar rotated in 3D, hue sweeping along it.

**Prism stack** — 3–5 `clip-path` triangles offset by `translateZ`, each a
different station hue, rotating slowly as a group.

**Grain** — put this over any large gradient. Without it, big gradients look
like AI slop; with it they look like a printed surface:
```css
.grain::after {
  content: ""; position: absolute; inset: 0; pointer-events: none;
  opacity: .17; mix-blend-mode: overlay;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='3'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)'/%3E%3C/svg%3E");
}
```

Icons: inline `<svg>`, stroke-based, 20px grid, `stroke-width:1.5`,
`stroke="currentColor"`, `fill="none"`. Never emoji, never dingbats.

## 7. Copy

Real copy about this product, never lorem, never "Welcome to our website".
Nyx Ichos runs on the user's own machine; that is the actual selling point.
Where a hard fact is missing (a version, a count, a date) write it bracketed
like `[BUILD]` rather than inventing one. Sample values inside a working
control (a token count ticking up) are fine.

---

## 8. The `.dc.html` format — read this carefully, the failures are silent

Each artboard is ONE self-contained file. Skeleton, exactly:

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Syne...">
  <style>
    body { margin: 0; font-family: "Sora", system-ui, sans-serif; }
    a { color: #b5abfc; text-decoration: none; }
    a:hover { color: #d2cefd; }
    /* all @keyframes and classes here */
  </style>
</helmet>

<div style="width: 1440px; height: 900px; ...">
  ... the design ...
</div>
</x-dc>

<script data-dc-script data-props='{"$preview": {"width": 1440, "height": 900}}'>
class Component extends DCLogic {
  renderVals() {
    return { /* values, arrays and handler functions the template binds */ };
  }
}
</script>
</body>
</html>
```

Rules that bite:

- **Keep the `<script src="./support.js"></script>` line exactly.** It is
  replaced with the real runtime at render time. Do not remove or inline it.
- **The root element must be exactly `width: 1440px; height: 900px`** with
  `overflow: hidden` and an explicit background. The frame does not scale.
- `{{ handlebars }}` are a **dotted lookup only** — `{{ user.name }}`,
  `{{ item.hue }}`, `{{ $index }}`. **Never an expression.** `{{ a + b }}`,
  `{{ !x }}`, `{{ f() }}` all fail silently. Operators outside the braces are
  literal text: `style="color: {{x}} ? 'a' : 'b'"` renders as invalid CSS and
  is dropped. Compute the finished value in `renderVals()` and bind it whole.
- Loops: `<sc-for list="{{items}}" as="item" hint-placeholder-count="6">` with
  `{{item.x}}` and `{{$index}}` in scope. Branches:
  `<sc-if value="{{flag}}" hint-placeholder-val="{{true}}">`. **Always set the
  `hint-*` attribute** — it is what renders while values stream in.
- Events work, JSX camelCase, whole-value only: `onClick="{{ item.pick }}"`
  where `pick` is a function returned from `renderVals()`. For per-item
  handlers, attach one to each item when you build the array:
  `items: xs.map((x, i) => ({ ...x, pick: () => this.setState({ sel: i }) }))`.
- Logic class: plain classic JS. No TypeScript, no import/export, no `render()`.
  `class Component extends DCLogic` with `this.props`, `this.state`,
  `this.setState`, and React class lifecycle (`componentDidMount`).
- `data-props` is a normal HTML attribute, **single-quoted**. Inside it write
  `&amp;` for `&` and `&#39;` for an apostrophe. Raw UTF-8 (é, —, ·) is fine.
- **Static copy stays literal text in the markup.** Do not turn labels into
  props or bindings — a viewer retypes literal text in place. Bind only real
  data and live state.
- Close every non-void element; quote every attribute. Prefer inline `style=""`
  for anything a viewer might want to restyle; put keyframes, pseudo-elements
  and hover rules in `<helmet><style>`.
- Lay sibling groups out with `display:flex`/`grid` + `gap`. Never space
  siblings with source whitespace or per-element margins.
- No network beyond Google Fonts. No `fetch`, no CDN scripts, no external images.
- Do not attach global `keydown` handlers — they would swallow the editor's undo.

## 9. What you deliver

Exactly one file, at the path named in your task. Nothing else — do not create
extra files, do not run any build or seeding command, do not touch the other
artboards, do not commit anything. When you are done, reply with a short note
saying what you built, which shapes and hues you used, and anything you left
as a placeholder.
