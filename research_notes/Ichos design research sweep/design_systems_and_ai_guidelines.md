# Design systems and AI-UX guidelines: exact tokens for Ichos (October 2026)

Scope: Fluent 2 (web and Windows 11/WinUI), Material 3 (and M3 Expressive motion), IBM Carbon (and Carbon for AI), GitHub Primer, Vercel Geist, Radix Colors, shadcn/ui, Atlassian (and Rovo), Salesforce SLDS 2/Agentforce, Shopify Polaris. AI-UX sets: Microsoft HAX, Google PAIR, Carbon for AI, shapeof.ai, NN/g, Microsoft Copilot examples.
Already covered elsewhere (not repeated): Apple HIG, LobeHub DESIGN.md, Linear/Stripe colours, Vercel AI Elements, Cloudscape artifact rule.
Method: values were pulled where possible from the systems' **token source files** (GitHub raw / npm CDN) rather than rendered doc sites, since most doc sites (m3.material.io, fluent2.microsoft.design, lightningdesignsystem.com, pair.withgoogle.com/guidebook) render through JavaScript and returned empty pages to the fetcher. Hex values written as `#AARRGGBB` are WinUI/XAML notation (alpha first); in CSS they become `rgba()`. Opacity percentages next to them are my conversion (alpha byte / 255).

---

## 1. Dark-theme surface ladders, text/secondary/disabled, borders, accent rules

### Takeaway
Two Microsoft dark ladders exist and they differ: **Windows 11 / WinUI** uses a #202020 base with *translucent white* fills for controls, cards and text (designed to sit on Mica), while **Fluent 2 web** uses an *opaque grey ladder* (#292929 default surface, down to #000) with opaque text greys. Every other system converges on the same shape: a near-black base around L* 6–10, 3–4 raised steps of roughly +4–8 lightness each, text at ~95% / ~70% / ~55% / ~35–40% white, and borders as low-alpha white.

### Cited Findings

**Fluent 2 web — dark alias tokens (webDarkTheme)** — alias mapping from [fluentui darkColor.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/alias/darkColor.ts); hex resolved from the grey palette in [fluentui global/colors.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/colors.ts) and brand ramp in [brandColors.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/brandColors.ts):

| Token | Palette ref | Hex |
|---|---|---|
| colorNeutralBackground1 (default surface) | grey[16] | #292929 |
| colorNeutralBackground1Hover / Pressed | grey[24] / grey[12] | #3d3d3d / #1f1f1f |
| colorNeutralBackground2 | grey[12] | #1f1f1f |
| colorNeutralBackground3 | grey[8] | #141414 |
| colorNeutralBackground4 | grey[4] | #0a0a0a |
| colorNeutralBackground5 | black | #000000 |
| colorNeutralBackground6 | grey[20] | #333333 |
| colorNeutralCardBackground | grey[20] | #333333 |
| colorSubtleBackgroundHover | grey[22] | #383838 |
| colorNeutralForeground1 | white | #ffffff |
| colorNeutralForeground2 | grey[84] | #d6d6d6 |
| colorNeutralForeground3 | grey[68] | #adadad |
| colorNeutralForeground4 | grey[60] | #999999 |
| colorNeutralForegroundDisabled | grey[36] | #5c5c5c |
| colorNeutralStroke1 | grey[40] | #666666 |
| colorNeutralStroke2 | grey[32] | #525252 |
| colorNeutralStroke3 | grey[24] | #3d3d3d |
| colorNeutralStrokeAccessible | grey[68] | #adadad |
| colorNeutralStrokeDisabled | grey[26] | #424242 |
| colorNeutralStrokeSubtle | grey[4] | #0a0a0a |
| colorBrandBackground | brand[70] | #115ea3 |
| colorBrandBackgroundHover | brand[80] | #0f6cbd |
| colorBrandBackgroundPressed | brand[40] | #0c3b5e |
| colorBrandForeground1 / colorCompoundBrandStroke | brand[100] | #479ef5 |
| colorNeutralForegroundOnBrand | white | #ffffff |
| colorStrokeFocus1 / colorStrokeFocus2 | black / white | #000000 / #ffffff |
| colorNeutralShadowAmbient / Key | — | rgba(0,0,0,0.24) / rgba(0,0,0,0.28) |

