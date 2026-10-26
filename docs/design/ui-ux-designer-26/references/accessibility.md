# Accessibility & Inclusive Design (2026)

Accessibility is a **gate, not a garnish**. Design it in from the first token; retrofitting costs 10×. This file is the a11y contract every screen the agent produces must pass. For the color engineering that _produces_ compliant values (OKLCH, P3, tokens), see [color](color.md); for motion timing rules, [motion-interaction](motion-interaction.md); for per-platform target sizes, [mobile-ios](mobile-ios.md) and [mobile-android](mobile-android.md).

## 2026 legal & standards baseline (what "compliant" means now)

| Thing | 2026 status | What it means for you |
|---|---|---|
| **WCAG 2.1 AA** | The operative legal floor (US ADA case law, EN 301 549, EAA) | Non-negotiable minimum. Ship nothing below it. |
| **WCAG 2.2 AA** | W3C Recommendation (Oct 2023); the **design target** | Adds 6 AA criteria (below). Build to 2.2 — it's a superset of 2.1. |
| **European Accessibility Act (EAA)** | **In force since 28 Jun 2025**, enforced across all 27 EU states | Applies to e-commerce, banking, ticketing, e-books, transport, consumer devices. Penalties to **€100,000 or 4% of revenue**; product withdrawal; public naming. First French lawsuits filed Nov 2025. Legacy services have until 28 Jun 2030. |
| **EN 301 549** | v3.2.1 = WCAG 2.1 AA today; **v4.x (2026)** will fold in WCAG 2.2 | The EAA's harmonized standard. Expect 2.2 to become the EU legal floor in 2026–27. |
| **WCAG 3.0** | Still **Working Draft**; realistic finalization ~2028–2030 | Do **not** design against it as a spec. Watch it; don't wait for it. |
| **APCA** | **Removed** from the WCAG 3 draft (2023); "exploratory" only. WCAG 3 contrast algorithm is officially **"yet to be determined."** | Use APCA as a **superior readability tuning tool**, but **conformance is still WCAG 2.x math**. Pass 2.x for the lawyers; tune with APCA for humans. |

**Rule of thumb:** target WCAG 2.2 AA everywhere; treat AAA as a stretch for body-text contrast and critical flows.

---

## WCAG 2.2 new success criteria (the 6 AA you must add over 2.1)

| SC | Level | Rule | Concrete build spec |
|---|---|---|---|
| **2.4.11 Focus Not Obscured (Min)** | AA | A focused element must **not be _entirely_ hidden** by author content (sticky headers, cookie bars, chat widgets). | Add `scroll-padding-top`/`scroll-margin` = sticky-header height. Test: Tab through with a sticky nav — the focus ring must never fully disappear behind it. |
| **2.5.7 Dragging Movements** | AA | Any drag interaction needs a **single-pointer (non-drag) alternative**, unless dragging is essential. | Sliders → also accept click-on-track + arrow keys + numeric input. Drag-to-reorder → also provide up/down buttons or a "move to…" menu. Kanban → context menu "Move to column". |
| **2.5.8 Target Size (Min)** | AA | Pointer targets ≥ **24×24 CSS px**, OR 24px spacing between smaller targets. | 24px is the _floor_. Ship **44×44 (iOS) / 48×48 dp (Android)** as the real target — see table below. |
| **3.2.6 Consistent Help** | A | Help mechanisms (contact, chat, FAQ link) appear in the **same relative order** on every page. | Put "Help/Support" in a fixed slot (e.g. header-end or footer). Don't move it per page. |
| **3.3.7 Redundant Entry** | A | Don't make users **re-enter info** they already gave in the same session. | Autofill "same as billing"; carry email/name across a multi-step flow; pre-fill or offer a selector. |
| **3.3.8 Accessible Authentication (Min)** | AA | **No cognitive-function test** (memorize, transcribe, solve a puzzle) unless an alternative exists. | **Allow paste** into all fields incl. OTP/password. Don't block password managers. Support `autocomplete="one-time-code"`, WebAuthn/passkeys, email magic links. CAPTCHAs must offer a non-cognitive path (e.g. device/token check). |

AAA extras to know: **2.4.12 Focus Not Obscured (Enhanced)** = _no_ part obscured; **2.4.13 Focus Appearance** = focus indicator ≥ 2px thick perimeter (or equal area) at ≥ 3:1 against adjacent colors; **3.3.9 Accessible Authentication (Enhanced)** = no cognitive test at all.

