# S21 RAGAs

- Source: Es, S. et al. 2024. RAGAs. EACL 2024 Demos, 150-158. doi:10.18653/v1/2024.eacl-demo.16
- Read: 2026-10-12, full paper: sections 1 to 8 (metric definitions and
  prompts, WikiEval construction, agreement results, reproducibility).

Page numbers are the proceedings pages.

## Candidate rules

| Rule (our words) | Locator | Role | Pass example (ours) | Fail example (ours) |
|---|---|---|---|---|
| Measure Tutor answer faithfulness as the share of its statements that the passages support, with each statement checked on its own. A decomposed check agreed with human judges far more often than asking a model for one overall score or for a ranking of two answers. | Sec 3 (faithfulness), p.152; Sec 5, Table 4, p.154-155 | Evaluation, Tutor | Eval scores a three-sentence answer as two of three supported and names the failing sentence. | Eval asks the model to rate the answer's faithfulness from 0 to 10 and records a 7. |
| Faithful is not the same as helpful. Score separately whether the answer addresses the question asked; an answer can be fully grounded and still incomplete or padded. | Sec 3 (answer relevance), p.152; Table 2 | Evaluation, Tutor | Question: when does the harbour flood? Answer: "At spring tides, according to your notes." Grounded and on point. | Answer: "Your notes discuss the harbour and its tides in some detail." Grounded, but it does not answer. |
| Ask for a short reason for each statement before the verdict, and require a fixed structured output. Structured output made scores clearly more stable between runs; the reason-first order is the paper's design and should be tested with the eval before adoption. | Sec 3 (verification prompt), p.152; Sec 5.1, Fig 1, p.155 | Verifier | Output schema per sentence: id, rationale, label, evidence, in that order, validated by the parser. | Free-text answer that the code scans for the word supported. |
| Track run-to-run stability per item, not only the mean. Repeated runs of the same configuration can differ; an item whose label flips between runs is a weak point even if the mean looks fine. | Sec 5.1, p.155 | Evaluation | Eval report lists items that received different labels across the three runs. | Report shows only the mean detection rate across runs. |
| Retrieval quality is a separate problem from answer quality, and picking the crucial sentences from a long context was the hardest step for the model. Keep Tutor passages short and few, and evaluate retrieval on its own. | Sec 3 (context relevance), p.153; Sec 5, p.155 | Tutor, Evaluation | Tutor receives the four best chunks for the question; the eval checks whether the chunk that holds the answer was among them. | Tutor receives every chunk from the source document; the eval only scores the final answer. |
| Negative eval answers can be made by answering the same question without the passages, then checking by hand which statements are now unsupported. This produces realistic errors rather than hand-planted ones. Confirm first that model-written items meet the rule that eval material is self-written. | Sec 4 (faithfulness data), p.153 | Evaluation | A closed-book Tutor answer about the fictional lake is reviewed, and its invented depth figure becomes a labelled unsupported item. | Every negative item is made by changing one word in a correct answer. |

## Not adopted

- The context relevance ratio (crucial sentences over all sentences): it
  penalises chunk size more than retrieval quality, and groundcast's chunks
  are fixed by ingestion.
- Answer relevance via generated questions and embedding similarity: it
  needs an embedding model and network calls; a direct judge of whether the
  answer addresses the question is simpler for groundcast.
- The specific prompts, gpt-3.5-turbo-16k, and the LlamaIndex and LangChain
  integrations.
- WikiEval itself: built from web pages; groundcast eval materials must be
  self-written or openly licensed.
