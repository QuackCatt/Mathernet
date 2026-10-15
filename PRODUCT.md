# Product

## Platform

web

## Stack

Delegated: HTML, CSS, and JavaScript served by the existing local Python JSON API, with locally vendored KaTeX for formula rendering.

## Users

University mathematics learners who want to understand formulas as connected ideas rather than isolated memorization tasks.

## Jobs

- Open an existing formula or learn a new one through one unified search.
- Organize formulas into independently named, pinnable, and deletable mind-map sessions.
- See which formulas support or depend on the selected formula.
- Read AI-generated formula explanations without confusing generated content with personal understanding.
- Continue formula exploration in a preserved deep-dive conversation generated on first use.
- Record a private study note and learning status.
- Inspect every source and edit or explicitly confirm AI-suggested dependency edges.
- Resolve a formula through the configured AI provider, reuse an exact local match, and create a card only when none exists.
- Optionally provide source material through a configured MCP tool.

## Product Truth

- Mathernet is a local, AI-assisted formula knowledge-graph learning assistant.
- Formula cards contain separate AI and user modules.
- AI citations are stored only when the provider returns real source URLs; Mathernet never fabricates citations.
- Deep dives are continuous articles with optional passages and optional references; missing topics or sources are omitted rather than filled with placeholders.
- Dependency edges must cite stored sources. An answer without citations cannot create dependency edges.
- AI-suggested dependency edges require explicit user confirmation before they are accepted.
- Study status records activity and must not be presented as proof of mastery.
- The product refuses assessed-work answers, unrelated requests, and fabricated citations or derivations.
- Saved cards remain usable offline; uncited AI answers are visibly qualified and do not claim source support.
- The CLI and Web interface must use the same repository, rules, safety behavior, and persistence model.

## Operating Context

- Local-first desktop and laptop use with a desktop working layout.
- Typical workflow: search or describe a formula, open or create one card, inspect its map, review sources, edit notes, and resolve suggested dependencies.
- The first Web surface is the working application, not a marketing page.
- Formula expressions are rendered from stored LaTeX with KaTeX; ASCII display values are compatibility fallbacks only.
- The dependency graph is an interactive force-directed canvas with dragging, panning, zooming, neighbour highlighting, and keyboard-selectable nodes.
- Each mind-map session renders its complete formula set and the dependency edges whose endpoints both belong to that session.

## Accessibility

- Keyboard operation is required for navigation, graph nodes, tabs, forms, and edge decisions.
- Status and verification are communicated with text and icons, not color alone.
- Body text must meet WCAG AA contrast.
- Reduced motion and browser zoom must remain supported.

## Terminology

- Formula card: AI-generated explanation of one formula, with real citations when the provider supplies them.
- AI Module: generated summary, explanation, examples, and derivation steps.
- Simple introduction: a generated 100-150 word definition explaining what a formula means, how it is used, and why it matters.
- User Module: learner-owned notes and study status.
- Deep-dive session: one generated opening article plus its preserved follow-up conversation for one formula.
- Mind-map session: a named formula workspace with its own graph composition and navigation history.
- Dependency edge: a directed, source-backed relation between formulas.
- Accepted edge: a dependency confirmed or edited by the learner.

## Constraints

- No network dependency is required for local browsing or saved-card interactions.
- No exam or homework answers are produced.
- No interface action may silently accept an AI-suggested dependency.
- Personal notes and local graph data remain outside version control.
- Deleting a formula card is global: it removes the card and its incident relationships from every mind-map session while retaining shared source records.