- Fluent web brand ramp (brandWeb 10→160): #061724, #082338, #0a2e4a, #0c3b5e, #0e4775, #0f548c, #115ea3, #0f6cbd, #2886de, #479ef5, #62abf5, #77b7f7, #96c6fa, #b4d6fa, #cfe4fa, #ebf3fc — [brandColors.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/brandColors.ts)
- Fluent grey palette is a 2-step neutral ramp (grey[2] #050505 … grey[98] #fafafa) plus whiteAlpha 5–90 (rgba(255,255,255,0.05)…0.9) — [colors.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/colors.ts)

**Windows 11 / WinUI dark theme resources** — values from WPF UI's port of the WinUI theme dictionary, [lepoco/wpfui Dark.xaml](https://github.com/lepoco/wpfui/blob/main/src/Wpf.Ui/Resources/Theme/Dark.xaml) (the original `Common_themeresources_any.xaml` in microsoft-ui-xaml could not be fetched at its old path; secondary source, but values match WinUI naming 1:1). `TextFillColorPrimary` dark = #FFFFFFFF is independently confirmed by [Microsoft's XAML theme resources page](https://learn.microsoft.com/windows/apps/design/style/xaml-theme-resources).

| Resource | Value | ≈ |
|---|---|---|
| SolidBackgroundFillColorBase (Mica fallback, app bg) | #202020 | |
| SolidBackgroundFillColorSecondary | #1C1C1C | |
| SolidBackgroundFillColorTertiary | #282828 | |
| SolidBackgroundFillColorQuaternary | #2C2C2C | |
| LayerFillColorDefault (content layer on Mica) | #4C3A3A3A | #3a3a3a @ 30% |
| CardBackgroundFillColorDefault | #0DFFFFFF | white @ 5.1% |
| CardStrokeColorDefault | #19000000 | black @ 9.8% |
| TextFillColorPrimary | #FFFFFF | 100% |
| TextFillColorSecondary | #C5FFFFFF | white @ 77% |
| TextFillColorTertiary | #87FFFFFF | white @ 53% |
| TextFillColorDisabled | #5DFFFFFF | white @ 36.5% |
| ControlFillColorDefault (rest) | #0FFFFFFF | white @ 5.9% |
| ControlFillColorSecondary (hover) | #15FFFFFF | white @ 8.2% |
| ControlFillColorTertiary (pressed) | #08FFFFFF | white @ 3.1% |
| ControlFillColorDisabled | #0BFFFFFF | white @ 4.3% |
| SubtleFillColorSecondary / Tertiary | #0FFFFFFF / #0AFFFFFF | 5.9% / 3.9% |
| ControlStrokeColorDefault | #12FFFFFF | white @ 7% |
| ControlStrokeColorSecondary | #18FFFFFF | white @ 9.4% |
| ControlStrongStrokeColorDefault | #8BFFFFFF | white @ 54.5% |
| DividerStrokeColorDefault | #15FFFFFF | white @ 8.2% |
| SurfaceStrokeColorDefault | #66757575 | #757575 @ 40% |
| SurfaceStrokeColorFlyout | #33000000 | black @ 20% |
| FocusStrokeColorOuter / Inner | #FFFFFF / #B3000000 | white / black @ 70% |
| SystemFillColorCritical / Success / Caution | #FF99A4 / #6CCB5F / #FCE100 | |
| SmokeFillColorDefault (modal scrim) | #4D000000 | black @ 30% |
| ApplicationBackgroundColor | #FF202020 | |

**Mica / Acrylic rules (Windows 11)** — [Mica material](https://learn.microsoft.com/en-us/windows/apps/design/style/mica):
- Mica is an opaque, dynamic material for the *backdrop of long-lived windows*; it samples the wallpaper only once (performance). Mica Alt has stronger tinting and is recommended for tabbed title bars.
- Apply Mica as the base layer; a content layer above it uses `LayerFillColorDefaultBrush` ("a low-opacity solid color"). With Mica Alt: base → commanding layer (`LayerOnMicaBaseAltFillColorDefaultBrush`) → content layer (`LayerFillColorDefaultBrush`).
- Mica falls back to solid `SolidBackgroundFillColorBase` (Mica Alt → `SolidBackgroundFillColorBaseAlt`) when transparency is off, Battery Saver is on, on low-end hardware, when the window is **inactive**, or below build 22000.
- Do set backgrounds transparent wherever Mica should show; don't apply backdrop material more than once per app; don't apply it to a UI element.
- Mica should be visible in the title bar (extend into non-client area with a transparent custom title bar).
- Windows uses a **two-layer** system: base layer (menus, commands, navigation) and content layer (contiguous or cards) — [Layering and elevation](https://learn.microsoft.com/en-us/windows/apps/design/signature-experiences/layering).

**Material 3 dark tone mapping** (baseline 2021 spec; tones of the HCT neutral/primary palettes) — [material-color-utilities color_spec_2021.ts](https://github.com/material-foundation/material-color-utilities/blob/main/typescript/dynamiccolor/color_spec_2021.ts):
- background / surface / surfaceDim = tone 6; surfaceBright = 24; surfaceContainerLowest = 4; Low = 10; Container = 12; High = 17; Highest = 22 (standard contrast; higher-contrast curves raise these, e.g. Highest 26/30).
- onSurface = 90; onSurfaceVariant = 80; outline = 60; outlineVariant = 30; inverseSurface = 90.
- primary = 80; onPrimary = 20; primaryContainer = 30; onPrimaryContainer = 90; error = 80; onError = 20.
- Note: the current `material_dynamic_colors.ts` now delegates to a **`ColorSpecDelegateImpl2026`** (color_spec_2026), i.e. Google shipped a 2026 colour spec; its dark tones were not retrieved — [material_dynamic_colors.ts](https://github.com/material-foundation/material-color-utilities/blob/main/typescript/dynamiccolor/material_dynamic_colors.ts).

**IBM Carbon — Gray 100 (dark) theme** — token→palette mapping from [@carbon/themes g100.js](https://cdn.jsdelivr.net/npm/@carbon/themes/src/g100.js); hex from [@carbon/colors](https://cdn.jsdelivr.net/npm/@carbon/colors/es/index.js):
- background gray100 #161616; layer-01 gray90 #262626; layer-02 gray80 #393939; layer-03 gray70 #525252; field-01 gray90 #262626.
- border-subtle-00 gray80 #393939; border-subtle-01 gray70 #525252; border-strong-01 gray60 #6f6f6f.
- text-primary gray10 #f4f4f4; text-secondary gray30 #c6c6c6; text-helper gray40 #a8a8a8; text-placeholder = text-primary @ 0.4; text-disabled = text-primary @ 0.25.
- link-primary blue40 #78a9ff; interactive blue50 #4589ff; focus white #ffffff; focus-inset gray100 #161616.

**GitHub Primer — dark** — functional mappings from [primer bgColor.json5](https://github.com/primer/primitives/blob/main/src/tokens/functional/color/bgColor.json5) and [fgColor.json5](https://github.com/primer/primitives/blob/main/src/tokens/functional/color/fgColor.json5); hex from [base dark.json5](https://github.com/primer/primitives/blob/main/src/tokens/base/color/dark/dark.json5):
- bgColor.inset neutral.0 #010409; bgColor.default neutral.1 #0D1117; bgColor.muted neutral.2 #151B23; bgColor.disabled neutral.3 #212830; bgColor.emphasis neutral.7 #3D444D; bgColor.neutral.muted = neutral.8 (#656C76) @ 0.2.
- fgColor.default neutral.12 #F0F6FC; fgColor.muted neutral.9 #9198A1; fgColor.disabled neutral.8 #656C76; fgColor.onEmphasis #ffffff; fgColor.accent / link #4493F8.
- bgColor.accent.emphasis blue.5 #1f6feb; bgColor.accent.muted = blue.4 (#388bfd) @ 0.1. Primer also ships "dimmed" and several high-contrast/colour-blind dark variants (e.g. dimmed default = neutral.3).

**Atlassian (ADS) — dark** — [@atlaskit/tokens atlassian-dark](https://unpkg.com/@atlaskit/tokens/dist/esm/artifacts/themes/atlassian-dark.js):
- elevation.surface.sunken #18191A; surface #1F1F21; surface.raised #242528; surface.overlay #2B2C2F.
- text #CECFD2; text.subtle #A9ABAF; text.subtlest #96999E; text.disabled #E5E9F640 (≈25%).
- border #E3E4F21F (≈12%); border.focused #8FB8F6; background.brand.bold / link #669DF1; background.discovery.bold #C97CF4.
- shadow.raised `0 0 0 1px #00000000, 0 1px 1px #01040480, 0 0 1px #01040480`; shadow.overlay `0 0 0 1px #BDBDBD1F, 0 8px 12px #0104045C, 0 0 1px 1px #01040480` (dark overlays get a 1px light ring).

**Radix Colors — dark scales** — [radix-ui/colors dark.ts](https://github.com/radix-ui/colors/blob/main/src/dark.ts):
- grayDark 1–12: #111111, #191919, #222222, #2a2a2a, #313131, #3a3a3a, #484848, #606060, #6e6e6e, #7b7b7b, #b4b4b4, #eeeeee.
- slateDark 1–12: #111113, #18191b, #212225, #272a2d, #2e3135, #363a3f, #43484e, #5a6169, #696e77, #777b84, #b0b4ba, #edeef0.
- grayDarkA 1–12: transparent, #ffffff09, #ffffff12, #ffffff1b, #ffffff22, #ffffff2c, #ffffff3b, #ffffff55, #ffffff64, #ffffff72, #ffffffaf, #ffffffed.
- blueDark 9/10/11/12: #0090ff / #3b9eff / #70b8ff / #c2e6ff; irisDark 9/11: #5b5bd6 / #b1a9ff; violetDark 9/11: #6e56cf / #baa7ff.

**shadcn/ui — `.dark` (neutral base)** — [shadcn theming](https://ui.shadcn.com/docs/theming):
- --background oklch(0.145 0 0); --foreground oklch(0.985 0 0); --card / --popover oklch(0.205 0 0); --secondary / --muted / --accent oklch(0.269 0 0); --muted-foreground oklch(0.708 0 0).
- --primary oklch(0.922 0 0) with --primary-foreground oklch(0.205 0 0) (inverted primary in dark); --destructive oklch(0.704 0.191 22.216).
- --border oklch(1 0 0 / 10%); --input oklch(1 0 0 / 15%); --ring oklch(0.556 0 0); --radius 0.625rem (10px).

**Vercel Geist** — [Geist colors](https://vercel.com/geist/colors): 10 scales (backgrounds, gray, gray-alpha, blue, red, amber, green, teal, purple, pink); each 100–1000 with fixed roles: 100–300 backgrounds (default/hover/active), 400–600 borders (default/hover/active), 700–800 high-contrast backgrounds, 900 secondary text/icons, 1000 primary text/icons. Background-100 is the default; background-200 for subtle differentiation, used sparingly. Use gray by default; gray-alpha only when the background must show through.

**Accent usage rules**
- Carbon: "Do not use Carbon for AI styling as decoration"; AI styling only identifies AI — [Carbon for AI](https://carbondesignsystem.com/guidelines/carbon-for-ai/).
- Atlassian Rovo: "Rovo color is applied to specific signifiers, not whole surfaces"; "Restraint and intent make those moments land" — [About Rovo UI](https://atlassian.design/rovo-ui/about-rovo-ui).
- Fluent dark uses a *lighter* brand step for text/strokes (brand[100] #479ef5) than for filled backgrounds (brand[70] #115ea3), and a *darker* step on pressed (brand[40]) — [darkColor.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/alias/darkColor.ts). M3 does the same (primary tone 80 on dark vs container 30) — [color_spec_2021.ts](https://github.com/material-foundation/material-color-utilities/blob/main/typescript/dynamiccolor/color_spec_2021.ts).

### Inferences
- Base lightness converges: Primer #0D1117, Radix #111111, Carbon #161616, Atlassian #1F1F21, WinUI #202020, Fluent web #292929 (Fluent web is the lightest default surface; WinUI's #202020 is what Windows 11 itself paints).
- Secondary text sits at 70–80% luminance across systems (WinUI 77% white, Fluent #d6d6d6, Carbon #c6c6c6, Radix gray11 #b4b4b4); disabled at ~25–37% (WinUI 36.5%, Carbon 25%, Atlassian ~25%, Fluent #5c5c5c).
- Translucent-white fills (WinUI, Radix A-scale, shadcn border 10%/input 15%) are what make a single token set survive both Mica and solid backgrounds — the right choice for a Windows-native-looking Electron/Tauri app.
- Accent text on dark must use a light step (≈ tone 70–80); filled accent buttons use a mid step with white text.

### Gaps
- WinUI values come from a faithful third-party port, not the microsoft-ui-xaml file itself (old path 404'd). `SolidBackgroundFillColorBaseAlt` and `LayerOnMicaBaseAltFillColorDefault` dark values were not retrieved. Acrylic tint/luminosity opacities were not retrieved.
- Geist dark hex values: not retrievable (doc site renders client-side; vercel.com/design.dark.md exposes only token names).
- M3 2026 colour spec tones: not retrieved.
- Shopify Polaris dark tokens: not researched (no time budget left; Polaris is light-first and lowest priority for a Windows desktop app).

---

## 2. Type ramps

### Takeaway
For a Windows-first app, use the **Windows 11 Segoe UI Variable ramp** verbatim (Caption 12/16, Body 14/20, Body Large 18/24, Subtitle 20/28, Title 28/36, Title Large 40/52, Display 68/92) with only Regular (400) and Semibold (600); no Bold, no Italic. Fluent 2 web tokens provide the matching CSS ladder.

### Cited Findings
- Windows 11 type ramp (effective pixels, size/line-height) — [Typography in Windows](https://learn.microsoft.com/en-us/windows/apps/design/signature-experiences/typography):

| Style | Variant / weight | Size / LH |
|---|---|---|
| Caption | Small, Regular | 12/16 |
| Body | Text, Regular | 14/20 |
| Body Strong | Text, Semibold | 14/20 |
| Body Large | Text, Regular | 18/24 |
| Body Large Strong | Text, Semibold | 18/24 |
| Subtitle | Display, Semibold | 20/28 |
| Title | Display, Semibold | 28/36 |
| Title Large | Display, Semibold | 40/52 |
| Display | Display, Semibold | 68/92 |

- Segoe UI Variable axes: `wght` 100–700 and `opsz` (automatic, optical scaling 8pt–36pt). Named weights: Light 300, Semilight 350, Regular 400, Semibold 600, Bold 700. In HTML optical scaling is automatic but you must specify "Segoe UI Variable" in CSS — [same](https://learn.microsoft.com/en-us/windows/apps/design/signature-experiences/typography).
- Rules: Regular for most text, Semibold for titles; **minimums 14px Semibold / 12px Regular**; sentence case for all UI text including titles; left-align by default; ellipses for truncation in most cases; "Bold and Italic styles are not part of the Windows type ramp. Use Semibold instead of Bold"; italic excluded for dyslexia legibility; 50–60 characters per line — [same](https://learn.microsoft.com/en-us/windows/apps/design/signature-experiences/typography).
- Usage: Title/Subtitle/Body with 12epx spacing; Body Strong as title in confined spaces; Caption for very confined spaces; multi-line lists use Body + Caption with 32epx icons; Body Strong for section headers — [Content layout and spacing](https://learn.microsoft.com/en-us/windows/apps/design/basics/content-basics).
- Fluent 2 web font tokens — [fluentui fonts.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/fonts.ts): fontSizeBase100 10/14, Base200 12/16, Base300 14/20, Base400 16/22, Base500 20/28, Base600 24/32, Hero700 28/36, Hero800 32/40, Hero900 40/52, Hero1000 68/92. Weights Regular 400, Medium 500, Semibold 600, Bold 700. fontFamilyBase `'Segoe UI', 'Segoe UI Web (West European)', -apple-system, BlinkMacSystemFont, Roboto, 'Helvetica Neue', sans-serif`; fontFamilyMonospace `Consolas, 'Courier New', Courier, monospace`; fontFamilyNumeric starts with `Bahnschrift`.
- Material 3 type scale (size; baseline weight → emphasized weight) — [MDC-Android Typography.md](https://github.com/material-components/material-components-android/blob/master/docs/theming/Typography.md): Display L/M/S 57/45/36 Regular→Medium; Headline L/M/S 32/28/24; Title L 22 Regular→Medium; Title M/S 16/14 Medium→Bold; Body L/M/S 16/14/12 Regular→Medium; Label L/M/S 14/12/11 Medium→Bold. (Line heights/tracking not in that file.)

### Inferences
- Fluent web's 16/22 Base400 step has no Windows-ramp equivalent; Windows jumps 14 → 18 (Body Large). For a chat-reading surface, 14/20 Body is native; offering an optional 16/24 "reading" size is a deliberate deviation worth a setting.
- Code font: Windows ships Cascadia Code/Mono with Terminal, but Fluent's token says Consolas; Ichos can prefer `'Cascadia Code', Consolas, monospace` (inference — not from a cited source).

### Gaps
- M3 line heights and tracking (m3.material.io is client-rendered). M3 Expressive "emphasized" type scale weights confirmed only from the Android doc above.

---

## 3. Spacing, radius, elevation/shadow, motion

### Takeaway
Fluent gives a complete, small set: a 4px-based spacing ladder with "nudge" steps (2,4,6,8,10,12,16,20,24,32), radii 4 (controls) / 8 (overlays/windows), two-layer shadows with dark-specific alpha, and 8 durations (50–500ms) with named curves. M3 and Carbon add useful spring and "productive vs expressive" motion distinctions.

### Cited Findings

**Spacing**
- Fluent spacing tokens (horizontal and vertical identical): None 0, XXS 2, XS 4, SNudge 6, S 8, MNudge 10, M 12, L 16, XL 20, XXL 24, XXXL 32 — [fluentui spacings.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/spacings.ts).
- Windows 11 layout gaps: 8epx between buttons; 8epx between button and flyout; 8epx between control and header; 12epx between control and label; 12epx between content areas; 16epx between surface edge and text; 16epx between control and expander button; 48epx indent for controls inside an expander — [Content layout and spacing](https://learn.microsoft.com/en-us/windows/apps/design/basics/content-basics).

**Radius**
- Windows 11: 8px for top-level containers (app windows, flyouts, dialogs, ContentDialog, MenuFlyout, TeachingTip); 4px for in-page controls (Button, CheckBox, ComboBox, TextBox, ListView, list backplates) and bar elements (ProgressBar, ScrollBar, Slider) and ToolTip; 0px where straight edges meet (SplitButton halves, flyout edge attached to its invoker) and for snapped/maximized windows. Global resources `ControlCornerRadius` = 4, `OverlayCornerRadius` = 8 — [Geometry in Windows 11](https://learn.microsoft.com/en-us/windows/apps/design/signature-experiences/geometry).
- Fluent web radius tokens: None 0, Small 2, Medium 4, Large 6, XLarge 8, 2XLarge 12, 3XLarge 16, 4XLarge 24, 5XLarge 32, 6XLarge 40, Circular 10000px — [fluentui borderRadius.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/borderRadius.ts).
- M3 shape scale: None 0, Extra Small 4, Small 8, Medium 12, Large 16, Large Increased 20, Extra Large 28, Extra Large Increased 32, Extra Extra Large 48, Full 50% — [MDC-Android Shape.md](https://github.com/material-components/material-components-android/blob/master/docs/theming/Shape.md).
- shadcn default `--radius: 0.625rem` — [shadcn theming](https://ui.shadcn.com/docs/theming).

**Elevation / shadow**
- Windows 11 elevation values (all with 1px stroke): Window 128, Dialog 128, Flyout 32, Tooltip 16, Card 8, Control 2, Layer 1; control states Rest 2, Hover 2, Pressed 1. "The intensity of the rendered shadow changes depending on the theme" — [Layering and elevation](https://learn.microsoft.com/en-us/windows/apps/design/signature-experiences/layering).
- Fluent web shadow recipe (ambient layer, key layer): shadow2 `0 0 2px A, 0 1px 2px K`; shadow4 `0 0 2px A, 0 2px 4px K`; shadow8 `0 0 2px A, 0 4px 8px K`; shadow16 `0 0 2px A, 0 8px 16px K`; shadow28 `0 0 8px A, 0 14px 28px K`; shadow64 `0 0 8px A, 0 32px 64px K` — [fluentui shadows.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/utils/shadows.ts). Dark A = rgba(0,0,0,0.24), K = rgba(0,0,0,0.28) — [darkColor.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/alias/darkColor.ts).
- Atlassian dark overlay shadow adds a 1px light ring (#BDBDBD1F) to separate overlays from dark surfaces — [atlassian-dark](https://unpkg.com/@atlaskit/tokens/dist/esm/artifacts/themes/atlassian-dark.js).

**Motion**
- Fluent durations: UltraFast 50ms, Faster 100, Fast 150, Normal 200, Gentle 250, Slow 300, Slower 400, UltraSlow 500 — [fluentui durations.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/durations.ts).
- Fluent curves: AccelerateMax (0.9,0.1,1,0.2); AccelerateMid (1,0,1,1); AccelerateMin (0.8,0,0.78,1); DecelerateMax (0.1,0.9,0.2,1); DecelerateMid (0,0,0,1); DecelerateMin (0.33,0,0.1,1); EasyEaseMax (0.8,0,0.2,1); EasyEase (0.33,0,0.67,1); Linear (0,0,1,1) — [fluentui curves.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/curves.ts).
- Material 3 durations: Short1–4 = 50/100/150/200ms; Medium1–4 = 250/300/350/400; Long1–4 = 450/500/550/600; ExtraLong1–4 = 700/800/900/1000. Easings: emphasizedDecelerate (0.05,0.7,0.1,1); emphasizedAccelerate (0.3,0,0.8,0.15); standard (0.2,0,0,1); standardDecelerate (0,0,0,1); standardAccelerate (0.3,0,1,1); emphasized is a two-segment path — [MDC-Android Motion.md](https://github.com/material-components/material-components-android/blob/master/docs/theming/Motion.md).
- M3 Expressive spring tokens (damping ratio / stiffness): FastSpatial 0.9/1400; DefaultSpatial 0.9/700; SlowSpatial 0.9/300; FastEffects 1/3800; DefaultEffects 1/1600; SlowEffects 1/800. "Spatial" = position/size; "Effects" = opacity/colour (critically damped, no bounce) — [Motion.md](https://github.com/material-components/material-components-android/blob/master/docs/theming/Motion.md). Note: that doc's per-component tables contain inconsistencies (e.g. one table lists standard as (0.4,0,0.2,1)) — same source.
- Carbon motion: productive vs expressive. standard productive (0.2,0,0.38,0.9) / expressive (0.4,0.14,0.3,1); entrance productive (0,0,0.38,0.9) / expressive (0,0,0.3,1); exit productive (0.2,0,1,0.9) / expressive (0.4,0.14,1,1). Durations fast-01 70ms, fast-02 110, moderate-01 150, moderate-02 240, slow-01 400, slow-02 700 — [@carbon/motion](https://cdn.jsdelivr.net/npm/@carbon/motion/src/index.js).
- Rovo: "Motion shows state and progress, guides attention"; AI expression is "invisible until needed, present while working, fully expressive when AI is front and center" — [About Rovo UI](https://atlassian.design/rovo-ui/about-rovo-ui).

### Inferences
- All three systems agree: micro-interactions 50–150ms, standard transitions 200–300ms, large/overlay transitions 300–500ms; decelerate on enter, accelerate on exit.
- Carbon's "productive vs expressive" split maps neatly onto Ichos: productive for chrome and controls, expressive (or M3 Effects springs) reserved for AI-presence moments, consistent with Rovo's "invisible until needed".

### Gaps
- Windows/WinUI's own control-level animation timings (e.g. ControlFasterAnimationDuration) not retrieved.

---

## 4. Focus rings and minimum target sizes

### Takeaway
Windows' focus visual is a **2px outer + 1px inner double ring with a 1px margin** (white outer, 70%-black inner in dark), shown for keyboard focus; Fluent web reproduces it as a 2px `colorStrokeFocus2` outline at radius 4. Targets: 40×40 epx standard, 32×32 compact (pointer); type minimum 12px Regular.

### Cited Findings
- Windows high-visibility focus visual: primary border **2px**, running *outside* a secondary border of **1px**; default margin **1px** from control bounds; brushes `SystemControlFocusVisualPrimaryBrush` / `SecondaryBrush` can be overridden app-wide; per-control `FocusVisualPrimaryThickness`, `FocusVisualSecondaryThickness`, `FocusVisualMargin`, `UseSystemFocusVisuals` — [Visual feedback](https://learn.microsoft.com/en-us/windows/apps/develop/input/guidelines-for-visualfeedback).
- Dark focus colours: FocusStrokeColorOuter #FFFFFF, FocusStrokeColorInner #B3000000 — [wpfui Dark.xaml](https://github.com/lepoco/wpfui/blob/main/src/Wpf.Ui/Resources/Theme/Dark.xaml).
- Fluent React v9 focus outline: width hardcoded `2px`, colour `colorStrokeFocus2` (white in dark), radius `borderRadiusMedium` (4px), default offset `calc(2px * -1)` i.e. drawn inset — [createFocusOutlineStyle.ts](https://github.com/microsoft/fluentui/blob/master/packages/react-components/react-tabster/src/focus/createFocusOutlineStyle.ts). Fluent dark defines colorStrokeFocus1 black / colorStrokeFocus2 white for the two rings — [darkColor.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/alias/darkColor.ts).
- Carbon dark: focus #ffffff with focus-inset #161616 (same double-ring idea) — [@carbon/themes g100](https://cdn.jsdelivr.net/npm/@carbon/themes/src/g100.js); Atlassian dark border.focused #8FB8F6 — [atlassian-dark](https://unpkg.com/@atlaskit/tokens/dist/esm/artifacts/themes/atlassian-dark.js).
- Target size: "set your touch target size to 7.5mm square range (40x40 pixels on a 135 PPI display at a 1.0x scaling plateau)"; enlarge frequently pressed targets; targets with severe consequences need more padding and distance from edges — [Targeting](https://learn.microsoft.com/en-us/windows/apps/develop/input/guidelines-for-targeting).
- Standard sizing aligns items to a 40×40 epx target (touch + pointer); Compact sizing to 32×32 epx (primarily pointer), applied via a resource dictionary — [Windows spacing doc (GitHub)](https://github.com/MicrosoftDocs/windows-dev-docs/blob/docs/hub/apps/design/style/spacing.md) (via search snippet; the live page now redirects to content-basics).
- Text minimums 14px Semibold / 12px Regular — [Typography in Windows](https://learn.microsoft.com/en-us/windows/apps/design/signature-experiences/typography).

### Inferences
- Use `:focus-visible` only (keyboard), never on mouse click — matches Windows' "keyboard input and navigation uses focus rectangles" model.
- For dense desktop chrome (title bar buttons, message action icons) Ichos can use 32px compact targets; primary actions (send, approve/deny) should stay ≥40px.

### Gaps
- Fluent 2 web control heights (Button small/medium/large) not verified from source this session.

---

## 5. AI-specific components and rules

### Takeaway
The systems agree on six primitives: **(1) a persistent AI label/disclosure** that is also the entry to an explanation; **(2) layered explainability** (short popover first, details on request); **(3) source citations inline**; **(4) calibrated, not decorative, confidence**; **(5) visible plan/stream-of-thought with pause/stop**; **(6) human verification before consequential actions, plus easy correction/revert and feedback**. AI visual styling (glow, gradient, colour) is reserved to *identify* AI, never decoration.

### Cited Findings

**Carbon for AI (IBM)**
- Every AI component must embed an **AI label** plus **explainability popover**; label any AI-generated or AI-recommended content "from a single word to the whole page"; AI styling is not decoration — [Carbon for AI](https://carbondesignsystem.com/guidelines/carbon-for-ai/).
- AI presence styling = light-inspired effects (brightness, glow, gradients) with subtle, limited spread on container edges; tokens live inside the normal themes ("AI presence" mode); show explanations only when needed or requested — [Carbon for AI](https://carbondesignsystem.com/guidelines/carbon-for-ai/).
- If the user edits AI-suggested content the component switches to the default (non-AI) variant, and a **revert-to-AI** button restores the original — [Carbon for AI](https://carbondesignsystem.com/guidelines/carbon-for-ai/); in inputs the AI label becomes a revert icon once the value is cleared/modified — [AI label accessibility](https://carbondesignsystem.com/components/ai-label/accessibility/).
- AI label keyboard: Enter/Space toggles popover, focus stays on trigger; Tab moves into interactive popover content; Esc closes and returns focus — [AI label accessibility](https://carbondesignsystem.com/components/ai-label/accessibility/).
- Carbon g100 AI tokens: ai-aura-start rgba(blue50 #4589ff, 0.10); ai-aura-start-sm rgba(blue50, 0.16); ai-aura-end rgba(black, 0); ai-aura-hover-start rgba(blue50, 0.40); ai-border-start rgba(blue30 #a6c8ff, 0.36); ai-border-end blue50 #4589ff; ai-border-strong blue40 #78a9ff; ai-inner-shadow rgba(blue50, 0.16); ai-drop-shadow rgba(black, 0.28); ai-popover-background gray100 #161616; ai-popover-shadow-outer-01/02 rgba(black,0.12)/(0.08); ai-skeleton-background rgba(blue40, 0.5); ai-skeleton-element-background rgba(blue40, 0.3); ai-overlay rgba(black, 0.5) — [@carbon/themes g100](https://cdn.jsdelivr.net/npm/@carbon/themes/src/g100.js).

**Microsoft HAX — 18 Guidelines for Human-AI Interaction** (verbatim titles) — [HAX Design Library](https://www.microsoft.com/en-us/haxtoolkit/library/):
1 Make clear what the system can do · 2 Make clear how well the system can do what it can do · 3 Time services based on context · 4 Show contextually relevant information · 5 Match relevant social norms · 6 Mitigate social biases · 7 Support efficient invocation · 8 Support efficient dismissal · 9 Support efficient correction · 10 Scope services when in doubt · 11 Make clear why the system did what it did · 12 Remember recent interactions · 13 Learn from user behavior · 14 Update and adapt cautiously · 15 Encourage granular feedback · 16 Convey the consequences of user actions · 17 Provide global controls · 18 Notify users about changes. Phases: initially, during interaction, when wrong, over time — [HAX AI guidelines](https://www.microsoft.com/en-us/haxtoolkit/ai-guidelines/).
- Copilot in Outlook pattern 2D ("low performance alert"): persistent low-key note "AI-generated content may be incorrect" at the bottom-right of the draft, not a modal — [HAX example](https://www.microsoft.com/en-us/haxtoolkit/example/copilot-in-outlook-g2-d-provide-low-performance-alerts/).

**Google PAIR (Explainability + Trust chapter)** — [PAIR](https://pair.withgoogle.com/chapter/explainability-trust/):
- Goal is calibrated trust: rely where it performs well, double-check where it doesn't. Scale explanation depth to stakes: "Don't say 'what' without saying 'why' in a high stakes scenario."
- Explain data sources by **scope, reach, removal**; tell users when missing data means they should use their own judgment.
- Confidence: skip it if it doesn't change decisions; categorical (High/Med/Low) needs defined cutoffs and a stated action per category; **N-best alternatives** suit low-confidence cases; numeric % "use with caution"; don't present high confidence in a way that discourages checking.
- Partial explanations are usually the best starting point; tie explanations to user actions.

**The Shape of AI (shapeof.ai)** — 60 patterns in 6 groups — [shapeof.ai](https://www.shapeof.ai/):
- Governors: **Action plan** (show steps before executing), **Branches**, **Citations** (inline annotations), **Controls** (pause a request mid-stream), **Cost estimates**, **Draft mode**, **Memory** (user controls what AI knows), **References**, **Sample response**, **Shared vision**, **Stream of Thought** (reasoning, tool use, decisions for oversight/audit), **Variations**, **Verification** (confirm decisions/actions before proceeding).
- Trust builders: Caveat, Consent, Data ownership, Disclosure, Footprints (trace steps prompt→result), Incognito mode, Watermark.
- Identifiers: Avatar, Color, Iconography, Name, Personality. Wayfinders: Example gallery, Follow up, Initial CTA, Nudges, Prompt details, Randomize, Suggestions, Templates. Tuners: Attachments, Connectors, Filters, Model management, Modes, Parameters, Preset/Saved styles, Prompt enhancer, Voice and tone.

**Atlassian Rovo** — [About Rovo UI](https://atlassian.design/rovo-ui/about-rovo-ui); [AI and Rovo patterns](https://atlassian.design/patterns/ai-rovo):
- "People should always know when they're interacting with AI and when they're not"; AI should feel integrated, not "a third-party app added on"; Rovo UI ships a **generative border** component and a **skills tag**; message cards are bordered containers in chat for summaries, **action confirmations**, or linked content.

**Salesforce (Agentforce / SLDS 2)** — [Salesforce AI agent design tips](https://www.salesforce.com/blog/ai-agent-design-tips/):
- Each agent conversation includes: welcome message, **disclosure statement**, example questions, **scope boundaries**, and a path to give feedback or escalate.
- Standard disclosure: "I may make mistakes, so review my responses for accuracy," in the welcome message or just below the input.
- Names: "Name + Agent", first part <10 characters, 1–2 words; consistent icons, colour, voice, and standardized avatars signal agentic experiences. Heuristics: consistency, error tolerance, teachability.
- SLDS 2 is positioned as the foundation for Salesforce's agentic design system; it is beta — [What is SLDS 2](https://www.salesforce.com/blog/what-is-slds-2/).

**Nielsen Norman Group (2026)** — [NN/g AI topic](https://www.nngroup.com/topic/ai/):
- "When Should You Disclose AI Use? The PACED Framework" (Sep 25 2026): audience reactions to AI involvement vary; framework for disclosure decisions.
- "The 3 Roles of Context for AI Agents" (Sep 18 2026): global, task-specific, and ambient context.
- "One AI Output Is an Example, Not an Evaluation" (Aug 14 2026): use multiple inputs, repeated runs, confidence ranges.
- "The 5 Qualities of Site-Specific AI Chatbots" (Jul 10 2026): handoff willingness, flexibility, initiative, emotional responsiveness, transparency.
- "The New Siri's Biggest Strength Is Not Intelligence" (Oct 9 2026): assistants need personal context, ability to act, and clear communication of limits.
(Summaries are from the topic page's teasers, not full articles.)

### Inferences
- A local-first assistant has a disclosure advantage: "runs on this PC / nothing leaves the device" is itself a PAIR "scope/reach/removal" data explanation and should live in the AI label popover.
- Carbon's AI token recipe (10% accent aura, 36% light-accent border start → solid accent border end, accent-tinted skeleton) is directly re-colourable to Ichos' accent.

### Gaps
- SLDS 2 "Agentic Experience Patterns" page content, Fluent 2 / Copilot AI component docs, Atlassian AI interaction guidelines page, and full PAIR pattern list could not be fetched (client-rendered or 404). No authoritative Fluent spec for a citation component was found.

---

## 6. Token naming conventions worth copying

### Takeaway
Copy Fluent's **category → concept → variant(number) → state** shape for colour, Atlassian/Primer's dotted semantic paths for readability, shadcn's surface/`-foreground` pairing for component theming, and Geist/Radix's "step = role" scales for the primitive layer.

### Cited Findings
- Fluent: `colorNeutralForeground1..4`, `colorNeutralBackground1..6`, `colorNeutralBackground1Hover/Pressed`, `colorBrandForeground1`, `colorStrokeFocus2` (category+concept+rank+state) — [darkColor.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/alias/darkColor.ts); size tokens `spacingHorizontalSNudge`, `borderRadiusXLarge`, `durationGentle`, `curveDecelerateMid` — [fluentui global tokens](https://github.com/microsoft/fluentui/tree/master/packages/tokens/src/global).
- WinUI: role-first names `TextFillColorPrimary/Secondary/Tertiary/Disabled`, `ControlFillColorDefault/Secondary/Tertiary/Disabled`, `LayerFillColorDefault`, `SolidBackgroundFillColorBase` — [wpfui Dark.xaml](https://github.com/lepoco/wpfui/blob/main/src/Wpf.Ui/Resources/Theme/Dark.xaml).
- Primer: `bgColor.default/muted/inset/emphasis`, `fgColor.default/muted/disabled/onEmphasis`, `bgColor.accent.emphasis/muted` — [Primer functional tokens](https://github.com/primer/primitives/tree/main/src/tokens/functional/color).
- Atlassian: `elevation.surface.sunken/raised/overlay`, `color.text.subtle/subtlest/disabled`, `color.border.focused` → CSS `--ds-*` — [atlassian-dark](https://unpkg.com/@atlaskit/tokens/dist/esm/artifacts/themes/atlassian-dark.js).
- shadcn: semantic pairs `primary` / `primary-foreground`, with "background" suffix omitted — [shadcn theming](https://ui.shadcn.com/docs/theming).
- Carbon: layering tokens `layer-01/02/03` that auto-alternate per nesting, `ai-*` family in the main theme — [@carbon/themes g100](https://cdn.jsdelivr.net/npm/@carbon/themes/src/g100.js).
- Geist: scale steps carry roles (100–300 bg, 400–600 border, 700–800 solid, 900–1000 text) — [Geist colors](https://vercel.com/geist/colors).

### Inferences
- Recommended Ichos convention: `--ichos-{category}-{role}[-{variant}][-{state}]`, e.g. `--ichos-text-secondary`, `--ichos-fill-control-hover`, `--ichos-stroke-divider`, `--ichos-ai-border-start`. Keep a primitive layer (`--ichos-grey-16`, `--ichos-accent-100`) that only semantic tokens reference.

### Gaps
- None material.

---

## 7. Recommended Ichos token set

### Takeaway
Base Ichos on the **Windows 11 (WinUI) dark resource set** so it looks native over Mica, with Fluent web tokens filling in sizing, shadow, motion and the brand ramp, Carbon's AI-presence recipe for AI identification, and M3 springs only for AI-presence moments. All values below are dark; light should be derived by swapping to the corresponding Fluent `webLightTheme` / WinUI Light values rather than inverting.

### Cited Findings
Proposed semantic tokens (source column = where the value comes from):

**Surfaces**
| Ichos token | Dark value | Source |
|---|---|---|
| --ichos-bg-app (Mica fallback / solid window) | #202020 | WinUI SolidBackgroundFillColorBase — [wpfui](https://github.com/lepoco/wpfui/blob/main/src/Wpf.Ui/Resources/Theme/Dark.xaml) |
| --ichos-bg-app-secondary (sidebar, sunken) | #1C1C1C | WinUI SolidBackgroundFillColorSecondary — same |
| --ichos-bg-layer (content layer over Mica) | rgba(58,58,58,0.30) | WinUI LayerFillColorDefault #4C3A3A3A — same |
| --ichos-bg-layer-solid (no-Mica equivalent) | #282828 | WinUI SolidBackgroundFillColorTertiary — same |
| --ichos-bg-card | rgba(255,255,255,0.051) | WinUI CardBackgroundFillColorDefault — same |
| --ichos-bg-flyout (menus, popovers, solid) | #2C2C2C | WinUI SolidBackgroundFillColorQuaternary — same |
| --ichos-bg-scrim | rgba(0,0,0,0.30) | WinUI SmokeFillColorDefault — same |

**Text**
| Ichos token | Dark value | Source |
|---|---|---|
| --ichos-text-primary | #FFFFFF | WinUI TextFillColorPrimary — [MS XAML theme resources](https://learn.microsoft.com/windows/apps/design/style/xaml-theme-resources) |
| --ichos-text-secondary | rgba(255,255,255,0.773) | TextFillColorSecondary #C5FFFFFF — [wpfui](https://github.com/lepoco/wpfui/blob/main/src/Wpf.Ui/Resources/Theme/Dark.xaml) |
| --ichos-text-tertiary (timestamps, meta) | rgba(255,255,255,0.53) | TextFillColorTertiary #87FFFFFF — same |
| --ichos-text-disabled | rgba(255,255,255,0.365) | TextFillColorDisabled #5DFFFFFF — same |
| --ichos-text-accent (links, accent text) | #479EF5 | Fluent colorBrandForeground1 = brand[100] — [darkColor.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/alias/darkColor.ts) |
| --ichos-text-on-accent | #FFFFFF | Fluent colorNeutralForegroundOnBrand — same |

**Fills (controls)**
| Ichos token | Dark value | Source |
|---|---|---|
| --ichos-fill-control | rgba(255,255,255,0.059) | ControlFillColorDefault — [wpfui](https://github.com/lepoco/wpfui/blob/main/src/Wpf.Ui/Resources/Theme/Dark.xaml) |
| --ichos-fill-control-hover | rgba(255,255,255,0.082) | ControlFillColorSecondary — same |
| --ichos-fill-control-pressed | rgba(255,255,255,0.031) | ControlFillColorTertiary — same |
| --ichos-fill-control-disabled | rgba(255,255,255,0.043) | ControlFillColorDisabled — same |
| --ichos-fill-subtle-hover / pressed | rgba(255,255,255,0.059) / rgba(255,255,255,0.039) | SubtleFillColorSecondary / Tertiary — same |
| --ichos-fill-accent | #115EA3 | Fluent colorBrandBackground (brand[70]) — [darkColor.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/alias/darkColor.ts) |
| --ichos-fill-accent-hover | #0F6CBD | colorBrandBackgroundHover (brand[80]) — same |
| --ichos-fill-accent-pressed | #0C3B5E | colorBrandBackgroundPressed (brand[40]) — same |

**Strokes**
| Ichos token | Dark value | Source |
|---|---|---|
| --ichos-stroke-control | rgba(255,255,255,0.07) | ControlStrokeColorDefault — [wpfui](https://github.com/lepoco/wpfui/blob/main/src/Wpf.Ui/Resources/Theme/Dark.xaml) |
| --ichos-stroke-control-strong (input/checkbox borders) | rgba(255,255,255,0.545) | ControlStrongStrokeColorDefault — same |
| --ichos-stroke-divider | rgba(255,255,255,0.082) | DividerStrokeColorDefault — same |
| --ichos-stroke-card | rgba(0,0,0,0.098) | CardStrokeColorDefault — same |
| --ichos-stroke-surface | rgba(117,117,117,0.40) | SurfaceStrokeColorDefault — same |
| --ichos-stroke-flyout | rgba(0,0,0,0.20) | SurfaceStrokeColorFlyout — same |

**Status**
| Ichos token | Dark value | Source |
|---|---|---|
| --ichos-status-critical | #FF99A4 | SystemFillColorCritical — [wpfui](https://github.com/lepoco/wpfui/blob/main/src/Wpf.Ui/Resources/Theme/Dark.xaml) |
| --ichos-status-success | #6CCB5F | SystemFillColorSuccess — same |
| --ichos-status-caution | #FCE100 | SystemFillColorCaution — same |

**Focus**
| Ichos token | Value | Source |
|---|---|---|
| --ichos-focus-outer | 2px solid #FFFFFF | Windows focus primary border 2px — [Visual feedback](https://learn.microsoft.com/en-us/windows/apps/develop/input/guidelines-for-visualfeedback); FocusStrokeColorOuter — [wpfui](https://github.com/lepoco/wpfui/blob/main/src/Wpf.Ui/Resources/Theme/Dark.xaml) |
| --ichos-focus-inner | 1px solid rgba(0,0,0,0.70) | secondary border 1px; FocusStrokeColorInner #B3000000 — same two sources |
| --ichos-focus-margin | 1px | default FocusVisualMargin — [Visual feedback](https://learn.microsoft.com/en-us/windows/apps/develop/input/guidelines-for-visualfeedback) |

**Type** (font stack `"Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", system-ui, sans-serif`; display sizes may use "Segoe UI Variable Display")
| Ichos token | Size/LH/weight | Source |
|---|---|---|
| --ichos-type-caption | 12/16/400 | [Windows type ramp](https://learn.microsoft.com/en-us/windows/apps/design/signature-experiences/typography) |
| --ichos-type-body | 14/20/400 | same |
| --ichos-type-body-strong | 14/20/600 | same |
| --ichos-type-body-large | 18/24/400 | same |
| --ichos-type-subtitle | 20/28/600 | same |
| --ichos-type-title | 28/36/600 | same |
| --ichos-type-title-large | 40/52/600 | same |
| --ichos-type-display | 68/92/600 | same |
| --ichos-font-mono | Consolas, "Courier New", monospace | [Fluent fontFamilyMonospace](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/fonts.ts) |

**Spacing / radius / size**
| Ichos token | Value | Source |
|---|---|---|
| --ichos-space-{xxs,xs,s-nudge,s,m-nudge,m,l,xl,xxl,xxxl} | 2,4,6,8,10,12,16,20,24,32px | [Fluent spacings.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/spacings.ts) |
| --ichos-gap-controls / control-label / content-areas / surface-edge | 8 / 12 / 12 / 16px | [Content layout and spacing](https://learn.microsoft.com/en-us/windows/apps/design/basics/content-basics) |
| --ichos-radius-small | 2px | [Fluent borderRadius.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/borderRadius.ts) |
| --ichos-radius-control | 4px | ControlCornerRadius — [Geometry](https://learn.microsoft.com/en-us/windows/apps/design/signature-experiences/geometry) |
| --ichos-radius-overlay | 8px | OverlayCornerRadius (windows, flyouts, dialogs) — same |
| --ichos-radius-large (chat bubbles, composer) | 12px | Fluent borderRadius2XLarge — [borderRadius.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/borderRadius.ts) |
| --ichos-radius-circular | 10000px | Fluent borderRadiusCircular — same |
| --ichos-target-min / --ichos-target-compact | 40px / 32px | [Targeting](https://learn.microsoft.com/en-us/windows/apps/develop/input/guidelines-for-targeting); [spacing doc](https://github.com/MicrosoftDocs/windows-dev-docs/blob/docs/hub/apps/design/style/spacing.md) |

**Elevation** (A = rgba(0,0,0,0.24), K = rgba(0,0,0,0.28))
| Ichos token | Value | Use (Windows elevation) | Source |
|---|---|---|---|
| --ichos-shadow-2 | 0 0 2px A, 0 1px 2px K | controls (elev 2) | [Fluent shadows.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/utils/shadows.ts); [darkColor.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/alias/darkColor.ts); [Layering](https://learn.microsoft.com/en-us/windows/apps/design/signature-experiences/layering) |
| --ichos-shadow-8 | 0 0 2px A, 0 4px 8px K | cards (elev 8) | same |
| --ichos-shadow-16 | 0 0 2px A, 0 8px 16px K | tooltips (elev 16) | same |
| --ichos-shadow-28 | 0 0 8px A, 0 14px 28px K | flyouts/menus (elev 32) | same |
| --ichos-shadow-64 | 0 0 8px A, 0 32px 64px K | dialogs (elev 128) | same |

**Motion**
| Ichos token | Value | Source |
|---|---|---|
| --ichos-duration-{ultra-fast,faster,fast,normal,gentle,slow,slower,ultra-slow} | 50,100,150,200,250,300,400,500ms | [Fluent durations.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/durations.ts) |
| --ichos-ease-enter | cubic-bezier(0,0,0,1) (DecelerateMid) | [Fluent curves.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/curves.ts) |
| --ichos-ease-exit | cubic-bezier(1,0,1,1) (AccelerateMid) | same |
| --ichos-ease-standard | cubic-bezier(0.33,0,0.67,1) (EasyEase) | same |
| --ichos-ease-emphasized | cubic-bezier(0.8,0,0.2,1) (EasyEaseMax) | same |
| --ichos-spring-ai-effects | damping 1, stiffness 1600 | M3 DefaultEffects — [MDC Motion.md](https://github.com/material-components/material-components-android/blob/master/docs/theming/Motion.md) |
| --ichos-spring-ai-spatial | damping 0.9, stiffness 700 | M3 DefaultSpatial — same |

**AI presence** (Carbon recipe, re-coloured to Ichos accent)
| Ichos token | Dark value | Source |
|---|---|---|
| --ichos-ai-aura-start | rgba(71,158,245,0.10) | Carbon ai-aura-start = accent @ 0.10 — [g100.js](https://cdn.jsdelivr.net/npm/@carbon/themes/src/g100.js) |
| --ichos-ai-aura-start-sm | rgba(71,158,245,0.16) | Carbon ai-aura-start-sm @ 0.16 — same |
| --ichos-ai-aura-end | rgba(0,0,0,0) | Carbon ai-aura-end — same |
| --ichos-ai-border-start | rgba(150,198,250,0.36) | Carbon ai-border-start = light accent @ 0.36 (Fluent brand[130] #96c6fa) — same + [brandColors.ts](https://github.com/microsoft/fluentui/blob/master/packages/tokens/src/global/brandColors.ts) |
| --ichos-ai-border-end | #479EF5 | Carbon ai-border-end = solid accent — same |
| --ichos-ai-skeleton | rgba(71,158,245,0.30) | Carbon ai-skeleton-element-background @ 0.3 — [g100.js](https://cdn.jsdelivr.net/npm/@carbon/themes/src/g100.js) |
| --ichos-ai-drop-shadow | rgba(0,0,0,0.28) | Carbon ai-drop-shadow — same |

### Inferences
- The accent hues above use Fluent's default web brand blue; if Ichos picks its own brand hue, keep the *step structure* (fill ≈ tone 40–45, hover one step lighter, pressed darker, text ≈ tone 65–75) rather than the hex. Alternatively follow the Windows system accent colour (inference; not researched here).
- #479EF5 on #202020 and white on #115EA3 should both clear 4.5:1 by approximate calculation; verify with a contrast checker before locking.
- Using translucent fills for controls/cards means Ichos inherits Mica tint automatically when the host window (Electron `backgroundMaterial` / Tauri window-vibrancy) enables it — implementation detail not verified in this sweep.
- Respect `prefers-reduced-motion`: drop springs and aura animation, keep instant state changes (inference consistent with Rovo's "motion shows state", not a cited rule).

### Gaps
- Light-theme counterparts were not collected (task scope was dark-first).
- `SolidBackgroundFillColorBaseAlt` (for a Mica-Alt-style tabbed title bar) not retrieved.

---

## 8. AI-UX rules Ichos should adopt

### Takeaway
Twenty rules, each traceable to a published guideline; together they cover disclosure, explainability, citations, confidence, generation states, human-in-the-loop, correction, feedback, memory/data control, and change notices.

### Cited Findings
1. **Label every AI output** (word to page) with a persistent AI label that doubles as the explainability trigger — [Carbon for AI](https://carbondesignsystem.com/guidelines/carbon-for-ai/); [shapeof.ai Disclosure](https://www.shapeof.ai/).
2. **Use AI styling only to identify AI**, never as decoration; apply AI colour to signifiers, not whole surfaces — [Carbon for AI](https://carbondesignsystem.com/guidelines/carbon-for-ai/); [Rovo UI](https://atlassian.design/rovo-ui/about-rovo-ui).
3. **Layered explainability**: a short popover first, deeper "why" on request; scale depth to stakes and never give "what" without "why" for high-stakes actions — [Carbon for AI](https://carbondesignsystem.com/guidelines/carbon-for-ai/); [PAIR](https://pair.withgoogle.com/chapter/explainability-trust/); HAX G11 — [HAX](https://www.microsoft.com/en-us/haxtoolkit/library/).
4. **State capabilities and limits up front** (welcome state: what it can do, example prompts, scope boundaries) — HAX G1 — [HAX](https://www.microsoft.com/en-us/haxtoolkit/library/); [Salesforce tips](https://www.salesforce.com/blog/ai-agent-design-tips/).
5. **Persistent, low-key accuracy caveat** near the composer or output (e.g. "Ichos can make mistakes — check important info"), not a modal — HAX G2 / pattern 2D — [HAX example](https://www.microsoft.com/en-us/haxtoolkit/example/copilot-in-outlook-g2-d-provide-low-performance-alerts/); [Salesforce tips](https://www.salesforce.com/blog/ai-agent-design-tips/).
6. **Explain data scope, reach and removal** in the label popover (for Ichos: local model, what files/memory were used, how to delete) — [PAIR](https://pair.withgoogle.com/chapter/explainability-trust/).
7. **Inline citations** tied to the claims they support, with a references panel to inspect/manage sources — [shapeof.ai Citations, References](https://www.shapeof.ai/).
8. **Show confidence only when it changes a decision**; prefer categorical (with defined cutoffs and an implied action) or N-best alternatives over raw percentages — [PAIR](https://pair.withgoogle.com/chapter/explainability-trust/).
9. **Generation-in-progress is visible and interruptible**: stream output, expose plan/tool steps (stream of thought), and provide stop/pause mid-stream — [shapeof.ai Stream of Thought, Controls](https://www.shapeof.ai/); motion should "show state and progress" — [Rovo UI](https://atlassian.design/rovo-ui/about-rovo-ui).
10. **AI-tinted skeletons** for pending AI content (accent @ 0.3/0.5), distinct from neutral loading — [Carbon g100 ai-skeleton tokens](https://cdn.jsdelivr.net/npm/@carbon/themes/src/g100.js).
11. **Show the action plan before execution** for multi-step agent work — [shapeof.ai Action plan](https://www.shapeof.ai/).
12. **Human verification before consequential actions** (file writes, sends, deletes): an explicit approve/deny card stating the consequence — [shapeof.ai Verification](https://www.shapeof.ai/); HAX G16 — [HAX](https://www.microsoft.com/en-us/haxtoolkit/library/); Rovo action-confirmation message cards — [Atlassian AI patterns](https://atlassian.design/patterns/ai-rovo); consequential targets get extra padding/distance — [Targeting](https://learn.microsoft.com/en-us/windows/apps/develop/input/guidelines-for-targeting).
13. **Efficient correction and revert**: editing AI content drops the AI styling; keep a "revert to AI version" control — HAX G9 — [HAX](https://www.microsoft.com/en-us/haxtoolkit/library/); [Carbon for AI](https://carbondesignsystem.com/guidelines/carbon-for-ai/).
14. **Efficient invocation and dismissal**: one keystroke/button to invoke, one to dismiss suggestions — HAX G7, G8 — [HAX](https://www.microsoft.com/en-us/haxtoolkit/library/).
15. **Scope down when unsure**: ask a follow-up or offer variations rather than guessing — HAX G10 — [HAX](https://www.microsoft.com/en-us/haxtoolkit/library/); [shapeof.ai Follow up, Variations](https://www.shapeof.ai/).
16. **Granular feedback** on each response (thumbs + optional reason) and a path to escalate — HAX G15 — [HAX](https://www.microsoft.com/en-us/haxtoolkit/library/); [Salesforce tips](https://www.salesforce.com/blog/ai-agent-design-tips/).
17. **User-controlled memory** with view/edit/forget and an incognito (no-memory) mode — HAX G12, G17 — [HAX](https://www.microsoft.com/en-us/haxtoolkit/library/); [shapeof.ai Memory, Incognito, Data ownership](https://www.shapeof.ai/).
18. **Global controls** for what the assistant monitors and how it behaves (model choice, connectors, autonomy level) — HAX G17 — [HAX](https://www.microsoft.com/en-us/haxtoolkit/library/); [shapeof.ai Model management, Connectors](https://www.shapeof.ai/).
19. **Update cautiously and announce changes** (new model, new skill, changed behaviour) — HAX G14, G18 — [HAX](https://www.microsoft.com/en-us/haxtoolkit/library/).
20. **Consistent AI identity**: one name, one avatar/icon, one AI colour across surfaces; agent names short (<10 chars before "Agent") and specific — [Salesforce tips](https://www.salesforce.com/blog/ai-agent-design-tips/); [shapeof.ai Identifiers](https://www.shapeof.ai/); always make clear when the user is and isn't talking to AI — [Rovo UI](https://atlassian.design/rovo-ui/about-rovo-ui).
21. **Accessible AI label**: Enter/Space toggles popover with focus kept on trigger, Tab into content, Esc closes and returns focus — [Carbon AI label accessibility](https://carbondesignsystem.com/components/ai-label/accessibility/).
22. **Don't judge quality from one output**: test prompts/features with multiple inputs and repeated runs before shipping — [NN/g](https://www.nngroup.com/topic/ai/) ("One AI Output Is an Example, Not an Evaluation", Aug 2026).

### Inferences
- For a local-first app, rules 6, 17 and 18 are differentiators worth surfacing prominently (privacy is a product feature, not just a setting).
- Rules 11–12 should share one "approval card" component with the Rovo-style bordered message card layout, AI aura border, and ≥40px Approve/Deny targets.

### Gaps
- No published numeric thresholds were found for when to show confidence or how many N-best alternatives to show (PAIR says to test).
- NN/g PACED disclosure framework details not retrieved (only the teaser).
