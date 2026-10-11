# Prompt and rubric distillation

How groundcast turns its reference sources into prompt rules (design spec,
section 9.2), and where each rule in the prompts came from. The sources and
their local copies are registered in [`references/`](../../references/README.md).

## Rules for these notes

- Write every rule in our own words. Do not copy sentences from a book, paper,
  transcript, or guide, and do not paste podcast dialogue (spec N3): these
  notes are public, the sources mostly are not.
- Record the source ID (S1 to S24) and, where it helps, a page, section, or
  episode locator, so a rule can be checked against its source later.
- From podcasts (tier T3) take structure only: openings, recap cadence, host
  roles, how analogies are introduced. Never wording.
- When sources disagree, learning research (T1) outranks podcast practice
  (T3), and correctness outranks every style rule (spec 9.3).

## Process

1. Read a source and write `S<nn>-<short-name>.md` here with its candidate
   rules (template below).
2. Merge candidate rules into the rubric: each becomes a checkable criterion
   with a pass and a fail example written by us.
3. Move rubric sections into the role prompts in `src/groundcast/prompts/`
   (`rubric.md` is shared by the Writer, reviser, and Editor prompts).
4. Change one prompt at a time and keep the change only if the evaluation
   improves (`groundcast eval` for the Verifier, `groundcast eval-quality`
   for script quality, judged against the fixed criteria in
   `src/groundcast/prompts/judge.md`).
5. Update the traceability table below in the same change.

## Note template

```markdown
# S<nn> <short title>

- Source: <citation as in references/README.md>
- Read: <date>, <which parts>

## Candidate rules

| Rule (our words) | Locator | Role | Pass example (ours) | Fail example (ours) |
|---|---|---|---|---|
|  |  | Writer / Verifier / Editor / Voice director |  |  |

## Not adopted

- <rule considered and why it was left out>
```

## Traceability of the current rubric

The M1 rubric in `src/groundcast/prompts/rubric.md` was drafted from the
principles the spec attributes to these sources, before any source note
existed. Every row is provisional until a note in this directory confirms it.

| Rubric rule (short form) | Section | Provisional sources | Confirmed by note |
|---|---|---|---|
| Cite the passages each claim rests on; say nothing they do not say | Correctness | Spec G2; S20, S23 | |
| One fact per sentence, so each can be checked | Correctness | S17 | |
| Mark analogies and examples as framing; the mapping must be true | Correctness | Spec 9.3 | |
| Open with what the session covers and why it matters | Structure | S1 (signalling), S7 | |
| Define a term before using it | Structure | Spec 9.3 (logical rigour) | |
| One segment per idea; recap at segment end and session end | Structure | S1 (segmenting), S5, S3 | |
| Repeat key points rather than rely on memory of earlier detail | Structure | S5 (transient information) | |
| Short sentences, one idea each | Writing for the ear | S7 | |
| Signposts between steps | Writing for the ear | S7, S1 (signalling) | |
| Conversational register, "you" is fine | Writing for the ear | S1 (personalisation), S7 | |
| No tables, lists, parentheses, or symbols; numbers as spoken | Writing for the ear | S7; spec 9.3 (fluency) | |
| Attribution before the statement | Writing for the ear | S7 | |
| Verifier labels: supported, contradicted, unsupported, framing, no claim | Verifier prompt | S20, S17, S23 | |