---

## Contrast: WCAG math (conformance) + APCA (readability)

**Conformance is measured in WCAG 2.x ratios. Full stop.** APCA Lc is a design aid, not a legal metric in 2026.

### WCAG 2.x thresholds (the pass/fail line)

| Content | AA | AAA |
|---|---|---|
| Body text (< 18px / < 14px bold) | **4.5:1** | 7:1 |
| Large text (≥ 24px, or ≥ 18.66px bold) | **3:1** | 4.5:1 |
| **Non-text** (icons, form borders, focus rings, chart strokes, toggles) — SC 1.4.11 | **3:1** vs adjacent colors | — |
| UI component states (hover/focus/checked) must remain distinguishable | 3:1 | — |
| Disabled controls | exempt (but keep ≥ 3:1 if actionable-looking) | — |

### APCA Lc guidance (use to _tune_, direction-aware, weight-aware)

APCA fixes WCAG 2's blind spots: it accounts for **text weight, size, and polarity** (dark-on-light ≠ light-on-dark).

| Use case | Min Lc (absolute value) |
|---|---|
| Large / bold headings, big UI labels | **~60** |
| Standard body text | **~75** |
| Small (< 16px) or thin-weight text, long-form reading | **~90** |
| Disabled / placeholder (intentionally low) | 30–45 |
| **Lc 15** | point of invisibility — never for meaningful content |

**Workflow:** design the palette in OKLCH ([color](color.md)) → verify **every** pair against WCAG 4.5/3 for conformance → sanity-check body/small text at APCA Lc ≥ 75/90 for real-world legibility. If a pair passes WCAG but feels thin (common with thin fonts on white), APCA will tell you — bump lightness.

❌ Don't rely on hue difference for contrast (red/green at same lightness ≈ 1:1 for many users).
❌ Don't let brand color for a primary button drop below 4.5:1 for its label.
✅ Test text over **images/video/gradients** at the worst-case pixel — add a scrim/overlay token if it fails.

---

## Keyboard access & visible focus

Everything operable by mouse/touch must be operable by keyboard alone, in a **logical order**, with a **visible** focus indicator, and **no traps**.

### Focus indicator — spec

```css
/* Kill the legacy always-on outline, restore it only for keyboard users */
:focus { outline: none; }                 /* do NOT leave this alone */
:focus-visible {
  outline: 2px solid var(--focus-ring, #4c8dff);
  outline-offset: 2px;                     /* 2px gap so the ring reads */
  border-radius: inherit;
}
/* High-visibility ring that works on any background: double-layer */
:focus-visible {
  box-shadow: 0 0 0 2px var(--bg), 0 0 0 4px var(--focus-ring);
}
```

- Ring ≥ **2px** thick, ≥ **3:1** contrast vs adjacent colors (WCAG 2.2 AAA 2.4.13; treat as AA-grade practice).
- Use `:focus-visible`, **not** `:focus`, so mouse clicks don't show rings but keyboard/AT does. Never `outline: none` without a replacement.
- Focus ring must be visible in **both** light and dark themes — token it, don't hardcode.

### Focus order & structure

✅ DOM order = visual reading order (avoid positive `tabindex`; use `tabindex="0"` / `"-1"` only).
✅ One **skip link** as the first focusable element:

```html
<a href="#main" class="skip-link">Skip to main content</a>
<!-- .skip-link: position:absolute; left:-9999px; visible on :focus -->
<main id="main" tabindex="-1"> … </main>
```

✅ **Focus trap** inside open modals/dialogs; **return focus** to the trigger on close. Use native `<dialog>` (`showModal()` traps + `Esc` closes for free) or Radix/React-Aria.
✅ `Esc` closes overlays; `Enter`/`Space` activate buttons; Arrow keys move within composites (menus, tabs, listbox) via **roving tabindex** (one `tabindex="0"`, rest `-1`).
❌ No keyboard trap you can't `Esc`/`Tab` out of.
❌ No focus sent to `<body>` or lost after an async update — move focus to the new region.

Cross-link: command palettes and their shortcuts live in [navigation-patterns](navigation-patterns.md); component focus states in [components](components.md).

---

## Screen readers & semantics (name · role · value)

**Native HTML first. ARIA is a patch, not a foundation.** The first rule of ARIA: don't use ARIA if a native element does the job.

