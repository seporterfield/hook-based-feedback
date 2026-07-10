---
name: Validate system claims against docs or source
description: "Any present-tense claim about how a code, service, or system behaves must be validated against docs/source before stating it; answering from training data is a failure"
type: feedback
---

Before stating how any external system behaves (AWS service, runtime, protocol, tool, API, library), validate the specific claim against current documentation or source. Do not answer from training data. This covers behavior, limits, defaults, billing, lifecycle, log formats, version-gated behavior. Conceptual "explain how X works" questions count, not just debugging.

**Why:** Explaining a system from memory is where wrong claims come from. Defaults change, limits get revised, billing models shift, and version-gated behavior differs across releases. Training-data recall is stale and untraceable, and a confident wrong claim costs the reader more than a hedge would.

**How to apply:** Use WebFetch on the authoritative doc, Context7 for libraries (even well-known ones), or read source for in-repo behavior. State only what the source confirms. Mark anything you cannot find a source for as unverified, or drop it. A deterministic hook cannot judge whether a claim was verified, so the enforcement is the lookup itself, folded into the drafting pass before output.
