---
name: EasyPaper Quiet Precision
colors:
  canvas: "#F5F5F2"
  surface: "#FFFFFF"
  surface_subtle: "#FAFAFA"
  ink: "#1D1D1F"
  muted: "#6E6E73"
  line: "#D8D8DC"
  accent: "#9F3027"
  accent_soft: "#F8EFED"
---

# Design System: EasyPaper Quiet Precision

## 1. Visual Theme & Atmosphere

EasyPaper should feel like a carefully made Apple tool for serious reading: quiet, exact, and immediately understandable. The visual field is mostly neutral white and soft gray. A single restrained ink-red accent marks attention, progress, and the one place where the product wants the user to act. There is no decorative noise, no dashboard theater, and no surface added without a reason.

The interface has an “art gallery airy” density on landing and library screens, then becomes instrument-like inside the reader. Hierarchy comes from typography, alignment, whitespace, and tiny changes in contrast. The product should feel considered before it feels branded.

Design posture: creativity 7, variance 4, motion 3, density 4. Make the unusual detail small and discoverable: a hairline active mark, a precise empty state, an exact hover response, a short transition, or a source quote aligned like a margin note.

## 2. Color Palette & Roles

- **Canvas Gray** `#F5F5F2` — the outer workspace; quiet enough to frame content.
- **Surface White** `#FFFFFF` — lists, forms, dialogs, and focused content.
- **Surface Subtle** `#FAFAFA` — hover states, source quotes, and secondary regions.
- **Off-Black Ink** `#1D1D1F` — primary text and primary buttons; never use pure black.
- **Muted Graphite** `#6E6E73` — descriptions, metadata, and quiet controls.
- **Structural Hairline** `#D8D8DC` — borders and separators; use one-pixel lines.
- **Ink Red** `#9F3027` — the only accent, reserved for active marks, focus, progress, and important links.
- **Ink Red Wash** `#F8EFED` — selected text, subtle emphasis, and non-destructive feedback.

Do not add purple, blue neon, multi-color gradients, glassmorphism, or glowing shadows. Keep the palette stable across all pages and use functional green/amber/red only for state messaging.

## 3. Typography Rules

Use the system Chinese sans stack for reliable native glyphs: `-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `PingFang SC`, `Microsoft YaHei`, sans-serif. Use the custom EasyPaper Headline only for the auth brand statement. Software UI pages should not use generic serif fonts.

- Page titles: 27–32px, 680 weight, tracking `-0.04em`, line-height 1.2.
- Section titles: 15–19px, 650–680 weight.
- Body copy: 14–15px, line-height 1.65–1.75, max 65ch.
- Metadata: 12–13px, muted graphite, tabular numerals.
- Labels: 10–11px, 700 weight, letter-spacing around `0.12em`.

Hierarchy must come from weight, spacing, and contrast before increasing font size. Avoid all-caps labels except for small overlines. Never use giant marketing headlines inside the product workspace.

## 4. Component Stylings

### Buttons

Primary actions are off-black ink with white text. Secondary actions use a white surface and hairline border. Ghost actions are invisible until hover. Controls use an 8px radius and a 40px height; coarse pointers receive 44px. Active feedback is a one-pixel tactile translate and a slight color change, never a glow.

### Cards and Lists

Use cards only when they establish a meaningful boundary. Cards use a 12px radius, one-pixel border, and no visible shadow. Dense lists use one outer frame and horizontal dividers instead of many floating cards. The continue-reading item has a 2–3px red leading rule; it does not use a gradient or decorative illustration.

### Navigation

The desktop rail is white, 228px wide, and divided into 工作区 and 学习 by generous whitespace. The active route is a neutral gray row with a two-pixel red leading mark. The account row is separated by one hairline. Mobile navigation becomes a compact touch strip without changing order or adding a hamburger interaction.

### Inputs and Forms

Inputs use a 40–44px height, white surface, 8px radius, and a quiet graphite border. Focus adds a thin red border and a translucent red halo. Labels remain above fields. Errors appear close to their field; helper copy is short and muted.

### Loading and Empty States

Use layout-aware quiet states. Avoid a generic spinner as the only content when the shape of the result is known; use text and a simple structural placeholder where possible. Empty states should explain the next useful action without inventing metrics or illustrations.

## 5. Layout Principles

- Desktop shell: 228px navigation rail plus a flexible content column capped at 1320px.
- Workspace padding: 50px top, 24–76px horizontal, 84px bottom.
- Major section gap: 40px; control rhythm: 4px and 8px.
- Align titles, descriptions, metadata, and actions to a predictable left edge.
- One primary action per page heading; secondary actions sit beside it or in a menu.
- Do not use equal three-card feature rows, nested cards, or percentage-based layout hacks.
- The reader keeps its full-height, tool-like layout and may be denser than the workspace.

## 6. Responsive Rules

At 1100px reduce rail and content margins. At 700px the rail becomes a compact navigation strip, page actions become full width, lists stack, and the reader panel overlays the document. At 380px navigation uses two columns to keep labels readable. No horizontal overflow is allowed; every tap target is at least 44px on coarse pointers.

## 7. Motion and Performance

Motion is restrained: 120–180ms ease-out transitions for color, opacity, and transform only. No perpetual decorative animation. Loading motion should communicate active work, respect `prefers-reduced-motion`, and never delay usable content. Keep animation off layout properties such as width, height, top, and left.

## 8. Anti-Patterns

- No pure black, purple/neon accents, gradients, glow shadows, glassmorphism, or fake depth.
- No generic serif fonts in software screens, no Inter, no emoji decoration.
- No oversized marketing copy inside the workspace.
- No three equal cards, nested card stacks, or repeated “pill everywhere” treatment.
- No invented statistics, fake performance metrics, filler labels, or AI copywriting clichés.
- No feature changes hidden inside visual redesigns; keep business actions and routes stable.