| Need | Use this (native) | Not this |
|---|---|---|
| Clickable action | `<button>` | `<div onclick>` + `role="button"` + tabindex + keydown |
| Navigation link | `<a href>` | `<span>` router hack |
| Grouped form control | `<fieldset><legend>` | floating labels only |
| Page structure | `<header><nav><main><aside><footer>`, `<h1>`–`<h6>` | `<div class="header">` soup |
| Toggle | `<input type="checkbox">` / `<button aria-pressed>` | color-only "on" state |

**Every interactive element needs an accessible _name_, correct _role_, and current _value/state_:**

- Name via visible `<label for>`, wrapping label, `aria-label`, or `aria-labelledby`. Icon-only buttons **must** have `aria-label` (e.g. `aria-label="Close"`).
- One `<h1>` per page/view; headings nest without skipping levels (h2→h3, not h2→h4).
- Decorative images `alt=""`; meaningful images get descriptive `alt`; complex charts get a text/table alternative (see [dashboard-data-viz](dashboard-data-viz.md)).
- Use `aria-expanded`, `aria-selected`, `aria-checked`, `aria-current="page"`, `aria-disabled` to expose state.
- Hide purely decorative nodes with `aria-hidden="true"`; never hide focusable content that way.

### Live regions (announce async changes)

| Change type | Mechanism | Behavior |
|---|---|---|
| Status, "Saved", search-result count, non-urgent toast | `role="status"` (= `aria-live="polite"`) | Waits for a pause, doesn't interrupt |
| Errors, session timeout, critical alert | `role="alert"` (= `aria-live="assertive"` + `aria-atomic="true"`) | Interrupts immediately — use sparingly |
| Loading progress | `role="status"` + text, or `<progress>` | Announce start + end |

```html
<!-- Reserve the region in the DOM on load; inject text later -->
<div id="toast" role="status" aria-live="polite" aria-atomic="true"></div>
```

✅ Put the live region in the DOM **before** you populate it (empty on first paint), then update `textContent`.
✅ Keep live regions small — SRs read the whole changed node.
❌ Don't set both `role="alert"` and `aria-live="assertive"` (double announcement in some SRs).
❌ Don't overuse `assertive` — it hijacks the user mid-sentence. Default to **polite**.
✅ Announce error messages that say _what_ and _how to fix_ ("Password must be 8+ characters"), not just "Invalid."

---

## Touch targets & spacing

| Platform | Absolute min | **Recommended target** | Source |
|---|---|---|---|
| WCAG 2.2 (2.5.8) | **24×24 CSS px** (or 24px spacing) | — | W3C AA floor |
| iOS (HIG) | 44×44 pt | **44×44 pt** | [mobile-ios](mobile-ios.md) |
| Android (Material 3 Expressive) | 48×48 dp | **48×48 dp** | [mobile-android](mobile-android.md) |
| Desktop dense UI | 24px | 32–40px, ≥ 8px gap | [desktop-apps](desktop-apps.md) |

- The **hit area** may exceed the visual size — pad an icon button to 44/48 even if the glyph is 24. Use pseudo-element or padding, not just visual size.
- Space adjacent targets ≥ **8px** so users don't mis-tap ([layout-spacing-grid](layout-spacing-grid.md), 4pt/8pt scale).
- Primary CTAs: ≥ 48px tall on mobile.

---

## Color independence (never signal by color alone)

WCAG 1.4.1: color must not be the **only** means of conveying info, indicating an action, prompting a response, or distinguishing an element.

| ❌ Color-only | ✅ Redundant cue added |
|---|---|
| Red field border = error | Border **+ icon + text** "Enter a valid email" |
| Green/red dot for status | Dot **+ label** ("Online" / "Offline") **+ shape/icon** |
| "Click the blue text" | Underline links in body copy; don't say "the blue one" |
| Chart series by color only | Add **direct labels, patterns, or markers** (see [dashboard-data-viz](dashboard-data-viz.md)) |
| Required fields in red | Add `*` / "(required)" text + `aria-required` |

Test by rendering the screen in grayscale — every distinction must survive. Also design for the ~8% of men with color-vision deficiency: avoid red/green as the sole differentiator; prefer blue/orange or add texture.

---

## Motion sensitivity & vestibular safety

Large-scale motion (parallax, zoom, sliding panels, auto-playing carousels, spin) can trigger **dizziness, nausea, migraine** for people with vestibular disorders. WCAG 2.1: 2.3.3 (Animation from Interactions, AAA) + 2.2.2 (Pause/Stop/Hide, A).

