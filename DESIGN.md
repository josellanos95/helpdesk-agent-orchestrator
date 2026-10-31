---
name: Triagent
description: The Audit Listing. A greenbar line-printer audit listing where every agent step is a ruled line and nothing is deleted, only stamped.
colors:
  paper: "#fbfcf7"
  band: "#e4f0da"
  rule: "#c9ddbb"
  ink: "#161b26"
  ink-2: "#3f4756"
  ink-3: "#5b6472"
  ribbon-blue: "#1f4aa8"
  on-blue: "#ffffff"
  ribbon-red: "#b3261e"
  amber-waiting: "#7a4f00"
typography:
  page-title:
    fontFamily: "Public Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  entry-title:
    fontFamily: "Public Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 750
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  section-title:
    fontFamily: "Public Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 650
    lineHeight: 1.25
  body:
    fontFamily: "Public Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  line-text:
    fontFamily: "Public Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
  secondary:
    fontFamily: "Public Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  column-head:
    fontFamily: "Public Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.06em"
  actor:
    fontFamily: "Public Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    letterSpacing: "0.04em"
  mono-data:
    fontFamily: "JetBrains Mono Variable, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    letterSpacing: "0.01em"
  stamp:
    fontFamily: "JetBrains Mono Variable, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "0.75rem"
    fontWeight: 700
    lineHeight: 1.35
    letterSpacing: "0.06em"
rounded:
  hairline: "2px"
  control: "3px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  topbar: "52px"
  tabbar: "60px"
components:
  button:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "44px"
  button-primary:
    backgroundColor: "{colors.ribbon-blue}"
    textColor: "{colors.on-blue}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "44px"
  button-hover:
    backgroundColor: "{colors.band}"
  button-danger:
    textColor: "{colors.ribbon-red}"
    rounded: "{rounded.control}"
  field:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
    height: "44px"
  stamp-approved:
    textColor: "{colors.ribbon-blue}"
    typography: "{typography.stamp}"
    rounded: "{rounded.hairline}"
    padding: "0 6px"
  stamp-void:
    textColor: "{colors.ribbon-red}"
    typography: "{typography.stamp}"
    rounded: "{rounded.hairline}"
    padding: "0 6px"
  stamp-awaiting:
    textColor: "{colors.amber-waiting}"
    typography: "{typography.stamp}"
    rounded: "{rounded.hairline}"
    padding: "0 6px"
  stamp-signature:
    textColor: "{colors.ribbon-blue}"
    typography: "{typography.stamp}"
    rounded: "{rounded.hairline}"
    padding: "1px 8px"
  listing-row:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    padding: "10px 16px"
  listing-row-banded:
    backgroundColor: "{colors.band}"
    textColor: "{colors.ink}"
    padding: "10px 16px"
  notice:
    backgroundColor: "{colors.band}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
---

# Design System: Triagent

## Overview

**Creative North Star: "The Audit Listing"**

The agent's work is printed, not chatted. Every step of a run is a ruled line on banded greenbar fanfold paper, and nothing is ever deleted: a rejected, expired or failed line stays in place, struck through and rubber-stamped. Human decisions are signed in ribbon blue; voids and failures in ribbon red; amber appears only for what is still waiting. The dark theme is the same listing on a phosphor terminal: near-black green paper, pale phosphor ink.

The density is that of a form, not a dashboard: one column of lines, hairline-ruled columns on wide screens, generous 44px touch targets on controls. Prose is read in a plain workhorse sans; monospace is rationed to the things a machine stamps onto the paper (time, actor-adjacent data, milliseconds, cost, stamps). The system is flat. Depth is made by rules and bands, never by shadow.

It refuses the sidebar-plus-bubbles helpdesk template and the generic admin look.

**Key Characteristics:**
- Greenbar banding (every other line) with a heavy ink rule at the top and a hairline green rule under each line.
- Stamps as the only state vocabulary: outlined mono chips, always carrying a word, never colour alone.
- Live print-head row: blinking block cursor plus a duration bar that grows to scale.
- Sans for everything read; mono only for time, milliseconds, cost, stamps.
- Light and phosphor-dark themes from one token set; system preference by default, explicit override via `data-theme`.

## Colors

Pale green paper and ruled lines with one ink, one human blue, one failure red and one waiting amber.

