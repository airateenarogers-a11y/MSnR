# Dashboards & Data Visualization (2026)

Prescriptive rules for designing dashboards, analytics views, and charts that answer **"is everything OK?"** in under 2 seconds. Scope: information architecture, KPI tiles, chart selection, chart hygiene, data color, tables, real-time, AI-native patterns, dark mode, empty/loading/error, performance. For general grids and spacing see [layout-spacing-grid](layout-spacing-grid.md); for the color engine and tokens see [color](color.md); for motion see [motion-interaction](motion-interaction.md); for generative UI depth see [ai-native-ui](ai-native-ui.md); for contrast/CVD law see [accessibility](accessibility.md).

---

## 1. The core mental model

A dashboard is not a report. It is a **status instrument**. Rank everything by this question:

> "If the user looks for 3 seconds, do they know whether to act?"

Design in three layers of attention (progressive disclosure):

| Layer | Answers | Format | Interaction |
|---|---|---|---|
| **L0 — Glance** | Is everything OK? | 3-5 hero KPI tiles + AI summary line | none, read-only |
| **L1 — Scan** | What changed & where? | trend charts, comparison bars, anomaly badges | hover tooltips, toggle ranges |
| **L2 — Drill** | Why & what next? | tables, breakdowns, filtered sub-views | filter, sort, drill-through, expand |

✅ Lead with the answer, then let users earn the detail.
❌ Never open with a 20-column table or a 6-chart wall of equal weight.

**Working-memory cap:** humans hold ~4-7 chunks at once. Keep the L0 strip to **3-5 primary reads**; push the rest behind tabs, a "View all" link, collapsible sections, or drill-throughs.

---

## 2. Information architecture & layout skeleton

The 2026 default that scales from 5 features to 50 (Stripe / Linear / Vercel / Attio pattern):

```
┌────────────┬──────────────────────────────────────────────┐
│  Sidebar   │  Top bar: title · date range · filters · ⌘K │
│  240-280px ├──────────────────────────────────────────────┤
│  nav       │  AI summary line (1 sentence, dismissible)   │
│            ├──────────────────────────────────────────────┤
│            │  KPI STRIP  [tile][tile][tile][tile]  (4-6) │
│            ├──────────────────────────────────────────────┤
│            │  12-col grid: charts + tables (bento/spans)  │
└────────────┴──────────────────────────────────────────────┘
```