**`prefers-reduced-motion` is a baseline requirement, not a nice-to-have.**

```css
/* Author full motion, then strip it for those who ask */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

Reduced-motion is **not** "no feedback." Replace, don't delete:

| Full motion | Reduced-motion substitute |
|---|---|
| Parallax / large translate | Static, or subtle **opacity fade** |
| Zoom/scale entrance | **Cross-fade** (opacity 0→1, 150ms) |
| Slide-in panel | Instant or short fade |
| Auto-playing carousel | Pause by default + manual controls |
| Spinner-heavy loaders | Simple fade / static indicator |

Durations & easing (full-motion budgets — see [motion-interaction](motion-interaction.md)): micro **150–200ms**, standard **200–350ms**, expressive **350–500ms**. Anything looping > 5s needs a pause control (2.2.2). No content flashes **> 3×/second** (seizure risk, 2.3.1).

---

## Forms accessibility

Forms are where a11y most often breaks. Spec:

- **Every input has a programmatic label** — `<label for="id">` or wrapping. Placeholder is **not** a label (disappears on input, low contrast).
- Group related controls: `<fieldset><legend>` for radios/checkboxes and address blocks.
- Mark required with `required` + visible "(required)" text, not color/asterisk alone.
- **Error identification (SC 3.3.1/3.3.3):** identify the field, describe the problem in text, and suggest a fix. Wire it up:

```html
<label for="email">Email (required)</label>
<input id="email" type="email" name="email"
       autocomplete="email" required
       aria-describedby="email-err" aria-invalid="true" />
