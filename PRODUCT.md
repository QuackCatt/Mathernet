# Product

## Platform

web

## Stack

Delegated: HTML, CSS, and JavaScript served by the existing local Python JSON API, with locally vendored KaTeX for formula rendering.

## Users

University mathematics learners who want to understand formulas as connected ideas rather than isolated memorization tasks.

## Jobs

- Find a formula or closely related name in a persistent local library.
- See which formulas support or depend on the selected formula.
- Read source-backed AI explanations without confusing generated content with personal understanding.
- Record a private study note and learning status.
- Inspect every source and edit or explicitly confirm AI-suggested dependency edges.
- Learn a new formula through configured MCP Web Search when a reliable source is available.

## Product Truth

- Mathernet is a local, source-backed formula knowledge-graph learning assistant.
- Formula cards contain separate AI and user modules.
- Every formula and dependency edge must cite stored sources.
- AI-suggested dependency edges require explicit user confirmation before they are accepted.
- Study status records activity and must not be presented as proof of mastery.
- The product refuses assessed-work answers, unrelated requests, unsupported formulas, and fabricated derivations.
- Saved cards remain usable offline; online learning falls back to cached approved search results when retrieval is unavailable.
- The CLI and Web interface must use the same repository, rules, safety behavior, and persistence model.

## Operating Context

- Local-first desktop and laptop use with a desktop working layout.
- Typical workflow: search the library, inspect a formula graph, review sources, edit notes, and resolve suggested dependencies.
- The first Web surface is the working application, not a marketing page.
- Formula expressions are rendered from stored LaTeX with KaTeX; ASCII display values are compatibility fallbacks only.
- The dependency graph is an interactive force-directed canvas with dragging, panning, zooming, neighbour highlighting, and keyboard-selectable nodes.

## Accessibility

- Keyboard operation is required for navigation, graph nodes, tabs, forms, and edge decisions.
- Status and verification are communicated with text and icons, not color alone.
- Body text must meet WCAG AA contrast.
- Reduced motion and browser zoom must remain supported.

## Terminology

- Formula card: source-backed explanation of one formula.
- AI Module: generated summary, explanation, examples, and derivation steps.
- User Module: learner-owned notes and study status.
- Dependency edge: a directed, source-backed relation between formulas.
- Accepted edge: a dependency confirmed or edited by the learner.

## Constraints

- No network dependency is required for local browsing or saved-card interactions.
- No exam or homework answers are produced.
- No interface action may silently accept an AI-suggested dependency.
- Personal notes and local graph data remain outside version control.