- **Sidebar:** 240-280px fixed; collapsible to a 56-64px icon rail.
- **KPI strip:** 4-6 tiles, equal width, top row. Stacks to 1-2 cols under 640px.
- **Body grid:** 12-column CSS grid, `gap: 16-24px`; charts span 4/6/8/12 cols (bento). See [layout-spacing-grid](layout-spacing-grid.md#bento).
- **Reading path:** most important → top-left. Users scan **F-shaped** (western LTR) or **Z-shaped** on sparse pages — put the north-star top-left, secondary right.
- **Date range / global filters** live top-right and apply to the whole board; they must feel instant (see §11).
- **Section grouping:** related widgets share a card or a labeled region (Law of Common Region + Proximity). Max ~2-3 distinct groups above the fold.

**Grid rhythm:** 4pt base / 8pt spacing scale. Card padding 16-24px desktop, 12-16px mobile. Card radius 8-16px; one radius token per surface.

---

## 3. KPI / stat tile anatomy

The single most-copied component on a dashboard. Get it exact.

```
┌─────────────────────────────┐
│ MRR                    ⓘ    │  ← label (metric name) + optional info
│ $48,250        ▲ 12.4%      │  ← primary value + delta chip
│ ╭─╮   ╭╮    ╱‾╲    ╱         │  ← sparkline (trend, last N periods)
│ vs. last month              │  ← comparison caption
└─────────────────────────────┘
```

### Tile spec table

| Element | Value | Notes |
|---|---|---|
| Label / metric name | 12-13px, weight 500, `oklch(L 0 0 / 0.65)` muted | top; sentence or SMALL-CAPS, never a sentence longer than 3 words |
| Primary value | 28-40px, weight 600-700, `font-variant-numeric: tabular-nums` | highest contrast text on the tile |
| Delta chip | 13-14px, weight 600, colored by **intent** | glyph `▲ / ▼ / —` + sign + value (`+12.4%` or `+3.2K`) |
| Comparison caption | 12px, muted | "vs last 30d" — always name the baseline |
| Sparkline | 60-120px × 24-32px, stroke 1.5-2px, no axes | optional end-dot; area fill 8-12% opacity |
| Status/icon | 16-20px, optional | reserve for threshold state, not decoration |
| Tile padding | 16-24px | |
| Min tile size | ~200 × 112px | below this, drop the sparkline first, then the caption |

### Delta rules

- **Compute:** `delta% = (current − prior) / |prior| × 100`, one decimal. Show sign always (`+`/`−`).
- **Color by intent, not direction.** Churn ↑ is *bad*; revenue ↑ is *good*. Map each metric to a `goodDirection` (`up`/`down`/`neutral`) and color from that. ❌ Never hard-code "up = green."
- **Never rely on color alone** (8% of men have CVD). Always pair color with the glyph (▲▼) and the signed number. See [accessibility](accessibility.md).
- **Prior = 0 or missing:** show "New" or "—", not "∞%" or "NaN%".
- Round & abbreviate values: `1,240 → 1.24K`, `3,400,000 → 3.4M`; keep decimals consistent within a metric.

### Semantic delta tokens (three-layer: primitive → semantic → component)

```css
/* semantic (theme-aware, OKLCH) */
--data-pos:   oklch(0.62 0.17 150);  /* good / positive intent */
--data-neg:   oklch(0.60 0.20 27);   /* bad / negative intent  */
--data-flat:  oklch(0.65 0.02 260);  /* no meaningful change   */
/* component */
--kpi-delta-good: var(--data-pos);
--kpi-delta-bad:  var(--data-neg);
```

✅ Do: one hero number per tile, baseline named, delta glyph + color + sign.
❌ Don't: stack 4 numbers in one tile, use a gauge for a single value, animate the number on every poll (see §9).

---

## 4. Chart selection by intent

Pick the chart from the **question**, not the data shape. Default to the simplest form that answers it.

| Intent (the question) | Best chart | Good alternates | Avoid | Rule |
|---|---|---|---|---|
| **Trend over time** | Line | Area (1 series), sparkline (inline), column (few discrete periods) | Pie, radar | ≤4-5 lines; label lines directly, not via legend |
| **Compare categories** | Horizontal bar | Vertical column (time-ordered/few), dot plot | 3D bar, pie for >3 | **Bars start at 0.** Sort by value unless order is inherent |
| **Part-of-whole (1 moment)** | Stacked bar (100%) | Treemap, donut (with center metric) | Pie >3 slices, multiple pies | Pie only for ≤3 slices summing to 100% |
| **Composition over time** | 100% stacked area | Stacked column, streamgraph | Many thin bands | ≤5-6 bands; group the tail into "Other" |
| **Distribution** | Histogram | Box plot, violin, beeswarm | Bar chart of raw values | Choose bin width deliberately; show n |
| **Relationship / correlation** | Scatter | Bubble (3rd dim = size), 2D density | Dual-axis line | Never imply causation; add trend line if useful |
| **Two categoricals + value** | Heatmap | Matrix table | Grouped bar w/ many groups | Use sequential/diverging scale (§6) |
| **Flow / movement** | Sankey | Chord, alluvial | Overloaded network | ≤8-10 nodes before it turns to spaghetti |
| **Progress to target** | Bullet chart | Progress bar, radial (single) | Speedometer gauge | Bullet > gauge: same info, ~5× the data-ink efficiency |
| **Ranking / change in rank** | Ordered bar | Bump chart, slope chart | Pie | Top-N + "Other"; don't rank 40 rows in a chart — use a table |
| **Geospatial** | Choropleth | Symbol/bubble map | 3D globe for analytics | Normalize per-capita; classify breaks intentionally |
| **Single big number** | KPI tile (§3) | Big-number card | Gauge, pie | A gauge wastes space a number + sparkline fills better |

**Pie/donut caution:** the eye compares angles poorly. Use only for a true part-of-whole with ≤3-5 slices; **never** to compare across time or between two pies. A donut is acceptable when the hole holds the total/hero number.

**Dual y-axis caution:** two different scales on one plot invite false correlation and can be manipulated. Prefer two stacked small-multiple charts sharing an x-axis.

---

## 5. Data-ink & chart hygiene

Maximize Tufte's **data-ink ratio**: most pixels should encode data. Strip everything that doesn't.

**Remove / mute:**
- ❌ 3D, drop shadows on bars, gradient fills for meaning, textures, glossy effects — pure chartjunk.
- ❌ Heavy chart borders, box frames, redundant tick marks.
- ✂️ Gridlines: keep **only the axis perpendicular to the bars** (horizontal for bar/line). Style 1px at ~8-14% contrast: `oklch(0.5 0 0 / 0.12)`. Drop gridlines entirely if data labels are present.
- ✂️ Legends: prefer **direct labeling** at the end of each line/segment. A legend forces a look-away round-trip; direct labels don't.

**Keep / add:**
- ✅ A clear baseline (x-axis). Bars & areas **must** anchor at 0; lines may use a non-zero range if labeled honestly.
- ✅ Axis titles only when units aren't obvious; units in the axis or value (`$`, `%`, `ms`).
- ✅ Reference lines for target/average/last-year (dashed, muted, labeled).
- ✅ Number formatting: thousands separators, abbreviated at scale (K/M/B), consistent decimals, right-aligned in tables (§8).
- ✅ Whitespace between plot and card edge: ≥16px so the data can breathe.

**Honesty (graphical integrity):**
- Don't truncate a **bar** y-axis (exaggerates differences).
- Keep aspect ratio stable; don't cherry-pick time windows.
- One encoding per variable; area/size scale by area, not radius.

---

## 6. Color for data

Data color is a *functional* system, separate from brand color. Prefer OKLCH; support P3; verify against WCAG 2.2 **and** CVD simulation. See the engine in [color](color.md); this section is the data-specific layer.

### Three palette families

| Family | Use for | Rule |
|---|---|---|
| **Categorical** | discrete, unordered series | max 5-7 hues; equal perceived lightness; group tail into "Other" |
| **Sequential** | ordered low→high (heatmaps, choropleth) | single hue, monotonic lightness ramp (light→dark) |
| **Diverging** | deviation from a midpoint (± vs target) | two hues, neutral center; equal steps each side |

### Colorblind-safe categorical default — **Okabe-Ito** (8 colors, CVD-tested, Nature-recommended)

```
#E69F00  orange
#56B4E9  sky blue
#009E73  bluish green
#F0E442  yellow
#0072B2  blue
#D55E00  vermillion
#CC79A7  reddish purple
#000000  black / neutral
```

Tableau 10 and D3 `category10` are acceptable modern alternates. Whatever you pick:
- ✅ Encode meaning with a **second channel** too — position, shape, direct label, or line dash — never hue alone.
- ✅ Simulate deuteranopia/protanopia/tritanopia before shipping (~8% of men, 0.5% of women affected).
- ❌ Never separate "good vs bad" by **red vs green alone.** Use blue↔orange diverging when up/down isn't semantically fixed.

### Semantic status color (thresholds)

| State | Meaning | Token |
|---|---|---|
| Green | on/above target | `--data-pos` |
| Amber | approaching limit | `oklch(0.78 0.15 80)` |
| Red | action required | `--data-neg` |

Keep categorical hues visually **distinct from** semantic status hues so a "series 3" green isn't misread as "healthy."

**Sequential/diverging in code (perceptually uniform):**
```css
/* sequential single-hue ramp */
--seq: oklch(0.96 0.03 250), oklch(0.72 0.11 250), oklch(0.45 0.15 250);
/* diverging: red ← neutral → blue (CVD-safer than red↔green) */
--div: oklch(0.58 0.19 27), oklch(0.92 0.01 250), oklch(0.55 0.15 250);
```

---

## 7. Data tables

Tables are the L2 workhorse. Density and alignment do 80% of the work.

### Alignment (non-negotiable)

| Content | Align | Why |
|---|---|---|
| Numbers, currency, % | **Right**, `tabular-nums` | decimals line up; scan-compare down a column |
| Text, names | Left | natural reading edge |
| Dates | Left (or right if compared) | consistent format `2026-07-06` or `Jul 6` |
| Status/badge | Left or center | |
| Headers | **Match their column's** alignment | header sits over its data |

```css
td.num { text-align: right; font-variant-numeric: tabular-nums; }
```

### Density (persist the user's choice)

| Mode | Row height | Use |
|---|---|---|
| Compact | 32px | power users, dense scanning |
| Comfortable | 40px | default |
| Spacious | 48px | touch, casual reading |

- Multi-line cells: **top-align** when any row exceeds ~2 lines.
- Zebra striping optional; a 1px row divider `oklch(0.5 0 0 / 0.08)` is usually cleaner.

### Behavior

- **Sticky header** on vertical scroll; sticky first column for wide tables. Test it doesn't jitter/detach.
- Sort on header click (show ▲/▼ + `aria-sort`); default sort = most useful column.
- Filter/search above the table; show active filter chips + result count.
- **Virtualize** beyond ~100 rows — render only visible rows (see §11).
- Column widths: let text columns flex, numeric columns size to content; allow user resize for pro tools.
- Row actions on hover (desktop) but keep a persistent affordance (⋯ menu) for touch/keyboard.
- Pagination vs infinite scroll: paginate for known/finite sets (predictable, linkable); infinite for feeds. Show total count either way.

---

## 8. Real-time & streaming

Match update cadence to human perception and system limits.

| Tier | Data cadence | Render throttle | Example |
|---|---|---|---|
| Live | sub-second source | **coalesce to 250ms-1s** | trading, ops NOC |
| Near-real-time | 5-15s | on arrival | active users, queue depth |
| Periodic | 30s-5min | on arrival | daily KPIs, billing |

Rules:
- **Never re-render a number faster than ~250ms (4fps).** Humans can't read faster; faster flicker is noise. Batch/coalesce upstream — if a source emits many times/sec, aggregate to a value per 1-10s (this also avoids streaming-tile payload limits in BI backends).
- Animate value changes with a short interpolation (150-250ms), but **snap instantly** under `prefers-reduced-motion`. See [motion-interaction](motion-interaction.md).
- **Never reflow layout** on update — reserve tile/chart dimensions so incoming data doesn't shift the page (CLS = 0). Preserve scroll position, table selection, and open tooltips across refresh.
- Streaming time-series: use a **fixed rolling window**; roll old points off the left edge; downsample so you never draw >1-2 points per pixel (LTTB).
- Show a **live indicator** (pulsing dot) + "Updated 3s ago" timestamp. If the connection drops, freeze data, dim the indicator, and show "Reconnecting…" — don't blank the board.
- Rate-limit user-driven refresh; debounce filter changes 150-300ms before refetch.

---

## 9. AI-native dashboards (2026)

The 2026 shift (Attio, Hex, Cursor, Querio, Domo): the dashboard **summarizes, prioritizes, and recommends** instead of leaving the user to assemble charts. Add these on top of a solid classic board — never as a replacement for real numbers.

**Patterns:**
- **Summary-first insight line** — one LLM-generated sentence at the top: *"Revenue +12% WoW, driven by EMEA; churn flat; 2 anomalies flagged."* Dismissible, regenerates on filter change.
- **Anomaly callouts** — auto-detect outliers/spikes and mark them: annotation pin on the chart, badge on the tile ("⚠ 3σ above trend"), and a ranked "Needs attention" list. Explain *why* it's flagged (threshold, seasonality-adjusted, forecast band).
- **Natural-language query (NLQ)** — replace rigid dropdown filters with a conversational bar ("show EMEA signups by week vs last quarter"). It generates the chart/table on the fly (generative UI — see [ai-native-ui](ai-native-ui.md)).
- **Prioritization** — rank tiles/cards by *what changed most* / *what needs action*, not fixed order.
- **Recommend next step** — "3 accounts at churn risk → view list", drill suggestions.

**Trust rules (mandatory):**
- ✅ **Ground every number in a real aggregate.** The LLM narrates computed results; it must never invent a figure.
- ✅ **Make it inspectable** — "Show the query" reveals the generated SQL/spec so users can verify. This is the 2026 differentiator (Hex, Querio).
- ✅ Cite the data source + freshness timestamp on AI output.
- ✅ Show confidence / uncertainty for forecasts (prediction bands, not a false-precision single line).
- ❌ Don't hide that content is AI-generated; don't auto-act on anomalies without a human affordance.

---

## 10. Dark mode for dashboards

Dashboards ship dark-first in many ops/analytics contexts. Don't just invert — retune the data layer. Full system in [color](color.md); data specifics here:

- **Surfaces:** near-black, never pure `#000`. Base `oklch(0.16 0.01 260)`; elevated cards a step lighter `oklch(0.19 0.01 260)`. Elevation = lighter, not shadow.
- **Text:** never pure white for body; ~90% lightness `oklch(0.92 0 0)`; muted labels ~60-65%.
- **Chart lines/marks:** raise lightness and reduce chroma slightly vs light mode so hues don't glow/vibrate on dark. Provide a **separate dark data palette**, not the same hex.
- **Gridlines:** even lower contrast — `oklch(1 0 0 / 0.08)`.
- **Semantic green/red:** bump lightness & chroma so they read on dark; verify contrast against the dark surface (APCA Lc ≥ 45 for chart marks, ≥ 60 for text).
- Both themes must satisfy contrast — stamp `data-theme` and test each.

---

## 11. Empty, loading & error states

Every widget needs all three. Design them, don't leave defaults.

**Loading:**
- Show a **skeleton within 100ms** that matches final layout dimensions (prevents layout shift). Tile skeleton = grey block sized to the number; chart skeleton = faint axis frame; table = shimmer rows.
- Load **per-widget independently** — the KPI strip should render while a heavy chart still fetches.
- Shimmer/pulse ≤1 cycle/1.5s; respect `prefers-reduced-motion` (static skeleton).

**Empty (distinguish the cause):**
| Case | Message | Action |
|---|---|---|
| First run / no data yet | "No data yet" | primary CTA to connect source / create |
| Filter matches nothing | "No results for these filters" | "Clear filters" button |
| Metric genuinely zero | show `0` in the tile | not an empty state — 0 is data |

**Error (contain the blast radius):**
- Wrap each widget in its own **error boundary** — one failed chart must not kill the dashboard.
- On refresh failure, show **last good data** dimmed with a "Couldn't update — retry" banner, not a blank card.
- Give a retry affordance and a plain-language cause. Never show a raw stack trace.

---

## 12. Performance budget

Targets for a dashboard to feel like an instrument, not a report:

| Metric | Budget |
|---|---|
| Skeleton visible | < 100ms |
| First KPI strip meaningful | < 1s |
| Fully interactive (TTI) | < 2s |
| LCP | < 2.5s |
| Cumulative layout shift (CLS) | ~0 (reserve all widget sizes) |
| Filter → updated view | < 300ms perceived (optimistic + debounce) |

Techniques:
- **Aggregate server-side.** Never ship 100k rows to compute a sum in the browser.
- **Virtualize** long tables/lists (render visible rows only).
- **Downsample** time series (LTTB) to ~1-2 points per pixel.
- **Lazy-load below-the-fold** charts with `IntersectionObserver`.
- **Debounce** filter input 150-300ms; **stale-while-revalidate** cache so the board shows instantly then refreshes.
- Code-split heavy chart libs; don't block the KPI strip on the charting bundle.

---

## Ship checklist

- [ ] **L0 answers "is everything OK?"** in ≤3s — 3-5 hero KPI tiles + one AI/summary line at top.
- [ ] Progressive disclosure: secondary detail is behind tabs / drilldowns / "View all", not all on screen at once.
- [ ] Every KPI tile: named baseline, delta with **glyph + sign + color-by-intent** (not color alone), tabular-nums value.
- [ ] Chart type chosen from the **question** (§4); bars/areas start at 0; no pie with >3 slices; no 3D/chartjunk.
- [ ] Direct labels over legends where feasible; gridlines ≤14% contrast or removed; units present.
- [ ] Data palette is **colorblind-safe** (Okabe-Ito or equivalent), meaning double-encoded (shape/position/label), CVD-simulated.
- [ ] Tables: numbers right-aligned + tabular-nums, sticky header, sortable with `aria-sort`, density persists, virtualized >100 rows.
- [ ] Real-time: renders throttled (≥250ms), no layout reflow on update, live indicator + "updated Xs ago", reduced-motion snaps.
- [ ] AI output is **grounded in real aggregates**, inspectable ("show query"), source-cited, labeled as AI.
- [ ] Dark mode uses a separate retuned data palette; surfaces near-black not `#000`; contrast verified (WCAG 2.2 + APCA).
- [ ] Empty/loading/error designed per widget: skeleton <100ms, per-widget error boundary, empty distinguishes first-run vs filtered-out.
- [ ] Performance: skeleton <100ms, interactive <2s, LCP <2.5s, CLS ~0; server-side aggregation + downsampling in place.
- [ ] Responsive: KPI strip stacks, tables scroll inside their own container (page body never scrolls horizontally).
- [ ] `prefers-reduced-motion` honored on every animated number, transition, and skeleton.
