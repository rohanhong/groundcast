# S22 SelfCheckGPT

- Source: Manakul, P. et al. 2023. SelfCheckGPT. EMNLP 2023, 9004-9017. doi:10.18653/v1/2023.emnlp-main.557
- Read: 2026-10-12, full paper: sections 1 to 9 (grey-box baselines, the five
  consistency variants, annotation scheme, sentence and passage results,
  comparison with a reference passage, sample-count and model ablations) and
  appendices A to C.

Locators are section, table, and figure numbers.

## Candidate rules

| Rule (our words) | Locator | Role | Pass example (ours) | Fail example (ours) |
|---|---|---|---|---|
| When passages exist, check against them; sampling the model several times is a fallback for when no source exists. Comparing against the reference passage beat self-sampling for the prompt and NLI variants. groundcast always has passages, so self-consistency never replaces the Verifier. | Sec 7.3, Table 3 | Verifier, Tutor | A Tutor answer is checked sentence by sentence against the retrieved passages. | A Tutor answer is accepted because three resampled answers agree with it. |
| Use repeated Verifier runs as a stability signal: if repeated judgments of the same sentence disagree, treat the sentence as uncertain and fail it. This adapts the paper's core idea (disagreement between samples signals a guess) to the checker itself. | Sec 1, Sec 5 (idea); Sec 7.3, Fig 7 | Verifier, Evaluation | Two runs give supported, one gives unsupported: the sentence is flagged for revision. | The majority label supported is kept and the split is not recorded. |
| A verdict the parser cannot read must count as a failure, never as a pass. The paper mapped unreadable answers to a middle value; for a gate, the safe side is failure. | Sec 5.5 | Verifier | Verifier returns a malformed label for sentence 9; sentence 9 is marked unsupported and retried. | Malformed output is dropped and sentence 9 is treated as checked. |
| A cheap lexical pre-check helps: a number or proper name in a claim that appears in none of the passages is a strong error sign. The least supported single token was among the best signals. Flag such sentences in code before the LLM call, after normalising spoken numbers; the flag can only add a failure, never clear one. | Sec 7.1 (observations 3 and 4), Table 2; App D, Table 7 | Verifier | Sentence says "nineteen ninety-eight"; the passages contain 1998; the normalised forms match, no flag. | Sentence names the Kell stream; no passage contains "Kell"; the pre-check is skipped and the LLM, primed by a related passage, passes it. |
| When eval annotators disagree on an item's label, keep the stricter label or drop the item. The paper resolved every disagreement to the worse label. | Sec 6 | Evaluation | Two reviewers give supported and unsupported; the item is stored as unsupported, or removed. | The item is stored as supported because the author of the item preferred it. |
| Weaker models could not do the prompt-based support check at all. Any new Verifier model, local or remote, must pass `groundcast eval` before it is used. | Sec 5.5; Sec 7.3, Table 4 | Evaluation | A smaller local model is tried; the eval shows detection 0.71, so it is not adopted. | A smaller model is switched in because it answers in the right format. |
| A sentence can mix accurate and inaccurate content, so sentence-level labels are coarse; the paper itself points to atomic facts as the finer unit. Keep the instruction that every fact in a sentence must be supported. | Sec 9 (limitations) | Verifier | Mixed sentence labelled unsupported with the failing fact named. | Mixed sentence labelled minor error and passed. |

## Not adopted

- Grey-box signals (token probabilities, entropy): the CLI backends do not
  expose them, and proxy models did poorly in the paper.
- Twenty stochastic samples per response: too costly for every script, and
  passages are always available.
- BERTScore, question-answering, and n-gram model variants: weaker than the
  prompt variant, and only the n-gram insight (rare tokens) is kept, as a
  lexical pre-check.
- The three-level accuracy scale (major, minor, accurate): groundcast gates
  on pass or fail, and its fail labels already say why.
