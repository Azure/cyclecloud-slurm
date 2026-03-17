Code Review Scoring Instructions

For every PR:
1. Assign a numeric score out of 100.
2. Produce a table with one row per criterion showing points awarded.
3. End with a single line: FINAL SCORE: <number>/100

Scoring rules (each category starts at max points; apply deductions only):

PR Description Accuracy (20)
- PR description is empty: -20
- Description does not match changes: -20
- Description partially matches but includes unrelated changes: -15
- Otherwise: 0

PR Atomicity (20)
- Multiple independent changes that should be separate PRs: -20
- Otherwise (single atomic change or well-described feature slice): 0

Logical Implementation (10)
- Overly verbose or unnecessarily complex logic: -10
- Otherwise: 0

Regression Risk (10)
- Introduces regression risk not documented in PR description or README: -10
- Otherwise: 0

Exception Handling (10)
- Exceptions not handled or errors not logged meaningfully: -10
- Otherwise: 0

Code Comments (10)
- Comments explain HOW instead of WHAT/WHY, or missing required docstrings: -10
- Otherwise: 0

Repetitive Code (10)
- Significant duplicated logic introduced: -10
- Otherwise: 0

Spelling (5)
- Any spelling errors present: -5
- Otherwise: 0

Logging Quality (5)
- Log levels inappropriate or messages unclear: -5
- Otherwise: 0

Output table columns (exact):
| Criterion | Max Points | Points Awarded | Notes |


Merge Recommendation (must appear after FINAL SCORE)

After computing FINAL SCORE, output exactly:

RECOMMENDATION: <MERGE | MERGE WITH FOLLOW-UPS | DO NOT MERGE>
RATIONALE: <1-2 sentences>
BLOCKERS: <0-3 bullet points, or "None">

Rules:
- If any HIGH-SEVERITY issue exists -> RECOMMENDATION: DO NOT MERGE (regardless of score).
  HIGH-SEVERITY includes: security flaw, correctness bug likely to break users, data loss risk, auth/secret exposure, unsafe concurrency/race.
- Else if FINAL SCORE >= 90 -> MERGE
- Else if FINAL SCORE >= 75 -> MERGE WITH FOLLOW-UPS
- Else -> DO NOT MERGE

For MERGE WITH FOLLOW-UPS:
- List the top 1-3 follow-ups as bullets under BLOCKERS only if they must be fixed before merging.
- If follow-ups can be post-merge, put them in RATIONALE as "follow-up items" and set BLOCKERS: None.
