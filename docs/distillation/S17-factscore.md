# S17 FActScore

- Source: Min, S. et al. 2023. FActScore. EMNLP 2023, 12076-12100. doi:10.18653/v1/2023.emnlp-main.741
- Read: 2026-10-12, full paper: sections 1 to 5, Limitations, appendices A (data
  collection, error and disagreement analysis), B.1 to B.5 (estimator details,
  ablations, other domains), C (editing experiments), and the decomposition
  prompt in Table 15 (read for structure only).

Page numbers are the proceedings pages.

## Candidate rules

| Rule (our words) | Locator | Role | Pass example (ours) | Fail example (ours) |
|---|---|---|---|---|
| Judge the separate facts inside a sentence one by one; a sentence passes only when every fact in it is supported. A sentence is the wrong unit for a verdict because one sentence often mixes a supported and an unsupported fact. | Sec 3.1, p.12078; footnote 2, p.12076 | Verifier | Passages: Lake Varne is 14 km long and fed by the Ostra River. Sentence: "Lake Varne is fourteen kilometres long and fed by the Ostra." Every fact matches: supported. | Same passages. Sentence: "Lake Varne is fourteen kilometres long and fed by two rivers." Length matches, river count does not; labelled supported because most of the sentence is right. |
| Support is always relative to a named source, here the learner's passages. Do not upgrade a fact to supported because it is true in the world. | Sec 3.1 (key idea 2), p.12078 | Verifier, Tutor | Passages say nothing about the lake's depth. Sentence: "The notes do not give the lake's depth." No claim beyond the passages. | Sentence: "Lake Varne is about forty metres deep." The checker knows a real lake of that name is that deep and marks it supported. |
| A conclusion that is likely but not stated is unsupported. Annotators disagreed most on such inferred facts, so the rule must be explicit. | App A.5, Table 8, p.12091 | Verifier | Passage: high tide at the harbour came at 06:10 and 18:35. Sentence: "There were two high tides that day." Counting the stated times is a direct consequence: supported. | Passage: the harbour floods at spring tides. Sentence: "The harbour floods every month." Plausible, since spring tides recur, but the passage never says it: must be unsupported, not supported. |
| An opinion or verdict that the materials attribute to someone must keep its attribution. Stated as plain fact it misrepresents the source. | Sec 3.4, Table 2 (subjective category), p.12080 | Writer, Verifier | Passage: the guide's author calls Lake Varne the jewel of the valley. Sentence: "The guide's author calls Lake Varne the jewel of the valley." | Sentence: "Lake Varne is the jewel of the valley." The opinion is now presented as a fact about the lake. |
| Most errors that survive retrieval are word-level slips in numbers, dates, and names. Seed eval errors mainly there, and make the Verifier compare each one explicitly. | Table 2, p.12080 (single-sentence contradiction, words) | Evaluation, Verifier | Seeded item changes 1962 to 1926 in a sentence about when the dam was built; tagged as a date error. | Seeded set has only relation reversals and no number or date swaps, so the most common real error type is never measured. |
| When a sentence fails, check the sentences after it that build on it. A follow-up that only expands a removed fact must be revised or removed too, even if it is supported on its own. | Sec 3.3 step 3; App A.4, Table 7, p.12090 | Editor | Sentence 4 (unsupported) claims a second inflow; sentence 5 names that inflow's source. The reviser removes 4 and rewrites 5. | Sentence 4 is removed, sentence 5 is kept and now describes "it" with no referent. |
| Hand the reviser the failing fact and the reason, not just a failed sentence. Fact-level labels made edits far more targeted and cut the cases where the editor copied the input unchanged. | App C.3, Table 14 | Editor | Reviser input: sentence 7 failed because the passage gives 14 km, not 41 km. | Reviser input: sentence 7 failed. The reviser rewrites a different part of the sentence. |
| Report factual precision together with how much the script says (claims per minute, key points covered). Precision alone rewards saying less, and a reviser that deletes content can look better than one that fixes it. | Sec 3.1 (precision not recall); Limitations, Table 6 | Evaluation | Report: 98 percent of claims supported, 31 claims, 9 of 10 brief key points covered. | Report: 100 percent supported, after the reviser deleted half the segment. |
| Retrieved passages that lack direct evidence caused most estimator errors, and extra passages distracted the checker. Give the Verifier the passages the sentence cites plus a small, tuned number of retrieved ones; measure retrieval misses separately in the eval. | App B.3, Table 13 | Verifier, Evaluation | Eval item whose supporting fact sits in a chunk the Writer did not cite; the report shows whether retrieval found it. | All eval items cite the right chunk, so retrieval misses never appear in the numbers. |
| Ask for a direct verdict per fact against the passages. Generating a question and comparing answers misfired because the questions were vague and two correct answers did not match. | App B.3, Table 11 | Verifier | Prompt asks for a label for the sentence against the passages. | Prompt asks the model to write a question about the sentence, answer it from the passages, and compare strings. |

## Not adopted

- The nonparametric probability estimator (masked language model over the
  corpus): it needs a separate model and index and only helped for some
  subject models; groundcast uses an LLM verifier.
- The Irrelevant label as a third outcome: groundcast scripts are generated
  on topic from the brief, and off-topic content is the Editor's concern, not
  a verification label.
- Wikipedia as the knowledge source and the biography task: groundcast's
  source is the learner's own materials.
- Error rate of the aggregate score as the main eval metric: groundcast gates
  each sentence, so per-item detection and false-flag rates matter more than
  an aggregate estimate.
- Entity rarity analysis: it concerns closed-book generation, not grounded
  scripts.
