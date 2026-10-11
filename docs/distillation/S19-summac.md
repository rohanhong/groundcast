# S19 SummaC

- Source: Laban, P. et al. 2022. SummaC. TACL 10, 163-177. doi:10.1162/tacl_a_00453
- Read: 2026-10-12, full paper: sections 1 to 6 and appendices A (NLI models,
  operator choice, ROC-AUC results).

Page numbers are the journal pages.

## Candidate rules

| Rule (our words) | Locator | Role | Pass example (ours) | Fail example (ours) |
|---|---|---|---|---|
| Check each script sentence on its own against the passages. Never ask for one verdict on a whole segment or script: a whole-text check rated a summary as entailed while one of its sentences had no support at all. | Sec 1, Fig 1, p.163-164; Sec 5.3.3, Table 5, p.171-172 | Verifier, Evaluation | A six-sentence segment yields six verdicts; sentence 4 is flagged alone. | The segment is sent as one block and judged consistent, hiding sentence 4. |
| The evidence unit should be at least as large as the claim. Splitting the source finer than the claim hurt every model; when a script sentence fuses two passage sentences, the Verifier must see both and may cite both. | Sec 5.3.3, Table 5, p.171-172 | Verifier | Passages: the Ostra enters Varne from the north; the Ostra carries most of the lake's inflow. Sentence: "The Ostra, entering from the north, brings most of the water." Supported, citing both. | Each passage is checked against the whole sentence separately; neither alone covers it, so a correct sentence is flagged. |
| A sentence is supported when the best evidence for it supports it, so take the strongest passage (or pair) per sentence; but gate the script per sentence. An average over sentences is only a report number, because one failing sentence must still block. | Sec 3.2, p.166; App A, Table A1 | Verifier, Evaluation | Script with 40 supported sentences and 1 unsupported is held until that sentence is fixed; the report shows 0.98 as information. | Script passes because its mean score of 0.98 is above a 0.9 cut-off. |
| Grounded consistency is not world accuracy. Correct background that the passages do not contain still counts as unsupported. | Sec 2.1, p.164 | Verifier | Passages describe tides at one harbour. Sentence adds nothing beyond them: supported. | Sentence adds "Tides are caused mainly by the Moon." True, but not in the passages: should be unsupported, labelled supported. |
| Report balanced accuracy (the mean of detection rate and correct-pass rate) next to detection and false-flag rates. Eval sets have very different shares of errors, and plain accuracy rewards a checker that passes everything. | Sec 4.3, Eq 1, p.168-169 | Evaluation | Report on a set with 80 percent correct items: detection 0.95, false flags 0.06, balanced accuracy 0.945. | Report shows accuracy 0.84 for a checker that passes every item and catches nothing. |
| Any score threshold (for example for a local model) is tuned on a separate validation split, never on the items used to report results. | Sec 4.3, p.169 | Evaluation | Threshold for a local checker chosen on a validation file; detection reported on the held-out file. | Threshold chosen to maximise detection on the same 118 items that are then reported. |
| Use the contradiction signal, not only entailment, where a model offers both; it gave a small gain. Keep contradicted and unsupported apart in groundcast's labels. | Sec 5.3.2, Table 4, p.171-172 | Verifier | Sentence giving 41 km where the passage says 14 km is labelled contradicted, with the passage ID. | Every failure is reported as unsupported, so the reviser cannot tell a wrong number from a missing fact. |
| A verdict must trace back to the passage that decided it. Keep evidence IDs on every supported and contradicted verdict so a learner or reviser can see why. | Sec 6 (interpretability), p.172 | Verifier | Verdict: contradicted, evidence [notes-3], rationale names the number. | Verdict: contradicted, no evidence, rationale says the sentence seems wrong. |

## Not adopted

- SummaC-Conv, the trained histogram layer over NLI scores: it needs
  training data in our domain and an NLI model; groundcast uses an LLM
  verifier. A later local checker (S23) supersedes it.
- The NLI model choices and the news benchmark itself: specific to 2021
  models and news summaries.
- Paragraph or two-sentence document blocks as a fixed setting: groundcast's
  chunking is set by ingestion; the rule kept is only that evidence should
  not be finer than the claim.
- Throughput comparisons: not relevant at groundcast's scale.
