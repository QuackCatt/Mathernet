# Relationship deep-dive skill

## Purpose

- Explain why two named formulas are mathematically connected.
- Preserve the relationship direction from the source formula to the target formula.
- Use the saved relationship type and rationale as the starting point, not as unquestionable truth.
- For manually created relationships, distinguish the learner's explanation from independently supported mathematics.

## Research

- Use the model's built-in web search when available and useful.
- Search for both formulas together and for the mathematical concept named by their relationship.
- Prefer established mathematical references, documentation, papers, and reputable educational sources.
- Never invent citations, quotations, URLs, people, or historical events.
- If independent support cannot be found, return an empty `sources` array and state that the article is presenting the learner's note without external confirmation.

## Writing

- Return one coherent article rather than separate Stories, Applications, and Background columns.
- Add an optional section only when it improves understanding.
- Use `story` only for a real historical account, `application` for a concrete use, and `background` for prerequisite or contextual knowledge.
- Write every mathematical expression as LaTeX between single dollar delimiters, such as `$P(A\\mid B)$`. Use double dollar delimiters for large standalone expressions.
- Explain the connection through definitions, transformations, limiting cases, or shared structure when possible.
- State clearly when the saved relationship is a useful learning analogy rather than an exact theorem.
- Do not solve exams, assessed work, or homework.

## Session behavior

- Generate one initial article automatically when no saved relationship exploration exists.
- Preserve the initial article and all later conversation.
- Later questions should continue from the relationship article and preceding messages.
- Continue within the saved conversation instead of asking the learner to create another session.
- If research is unavailable or uncertain, say so in the article or warnings rather than presenting speculation as fact.
