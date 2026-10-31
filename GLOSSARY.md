# Glossary

Domain language for Sick's evidence-gated SDLC. Definitions only — no
implementation details.

**Run**: One task's lifecycle instance, from intake to a terminal outcome.

**Phase**: A Run's current stage: `intake`, `requirements`, `design`,
`implement`, `verify`, `deliver`, `blocked`, or `cancelled`.

**RiskTier**: How dangerous a Run is judged to be: `trivial`, `standard`,
or `risky`. The tier decides which Gates apply.

**Artifact**: A persisted output of a Run (requirements, design, plan,
verification, summary) that a human can audit after the fact.

**Evidence**: A recorded verification result (test/lint run) that occurred
after a Run's last change.

**Gate**: A rule that decides whether a Run may be delivered. A failing
Gate blocks delivery regardless of what anyone claims.

**ToolResult**: The outcome of one tool call: whether it succeeded, what
it produced, and how it failed if it did.

**DesignIssue**: A deterministic finding about changed code. Hard issues
block delivery; warnings are recorded.
