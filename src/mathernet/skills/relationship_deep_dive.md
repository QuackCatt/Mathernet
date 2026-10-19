# Relationship deep-dive skill

## Purpose

- Explain why two named formulas are mathematically connected.
- Preserve the relationship direction from the source formula to the target formula.
- Use the saved relationship type as the mathematical starting point.
- For AI-created relationships, explain the connection independently.
- For AI-confirmed manual relationships, incorporate `learner_note` as user-supplied context when present, but do not treat it as unquestionable truth.
- Do not add a `learner_note` field when the user left the explanation empty.

## Research

- Use the model's built-in web search when available and useful.
- Search for both formulas together and for the mathematical concept named by their relationship.
- Prefer established mathematical references, documentation, papers, and reputable educational sources.
- Never invent citations, quotations, URLs, people, or historical events.
- Return only source URLs that were actually found and support the explanation.

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
