# S20 FEVER

- Source: Thorne, J. et al. 2018. FEVER. NAACL-HLT 2018, 809-819. doi:10.18653/v1/N18-1074
- Read: 2026-10-12, full paper: sections 1 to 7 (claim generation,
  labelling guidelines, validation findings, baseline pipeline, error
  analysis).

Page numbers are the proceedings pages.

## Candidate rules

| Rule (our words) | Locator | Role | Pass example (ours) | Fail example (ours) |
|---|---|---|---|---|
| Three outcomes with evidence: a supported or contradicted verdict must name the passage or passages that decide it; an unsupported verdict needs none. Score a supported or contradicted verdict as right in the eval only when its evidence includes the passage that actually decides it. | Sec 3.2, p.811; Sec 5.2, p.814 | Verifier, Evaluation | Eval item expects contradicted with evidence chunk 3; the Verifier says contradicted citing chunk 3: counted right. | Verifier says contradicted citing chunk 1, which says nothing on the point: counted right because only the label is compared. |
| Contradicted needs passages that rule the claim out. When the passages state something different but compatible, the claim is unsupported, not contradicted. Do not use world knowledge to turn a difference into a conflict. | Sec 3.4.4, p.812-813 | Verifier | Passage: the Ostra feeds Lake Varne. Sentence: "The Kell stream feeds Lake Varne." A lake can have several inflows, so: unsupported. | Same case labelled contradicted. Only a passage saying the Ostra is the sole inflow would rule it out. |
| Check that a short or shared name in the sentence refers to the same thing as in the passage. Annotators readily accepted support for an ambiguous short name. | Sec 3.4.4 (entity resolution), p.813 | Verifier | Materials cover two lakes, each with a north station. Sentence about Varne's north station is checked only against passages about Varne. | Sentence about Varne's north station is supported by a passage about the other lake's north station. |
| Allow support that needs two or more passages together, and cite all of them. A sizeable share of claims needed several sentences, some from different pages. | Sec 1, p.809-810; Fig 1; Sec 5.2 | Verifier, Evaluation | Passage A: the survey ran in 1998. Passage B: the survey found eel in the lake. Sentence: "Eel were found in the lake in 1998." Supported, citing A and B. | Verifier checks each passage alone, finds neither sufficient, and flags a correct sentence. |
| Build seeded errors from all six mutation types: paraphrase, negation, swap for a similar thing, swap for a dissimilar thing, more general, more specific. Avoid lazy negations that just insert "not"; they are too easy to catch. | Sec 3.1, p.811 | Evaluation | Seeded "more specific" item: the notes say the lake freezes in winter; the sentence says it freezes every January. Tagged specific. | Seeded set has ten items that only add "not" to a correct sentence, and none that over-specify. |
| Unsupported eval items should come with passages on the same topic that fall just short, not with unrelated text. Related but insufficient evidence was the hard case; random text made the task look easier than it is. | Sec 4, Sec 5.5, Table 3, p.813-815 | Evaluation | Unsupported item about the lake's fish counts is checked against the chunk on the lake's fish species. | Unsupported item is checked against a chunk about a different subject entirely. |
| Each claim in a script must be specific enough to check. Claims too vague to verify were discarded from the dataset; in a script they are filler that the Verifier cannot judge. | Sec 3.4, p.812 | Writer, Editor | "The lake's level fell by two metres between 1990 and 2000." | "The lake changed a lot over the years." |
| Decide from the passages given for the sentence and nothing else. Supported when they clearly back it, contradicted when they clearly count against it; otherwise name the missing piece in the rationale and label unsupported. | Sec 3.2 (labelling guideline), p.811-812 | Verifier | Rationale: the passages give the length but not the depth; the depth part is unsupported. | Rationale: the depth sounds reasonable for a lake this size, so supported. |

## Not adopted

- The TF-IDF retrieval and decomposable attention baseline: dated, and
  groundcast already retrieves with BM25 and verifies with an LLM.
- Wikipedia introductions as the evidence pool and claims generated from
  them: groundcast verifies against the learner's materials.
- The rule that claims are judged outside any context: groundcast passes the
  previous line so that references can be resolved.
- Simulated not-enough-info training data (sampling sentences): there is no
  model training in groundcast; only the eval lesson (related negatives) is
  kept.
