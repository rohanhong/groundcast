# S24 FACTS Grounding

- Source: Jacovi, A. et al. 2025. The FACTS Grounding Leaderboard. arXiv:2501.03200
- Read: 2026-10-12, full report (arXiv v1): sections 1 to 5 and appendix A
  (judge prompt templates and the eligibility rubric, read for structure
  only).

Locators are section and table numbers.

## Candidate rules

| Rule (our words) | Locator | Role | Pass example (ours) | Fail example (ours) |
|---|---|---|---|---|
| A script or answer is grounded only if every information-bearing sentence is grounded; one ungrounded sentence makes the whole unit fail until it is fixed. | Sec 3.1 | Verifier, Tutor | A Tutor answer with three supported sentences is shown without warnings. | A Tutor answer with one unsupported sentence is shown without a warning because the other two are fine. |
| Label sentence by sentence, never the whole response at once. In the paper's judge comparison, whole-response templates let most ungrounded responses through (false acceptance between about 73 and 95 percent), while sentence-level templates caught far more. | Sec 3.1, Table 2 | Verifier | The Verifier returns one label per sentence id. | The Verifier is asked whether the answer as a whole is grounded and says yes. |
| Count a sentence as supported or contradicted only on plain evidence in the passages; otherwise unsupported. Outside knowledge is allowed only when it is trivial and needed to read the passage (units, calendar arithmetic), never about the subject. | App A (strict sentence-level template) | Verifier | Passage: the ferry takes 90 minutes. Sentence: "The crossing takes an hour and a half." Unit reading only: supported. | Passage: the ferry crosses Lake Varne. Sentence: "The ferry crosses the deepest lake in the region." Depth ranking comes from outside: should be unsupported. |
| Ask the Verifier for a short excerpt from the passage for each supported or contradicted verdict, and check in code that the excerpt really occurs in the cited passage (after normalising spacing and case). A missing or invented excerpt turns the verdict into unsupported. The excerpt check is our extension of the paper's format. | App A (sentence-level templates) | Verifier | Verdict supported, evidence [notes-2], excerpt "fed by the Ostra River", found in notes-2. | Verdict supported, excerpt "fed by two rivers", which appears in no passage, and the verdict is kept. |
| A grounded answer that dodges the question still fails. Check separately that a Tutor answer (and each script segment) actually delivers what was asked; vague, safe answers were disqualified in the benchmark. | Sec 3.2, Table 3 | Tutor, Editor, Evaluation | Question: what drives the spring tides in the notes? Answer gives the two causes the notes list. | Answer: "The notes describe several factors behind the tides." Grounded, but says nothing. |
| A judge tends to rate output from its own model family higher (a mean of about three points in the paper). Prefer a Verifier model from a different family than the Writer where the backends allow it, and record the pairing in every eval report. | Sec 3.1; Sec 4 (aggregating judges) | Evaluation, Verifier | Eval report header: Writer model A, Verifier model B. | The Writer and Verifier use the same model, and the eval baseline was measured with a different pairing. |
| The best judge prompt differed by judge model. Switching the Verifier model means re-running `groundcast eval` and, if needed, trying the prompt variants again. | Sec 3.1, Table 2 | Evaluation | After a model change the eval is re-run before the new model is used for sessions. | The model is swapped in config and the old eval result is assumed to still hold. |
| A second narrow pass (sentence against its quoted excerpt only) did not improve agreement with human labels for any judge. Do not add such a pass by default; test it with the eval first. | Sec 3.1, Table 2 (double-check template) | Verifier | Single sentence-level pass, measured by the eval. | An extra yes or no pass per sentence added for safety, doubling calls with no measured gain. |

## Not adopted

- A panel of three commercial judges averaged together: groundcast runs one
  configured backend; the self-preference finding is kept as the pairing
  rule instead.
- Treating opinions as needing no attribution (the paper's no-attribution
  label covers opinions, greetings, questions, disclaimers): in groundcast an
  opinion about the subject is still a claim that must come from the
  materials (see S17); only signposts and rhetorical questions are no_claim.
- The eligibility judge that compares against a baseline response: groundcast
  has no baseline response; a direct check that the answer addresses the
  question is enough.
- Excluding tasks that need arithmetic or reasoning, as the benchmark did:
  groundcast scripts do derive simple totals and differences, which the
  Verifier must handle (seeded items tagged derived and arithmetic).
- Documents up to 32k tokens in one prompt: groundcast checks against
  retrieved passages, not whole documents.
