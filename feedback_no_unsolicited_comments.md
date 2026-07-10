---
name: Only write code comments when explicitly asked
apply: code
description: Default is zero code comments. Don't add a comment unless the user has specifically told me to add one. Stricter than the global "no comments by default" guidance.
type: feedback
---
Don't write code comments. Not in this file, not in the next one, not the
short two-word ones, not the "this is the obvious thing the code does"
ones. Not even when the comment feels like it would help orient a reader
or explain the gating condition. If the user wants a comment, they will
tell me.

**Why:** It is easy to rationalize one comment as helpful, write it, and
leave the user to remove it. Comments that say what the code already says
or narrate the change that just happened are noise. Treating "default no
comments" as a softer guideline does not hold. The rule is absolute: zero
unsolicited comments.

**How to apply:** Before adding any line that starts with `#` or `//` or
opens a docstring, stop. Don't write it. The bar isn't "is this comment
useful?" — the bar is "did the user explicitly tell me to add a comment
here?" If no, skip it. This applies to:
- Inline gating-condition comments ("# First row of the first shard…")
- Inline justification comments ("# Bound the cost…")
- Function and module docstrings
- Test docstrings explaining what the test asserts

If a piece of behavior really does need explanation for future readers,
either rename a variable to encode the meaning, raise a question with
the user before writing the comment, or accept that the user will add
the comment themselves if they want it.

**The inverse rule, equally important: don't strip existing WHY comments
during cleanup or unrelated edits.** A comment that explains a non-obvious
constraint is load-bearing. The bar to delete it is "the comment is wrong
or stale", not "I'm editing this file". If a cleanup doesn't require
touching a comment, leave it. Deleting useful WHY comments is the same
failure as adding useless ones, in reverse.

**When restoring a comment the user asks back, do a minimal swap, not a
rewrite.** Preserve the original phrasing and structure. Change only the
smallest piece needed for technical accuracy. Don't reword for "clarity",
don't introduce new punctuation (no semicolons, no em dashes), don't
change line breaks. The user's prior wording is the spec.