### Primary
- **Ribbon Blue** (#1f4aa8): the human hand. Primary button fill, signed and approved stamps, the user actor label, the live cursor and live duration bar, focus outline, selection tint, current-tab marker.

### Secondary
- **Ribbon Red** (#b3261e): void, rejected and failed stamps, the strike-through on voided lines, the danger button, error notice border and icon.

### Tertiary
- **Waiting Amber** (#7a4f00): awaiting stamps and the pending-count badge on tabs. Nothing else.

### Neutral
- **Listing Paper** (#fbfcf7): page, bars, fields, sheets.
- **Green Band** (#e4f0da): every other listing line, hover wash, current tab, notices, code blocks.
- **Hairline Green** (#c9ddbb): row dividers, column rules, scrollbars, pressed-button fill.
- **Printer Ink** (#161b26): body text, heavy top rule of every list, selected segment fill, composer and tab-bar top rule.
- **Ink Soft** (#3f4756): secondary text, sub-lines, model and tool lines.
- **Ink Quiet** (#5b6472): times, meta, column heads, placeholders, totals.

### Phosphor theme (same roles, dark values)
Paper #0e1511, band #16271d, rule #2e4636, ink #d9e8da, ink-2 #b4c6b6, ink-3 #8fa392, blue #8fb0ff (text on it #0b1220), red #ff8a80, amber #f2c14e, scrim rgb(0 0 0 / 0.65). Amber and red lighten, blue becomes a periwinkle, so each stamp keeps contrast on the dark paper.

### Named Rules
**The Ribbon Rule.** Blue means a human did it or is acting; red means void or failed; amber means still waiting. A colour never carries a state alone; the stamp word is always present.
**The Green Is Paper Rule.** Green belongs to the paper (band, rule, scrim ink), never to a status. There is no success green.

## Typography

**Display / Body Font:** Public Sans Variable (with ui-sans-serif, system-ui, sans-serif)
**Label/Mono Font:** JetBrains Mono Variable (with ui-monospace, SFMono-Regular, Menlo, monospace)

**Character:** A plain, legible workhorse sans carries every sentence; the mono is the printer's own type, used sparingly so it reads as machine record.

### Hierarchy
- **Entry title** (750, 1.75rem, 1.15, -0.02em): entry screen heading only.
- **Page title** (700, 1.375rem, 1.25): page headings; empty-chat title.
- **Section title** (650, 1.125rem): section breaks inside pages; company names.
- **Body / line text** (400, 1rem, 1.5 and 1.55): the printed message text. Model and tool lines drop to 0.9375rem in Ink Soft.
- **Secondary** (400, 0.875rem; meta 0.8125rem): sub-lines, item meta, labels (600).
- **Column head** (600, 0.6875rem, 0.06em, uppercase, Ink Quiet): the listing's column-head row, wide screens only.
- **Actor** (600, uppercase, 0.04em, sans): the actor column of each line.
- **Mono data** (400, 0.75rem, tabular numerals): time, ms, cost, token counts; inspector data blocks.
- **Stamp** (700, 0.75rem mono, 0.06em, uppercase): rubber-stamp states.

### Named Rules
**The Mono Ration Rule.** Monospace is for time, milliseconds, cost and stamps. Anything a person reads as a sentence is sans.
**The Tabular Rule.** Every number that lines up in a column uses tabular numerals.

## Layout

A single column of lines is the unit. Pages are capped at 58rem and centred; the chat listing runs full width. Mobile (under 800px): one column, a fixed three-tab bottom bar (3.75rem) with the composer docked above it, a sticky 3.25rem top bar. From 800px the top bar carries the tabs and the bottom bar disappears. From 1100px a 15rem conversation list joins at the left; from 1360px a 21rem run-inspector column joins at the right. Run detail is a bottom sheet on phones and a 26rem popover sheet on desktop.

Each line is a container-query grid. Narrow (under 40rem container): time, actor and meta on one row, content beneath. Wide: four hairline-ruled columns (time 4.5rem, actor 11rem, content flexible, meta 11rem) under a column-head row. Spacing steps in use: 4, 8, 12, 16, 24px; rows pad 10px/16px; controls are 44px tall (36px small).

### Named Rules
**The Ruled Column Rule.** Wide listings separate columns with 1px hairline rules, not gaps or cards.

## Elevation & Depth

Flat. Depth comes from rules and bands: a 1px Printer Ink rule opens every list and closes every fixed bar; 1px green hairlines divide lines; banding separates alternate lines. The only shadow in the build is the desktop popover sheet (`0 8px 24px rgb(0 0 0 / 0.18)`) which lifts it off the listing; mobile sheets use a 2px ink top rule and a scrim instead. Selection is an inset 1.5px ink outline, not a lift.

### Named Rules
**The Flat Paper Rule.** Nothing floats except the single desktop popover sheet. Cards, glows and stacked shadows do not exist here.

## Shapes

Square paper with the corners barely taken off: 2px for stamps, code blocks, bars and focus rings; 3px for buttons, fields, segmented controls, notices and sheets. No pills, no circles. Borders are 1px (1.5px for stamps, 2px for the current-tab marker and mobile sheet rule). Stamps lean at -1.5deg; plain status tags sit flat.

## Components

### Buttons
- **Shape:** squared (3px), 44px tall, 16px side padding, 600 weight, 0.9375rem.
- **Default:** transparent with a 1px Ink Quiet border; hover fills Green Band and darkens the border to ink.
- **Primary:** Ribbon Blue fill, white label. Disabled keeps a readable label: the fill is dimmed to 30% blue on paper while the text stays ink, never faded text.
- **Danger:** ribbon-red label and border; hover washes 12% red.
- **Quiet / icon / small:** transparent border; 44px square icon button; 36px small. Icons are Lucide SVGs, 16-22px.
- **Transitions:** background and border, 120ms ease-out.

### Fields
- 44px min height, paper fill, 1px Ink Quiet border, 3px radius. Focus: 2px blue outline with no offset and a blue border. The caret is blue.

### Segmented switch
- One bordered 3px group, buttons divided by 1px rules. Selected segment inverts to ink fill with paper text, weight 650. Used for persona and language.

### Stamps
Outlined mono chips: 1.5px currentColor border, 2px radius, uppercase 0.75rem 700, tilted -1.5deg. Colour by meaning: approved blue, rejected/void/failed red, awaiting amber. A plain variant (ink-soft, untilted) labels neutral ticket and escalation states. The signature variant, used on the human signing line and approval lines, is 0.875rem with a second 1px outline offset 2px, producing a doubled rule. When a signature line prints, its stamp is struck down once (scale 1.6 to 1, 160ms, 120ms delay).

### Listing (signature)
Banded ruled lines: odd/even banding, heavy ink top rule, hairline bottoms, column-head row on wide screens. Time is mono in Ink Quiet; actor is uppercase sans, blue for the user and human signer; meta right-aligns ms and cost in mono with a duration bar (3.5rem on narrow, full column width on wide, 4px high, scaled to the step's share of the run). Inspectable lines show a chevron cue and an inset-ink outline when pressed. Total lines are quieter (Ink Quiet, tighter padding). Struck lines carry a red 1px line-through in Ink Quiet text.

### Live print-head row
The in-progress step prints a 0.5em-wide blue block cursor blinking at 1s steps, and a blue duration bar whose scaleX tracks progress (220ms linear). A new line arrives by line-feed reveal: 180ms, ease-out-expo, translating up 0.5rem while a clip-path opens. Reduced motion collapses all animation to instant.

### Navigation
Mobile: fixed bottom tab bar of icon over 0.75rem label; current tab gets Green Band fill, a 2px blue top marker and weight 700. Desktop: top-bar tabs, 0.9375rem, current tab has a 2px ink underline and weight 650; hover fills the band. Pending counts appear as a small amber outlined mono badge.

### Sheet and notice
Sheets are native dialogs rising 220ms with a scrim. Notices are band-filled 3px boxes with a 1px hairline; the error variant swaps the border to ribbon red.

## Do's and Don'ts

### Do:
- **Do** print every state as a line and mark it with a stamp that carries its word.
- **Do** keep banding, the heavy ink top rule and hairline dividers on any new list.
- **Do** use Ribbon Blue only for human action and focus, red for void/failed, amber for waiting.
- **Do** keep mono to time, ms, cost, tokens and stamps.
- **Do** keep controls at 44px and corners at 2-3px.
- **Do** animate only as printing: line-feed reveal 180ms, stamp-down 160ms, cursor blink, bar growth; honour reduced motion.

### Don't:
- **Don't** add cards, rounded pills, gradients or glow shadows; the world is flat paper.
- **Don't** add a success green or use colour alone to signal state.
- **Don't** delete a rejected or failed line; strike and stamp it.
- **Don't** set sentences in mono.
- **Don't** reintroduce the sidebar-plus-bubbles chat pattern.

## Defects and drift not canonized
- Monospace also appears in the tab badge, inspector data blocks and inline code, which stretches the Mono Ration Rule; recorded as drift, not as precedent.
- The Public Sans / Tailwind utility classes in `ChatPage.tsx` (empty-state title) bypass the `.page-title` class; one-off.
- The dark token block is declared twice in `index.css` (explicit `data-theme` and `prefers-color-scheme`); a maintenance duplicate, not a design decision.
- The uppercase actor column and column-head row are functional listing labels, not kickers or eyebrows; no eyebrow style exists and none is recorded.
