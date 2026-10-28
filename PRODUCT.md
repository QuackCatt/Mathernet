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
- Inspect the sources the model returns and cut any dependency edge that is wrong.
- Resolve a formula through the configured AI provider, reuse an exact local match, and create a card only when none exists.

## Product Truth

- Mathernet is a local, AI-assisted formula knowledge-graph learning assistant.
- Formula cards separate model-generated context from learner-owned notes and status.
- Sources returned by the model are stored as model output. Mathernet does not add citations of its own and does not independently verify model-supplied URLs.
- Deep dives are continuous articles with optional passages and optional references; missing topics or sources are omitted rather than filled with placeholders.
- Dependency edges are displayed with their rationale and any model-supplied sources. An edge without sources is marked unverified.
- AI-suggested dependency edges appear on the map immediately. The learner removes an incorrect edge by cutting it on the map.
- Study status records activity and must not be presented as proof of mastery.
- The product refuses assessed-work answers, unrelated requests, and requests to fabricate citations or derivations.
- Saved cards remain usable offline; uncited AI answers are visibly qualified and do not claim source support.
- Mathernet has exactly one AI integration path: a user-supplied provider API key. It does not connect to MCP servers or external search APIs. When the configured model can search the web on its own, that search is used; otherwise the model's answer and any sources it returns are accepted as model output.

## Operating Context

- Local-first desktop and laptop use with a desktop working layout.
- Typical workflow: search or describe a formula, open or create one card, inspect its map, review sources, edit notes, and cut any relationship that is wrong.
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

- Formula card: a saved formula with model-supplied context, sources, and learner-owned notes.
- AI summary: the compact provider-generated note stored with a card and used to ground later explanations.
- Simple introduction: a generated 100-150 word definition explaining what a formula means, how it is used, and why it matters.
- User Module: learner-owned notes and study status.
- Deep-dive session: one generated opening article plus its preserved follow-up conversation for one formula.
- Mind-map session: a named formula workspace with its own graph composition and navigation history.
- Dependency edge: a directed relation between formulas, with a rationale and any model-supplied sources.
- Cut edge: a relationship removed directly on the map by the learner.

## Constraints

- No network dependency is required for local browsing or saved-card interactions.
- No exam or homework answers are produced.
- The local API accepts only loopback Host and Origin values and exposes no cross-origin access.
- Cutting a relationship takes effect immediately; there is no separate acceptance step.
- Personal notes and local graph data remain outside version control.
- Deleting a formula card is global: it removes the card, its incident relationships, its saved deep dives, and its cached introduction from every mind-map session while retaining shared source records.