<p id="email-err" role="alert">Enter an email like name@example.com.</p>
```

- Move focus to the **first errored field** (or the error summary) on submit; link summary items to fields.
- **`autocomplete` tokens (SC 1.3.5)** — use the right ones so browsers/AT can autofill:

| Field | Token |
|---|---|
| Full name | `name` (or `given-name`/`family-name`) |
| Email | `email` |
| Phone | `tel` |
| Street / city / postcode | `street-address`, `address-level2`, `postal-code` |
| Card number / exp / cvc | `cc-number`, `cc-exp`, `cc-csc` |
| Current / new password | `current-password`, `new-password` |
| One-time code (OTP) | `one-time-code` |

- **Allow paste everywhere** (WCAG 2.2 SC 3.3.8) — especially passwords and OTP. Never `onpaste="return false"`.
- Inputs get the right `type`/`inputmode` (`email`, `tel`, `numeric`, `decimal`) to summon the correct mobile keyboard.
- Don't disable the submit button until valid — it hides why. Validate on blur + submit, not on every keystroke.

Component-level input states (focus/error/disabled visuals) live in [components](components.md).

---

## Reading, cognitive load & plain language

Accessibility includes people with dyslexia, ADHD, aphasia, low literacy, and anyone tired or stressed.

- **Line length** 45–75 characters (≈ `max-width: 65ch`) for body ([typography](typography.md)).
- Line-height **1.5** body / **1.2–1.3** headings; paragraph spacing ≥ 1.5× line-height (SC 1.4.12 text spacing must not clip when users override).
- Left-align long-form text (justified text creates rivers; hurts dyslexic readers).
- **Plain language:** short sentences, active voice, common words, expand acronyms on first use. Front-load the point.
- Chunk content: headings, lists, tables; one idea per paragraph.
- Don't rely on memory across steps (SC 3.3.7); show progress in multi-step flows.
- Error/empty/loading states written as helpful sentences, not codes ([ai-native-ui](ai-native-ui.md) for AI states).
- Provide undo/confirm for destructive actions; avoid time limits, or let users extend them (SC 2.2.1).

---

## RTL & internationalization basics

~ 500M people read right-to-left (Arabic, Hebrew, Farsi, Urdu). Build for it from the start.

- Set `dir="rtl"` + correct `lang` on `<html>`. Let it cascade — don't hardcode per element.
- Use **CSS logical properties** so layout mirrors automatically:

```css
/* ❌ physical — breaks in RTL */    /* ✅ logical — mirrors */
margin-left: 16px;                     margin-inline-start: 16px;
padding-right: 8px;                    padding-inline-end: 8px;
left: 0;                               inset-inline-start: 0;
text-align: left;                      text-align: start;
border-radius: 8px 0 0 8px;            border-start-start-radius: 8px; …
```

- Mirror directional icons (back/forward, chevrons, progress) in RTL; **don't** mirror logos, media playback, or clocks.
- Allow **text expansion**: German/Finnish run +30–40% longer than English — don't fix widths to English strings; avoid text baked into images.
- Format dates, numbers, currency, and pluralization via `Intl` / ICU MessageFormat, not string concatenation.
- Support user font-size scaling to **200%** without loss of content/function (SC 1.4.4) — use `rem`, not `px`, for type.

---

## Testing (do all four — automation catches ≤ ~40%)

| Layer | Tool (2026) | Catches |
|---|---|---|
| Automated scan | **axe-core / axe DevTools**, Lighthouse, Pa11y, WAVE; `eslint-plugin-jsx-a11y` in CI; Playwright + `@axe-core/playwright` | Missing labels, contrast, roles, bad ARIA (~30–40% of issues) |
| Keyboard-only | Unplug the mouse | Focus order, traps, invisible focus, unreachable controls, missing skip link |
| Screen reader | **VoiceOver** (macOS/iOS), **NVDA** (Win, free), **TalkBack** (Android); spot-check JAWS | Name/role/value gaps, unannounced updates, reading order |
| Zoom / reflow | Browser zoom **200% & 400%**, 320px reflow (SC 1.4.10), OS text-size bump | Clipping, horizontal scroll, overlap |

Also verify: `prefers-reduced-motion` on; forced-colors / Windows High Contrast mode; grayscale check for color-only signals; both light & dark themes.

**Manual passes are mandatory** — an axe-clean page can still be unusable by keyboard or SR.

---

## Ship checklist (a11y gate — all must pass)

- [ ] **Contrast:** all text ≥ 4.5:1 (large ≥ 3:1); icons/borders/focus rings/UI states ≥ 3:1; body sanity-checked at APCA Lc ≥ 75.
- [ ] **Keyboard:** every action reachable & operable; logical Tab order; `Esc` closes overlays; no traps; focus returns to trigger.
- [ ] **Focus visible:** `:focus-visible` ring ≥ 2px, ≥ 3:1, works in light **and** dark; no naked `outline:none`.
- [ ] **WCAG 2.2:** focus never fully obscured by sticky UI; drag has a single-pointer alternative; targets ≥ 24px (44/48 recommended); paste allowed on all fields incl. OTP.
- [ ] **Semantics:** native elements first; one `<h1>`, no skipped heading levels; landmarks present; icon-buttons have `aria-label`.
- [ ] **State exposed:** `aria-expanded/selected/checked/current/invalid` set; live regions (`role="status"`/`"alert"`) announce async changes without over-using assertive.
- [ ] **Forms:** real `<label>`s; correct `autocomplete`/`type`/`inputmode`; errors identify field + fix in text + move focus; required marked in text.
- [ ] **Color independence:** no color-only status/error/link — passes grayscale test.
- [ ] **Motion:** `prefers-reduced-motion` honored (replace, don't delete); no >3 flashes/sec; auto-play has pause.
- [ ] **Reflow/zoom:** usable at 200% & 400% zoom and 320px width; `rem`-based type; no clipping at 200% text.
- [ ] **RTL/i18n:** logical properties used; `dir`/`lang` set; layout mirrors; strings tolerate +40% expansion.
- [ ] **Images/media:** meaningful `alt`; decorative `alt=""`; complex viz has text alternative; captions on video.
- [ ] **Tested 4 ways:** axe/Lighthouse clean **and** keyboard-only run **and** one screen-reader pass **and** zoom/reflow check.
- [ ] **Media/timeouts:** no unavoidable time limits (or extendable); destructive actions confirmable/undoable.

---

### Sources
- [W3C WCAG 2.2 Recommendation](https://www.w3.org/TR/WCAG22/) · [Level Access WCAG 2.2 2026 checklist](https://www.levelaccess.com/blog/wcag-2-2-aa-summary-and-checklist-for-website-owners/) · [Deque WCAG 2.2 code examples](https://dequeuniversity.com/resources/wcag-2.2/)
- [Adrian Roselli — WCAG3 Contrast as of April 2026](https://adrianroselli.com/2026/04/wcag3-contrast-as-of-april-2026.html) · [APCA in a Nutshell](https://git.apcacontrast.com/documentation/APCA_in_a_Nutshell.html)
- [Level Access — European Accessibility Act 2026 guide](https://www.levelaccess.com/compliance-overview/european-accessibility-act-eaa/)
- [MDN — prefers-reduced-motion](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion) · [MDN — ARIA live regions](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Guides/Live_regions)
