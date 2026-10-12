# Mathernet Design System

## Direction

Mathernet is a calm scientific editing table for inspecting mathematical relationships. The interface feels precise and trustworthy without becoming a generic dashboard. Its signature move is the central dependency constellation: formulas sit in a live, inspectable graph while the surrounding workspace preserves source provenance and learner ownership.

## Tokens

### Color

- `canvas`: `#F3F6F2` — cool mineral workspace background.
- `surface`: `#FFFFFF` — reading and editing surfaces.
- `surface-soft`: `#E8EEEA` — selected rows and quiet controls.
- `ink`: `#17231F` — primary text.
- `muted`: `#52625B` — secondary text.
- `line`: `#C8D2CC` — structure and separators.
- `signal`: `#2859D9` — selection, primary actions, and graph focus.
- `signal-soft`: `#DFE7FF` — selected control backgrounds.
- `verified`: `#167458` — learner-confirmed state.
- `pending`: `#9A5A00` — AI-suggested state.
- `danger`: `#B63E35` — rejection and recoverable errors.
- `annotation`: `#D55A43` — user-owned content marker.

Dark mode uses `#111714`, `#18211D`, `#223029`, `#EEF5F1`, `#B9C7C0`, `#3D4D45`, `#82A2FF`, `#253765`, `#67C49E`, `#E2AE5D`, `#FF8D80`.

### Type

- Display and formulas: `Source Serif 4`, `Iowan Old Style`, `Georgia`, serif.
- Interface: `Atkinson Hyperlegible`, `Avenir Next`, `Segoe UI`, sans-serif.
- Body: 16px minimum, 1.55 line height.
- Headings use balanced wrapping; body text uses pretty wrapping.
- Dynamic counts and timestamps use tabular numerals.

### Space and Shape

- Spacing scale: 4, 8, 12, 16, 24, 32, 48px.
- Control height: 44px minimum.
- Radius: 6px controls, 10px dialogs, 12px formula nodes.
- Structural panels use borders and tonal separation, not floating cards.
- Shadows communicate temporary elevation only.

### Motion

- Interactive transitions use transform, opacity, color, border-color, and background-color.
- Buttons press to `scale(0.96)`.
- Graph selection animates node emphasis and edge opacity once.
- Loading uses stable progress text and `aria-busy`.
- All nonessential movement is disabled under `prefers-reduced-motion`.

## Layout

Desktop uses a three-column workbench: library on the left, dependency constellation in the center, and source-backed inspector on the right. Mobile changes to three task tabs: Library, Graph, and Details. The interface is left aligned and content is dense enough for repeated study work without becoming a cockpit.

## Components

- Formula library rows are unframed buttons with formula name, topic, source count, and textual status.
- The graph uses authored SVG nodes and edges with keyboard-selectable nodes.
- Formula inspector tabs separate Overview, Sources, and Learning.
- AI content and learner content are visually and semantically distinct.
- Pending edges show their direction, rationale, sources, and explicit Confirm or Reject actions.
- Forms expose visible labels, inline errors, loading feedback, and stable success messages.
- Empty states explain the next useful action.

## Principles

- Source provenance is visible before persuasion.
- The graph is functional evidence, not decoration.
- Generated content never impersonates learner knowledge.
- Every action names its result.
- Controls use familiar Web patterns and consistent iconography.
- One memorable visual move, the dependency constellation, carries the identity.
