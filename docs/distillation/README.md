# Prompt and rubric distillation

How groundcast turns its reference sources into prompt rules, and where
each rule in the prompts came from. The sources and their local copies are
registered in [`references/`](../../references/README.md).

## Rules for these notes

- Write every rule in our own words. Do not copy sentences from a book, paper,
  transcript, or guide, and do not paste podcast dialogue: these notes are
  public, the sources mostly are not.
- Record the source ID (S1 to S26) and, where it helps, a page, section, or
  episode locator, so a rule can be checked against its source later.
- From podcasts (tier T3) take structure only: openings, recap cadence, host
  roles, how analogies are introduced. Never wording.
- When sources disagree, learning research (T1) outranks podcast practice
  (T3), and correctness outranks every style rule.

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

The rubric (`src/groundcast/prompts/rubric.md`) merges the candidate rules
of the notes in this directory:

| Rubric rule (short form) | Section | Sources | Note |
|---|---|---|---|
| Cite the passages each claim rests on; say nothing they do not say | Correctness | S20, S23, S24 | S20-fever, S24-facts-grounding |
| One fact per sentence, so each can be checked | Correctness | S17 | S17-factscore |
| Give a finding's limits and strength of evidence with it | Correctness | S14 | S14-science-vs |
| Overall finding before a single case; say how typical it is | Correctness | S26 | S26-dahlstrom-2014 |
| Framing is marked, short, true in its mapping, and adds no facts | Correctness | S26 | S26-dahlstrom-2014 |
| Open with the question or a case from the passages, why it matters, and the plan | Structure | S15, S14, S13, S25 (signalling) | S15-philosophize-this, S14-science-vs, S13-hidden-brain, S25-mayer-2024 |
| Name each part with one trait before relations; define terms first, paired terms together | Structure | S05, S25 (pretraining), S15 | S05-sweller, S25-mayer-2024, S15-philosophize-this |
| One segment per idea, headed by the question it answers; processes in time order | Structure | S14, S25 (segmenting), S26 | S14-science-vs, S25-mayer-2024, S26-dahlstrom-2014 |
| Short recap and a bridge at each segment end; close by answering the opening question | Structure | S13, S14, S03, S05 | S13-hidden-brain, S14-science-vs, S03-dunlosky, S05-sweller |
| Leave out off-goal material; no restating right after making a point | Structure | S25 (coherence), S05 (redundancy) | S25-mayer-2024, S05-sweller |
| Fit definitions and recaps to the brief's level | Structure | S05 (expertise reversal) | S05-sweller |
| Refer back by naming the earlier point again | Structure | S13 | S13-hidden-brain |
| Short sentences, subject and verb early | Writing for the ear | S07 | S07-npr-training |
| Signposts between steps | Writing for the ear | S07, S25 (signalling) | S07-npr-training, S25-mayer-2024 |
| Conversational register; active verbs | Writing for the ear | S25 (personalisation), S07 | S25-mayer-2024, S07-npr-training |
| No written-only structures; numbers as spoken | Writing for the ear | S07 | S07-npr-training |
| Attribution first; name a source before what it says | Writing for the ear | S07, S14 | S07-npr-training, S14-science-vs |
| Same word for the same thing | Writing for the ear | S07 | S07-npr-training |
| Raise a question, then answer it; voice an objection the passages answer | Vividness | S07, S15 | S07-npr-training, S15-philosophize-this |
| Concrete, typical cases from the passages | Vividness | S07, S26, S13 | S07-npr-training, S26-dahlstrom-2014 |
| Announce analogies, one image at a time, right after the idea | Vividness | S14, S15, S05, S07 | S14-science-vs, S15-philosophize-this, S05-sweller |
| Verifier labels: supported, contradicted, unsupported, framing, no claim | Verifier prompt | S20, S17, S23 | S20-fever, S17-factscore |
| Retrieve passages with the line before the sentence | Verifier input | S23 | S23-minicheck |
| Host B asks for a term at first use, voices doubts the passages answer, sums up for Host A to check; questions never hold their answers; comparisons announced | Two-host prompt | S13, S14, S07 | S13-hidden-brain, S14-science-vs, S07-npr-training |
| Recall questions ask the listener to produce the answer; "why" and "how" only about what was explained | Recall prompt | S03 | S03-dunlosky |
