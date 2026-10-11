# S23 MiniCheck

- Source: Tang, L., Laban, P. and Durrett, G. 2024. MiniCheck. EMNLP 2024, 8818-8847. doi:10.18653/v1/2024.emnlp-main.499
- Read: 2026-10-12, full paper: sections 1 to 9, Limitations, appendices A
  (synthetic data analysis and human check), B (threshold tuning,
  decomposition, decontextualization, labelling all sentences at once), C
  (benchmark datasets, label mapping, exclusions), E (checker inference
  details, chunk sizes), G (training), H (prompts, read for structure only).
  Also the four Hugging Face model cards and API records and the reference
  inference code (github.com/Liyan06/MiniCheck, files minicheck.py and
  inference.py on main), all checked on 2026-10-12.

Page numbers are the proceedings pages.

## Candidate rules

| Rule (our words) | Locator | Role | Pass example (ours) | Fail example (ours) |
|---|---|---|---|---|
| Check each sentence whole, with an instruction to check every fact in it. A separate step that first splits sentences into atomic facts gave no consistent gain while multiplying cost by two to four. Add decomposition only if `groundcast eval` shows it helps. | Sec 7.1, Table 5, p.8824; App B.2 | Verifier | One Verifier call per batch of sentences, each judged whole. | A decomposition call per sentence, then a check per fact, with no measured gain. |
| The hard cases are sentences that bundle several facts and facts that need two passage sentences combined. Seed eval items of both kinds. | Sec 2 (challenges), Fig 2, p.8819-8820; App A.1 | Evaluation | Item: the notes give the dam's height in one sentence and its year in another; the script sentence states both. | Every seeded item can be decided from a single passage sentence. |
| A sentence that starts with a reference word needs the previous line for retrieval, even though the judge itself copes well. Build the Verifier's retrieval query from the sentence plus the previous line (or a resolved form), not the sentence alone. | Sec 7.2, Table 5, p.8824 | Verifier | Sentence "It was finished in 1962." is retrieved with the previous line about the Varne dam, and the dam passage is found. | The query is only "It was finished in 1962." and BM25 returns a passage about a bridge. |
| Most generated sentences are correct, so a checker must keep false flags low while catching subtle errors. Treat the false-flag rate as a first-class pass threshold. | Sec 1, p.8818-8819 | Evaluation | Eval fails a Verifier change that raises detection by one point but doubles false flags. | Eval accepts any change that raises detection. |
| Scoring chunk by chunk and taking the best chunk cannot combine evidence that sits in two chunks. When a local checker is used, give it the cited passages joined as one document where they fit. | Sec 2 (max over documents), p.8820; App E.2 | Verifier | Cited chunks 3 and 4 are joined and scored together for a sentence that needs both. | Chunks 3 and 4 are scored separately; each scores low; a correct sentence is flagged. |
| Use a fixed midpoint threshold (0.5) for a local checker's support probability; the scores cluster near 0 and 1, and per-dataset tuning changed little. Tune only on a validation split if ever. | Sec 4.1 (validation and threshold), p.8822-8823; App B.1 | Evaluation, Verifier | Local score 0.97: passes; 0.02: flagged; threshold read from config. | Threshold hand-set to 0.31 after looking at the reported test items. |
| Real model errors differ from planted ones; the authors excluded datasets with instructed, artificial errors. Keep a second eval set of real Writer output, labelled by hand, next to the seeded set. | Sec 4, p.8822; App C.3 | Evaluation | Eval runs on the seeded set and on 40 hand-labelled sentences from actual sessions. | All eval items are hand-planted single-word swaps. |
| When several sentences share one document, one call that labels all of them performed about as well as one call per sentence, at under half the cost. Keep batching sentences that share passages. | App B.4, Table 10 | Verifier | One Verifier call labels a segment's twelve sentences against their shared passages. | Twelve separate calls with the same passages. |
| A local checker can only be a second opinion in groundcast: it outputs a binary supported score, so it cannot say contradicted versus unsupported, framing, or no claim, and it ignores the previous line. Let it add flags to sentences the LLM Verifier passed; never let it clear an LLM flag. | Sec 2 (problem setup, binary labels), p.8819-8820 | Verifier | LLM says supported, local score 0.04: the sentence is re-checked or flagged. | LLM says unsupported, local score 0.92: the sentence is passed. |

## Not adopted

- Training our own checker on C2D and D2C synthetic data: groundcast does not
  train models; the released checkpoints are enough to test.
- Decontextualization as a separate LLM step: the judge did not need it; only
  the retrieval point is kept.
- LLM-AggreFact as groundcast's eval set: its documents are news, dialogue,
  and web text under various terms; groundcast eval material must be
  self-written or openly licensed.
- Replacing the LLM Verifier with a local checker: the binary label loses the
  distinctions groundcast needs (see the last rule), and the models are
  English only (Limitations).
- Bespoke-MiniCheck-7B for local use: see the table below.

## Released checkpoints and local use

Checked on 2026-10-12 from the Hugging Face API records
(`/api/models/<id>`), the model cards, and the reference code. Parameter
counts are from the paper (Table 3) or the API; file sizes are the weight
files in the repositories.

| Checkpoint | Backbone | Parameters | Weights on the Hub | Licence | Max input in reference code | Paper result (mean BAcc, LLM-AggreFact test, Table 2) | Fits RTX 3070 8 GB |
|---|---|---|---|---|---|---|---|
| lytang/MiniCheck-Flan-T5-Large (revision 96eafd01cee2d16cf81aaa2fb226b14f422a37b3) | google/flan-t5-large (Apache-2.0) | 770M (card: 0.8B) | pytorch_model.bin, 3.13 GB (fp32) | MIT (API license tag and card front matter) | 2048 tokens; document chunks of about 500 whitespace words | 74.7 (GPT-4: 75.3) | Yes: about 1.6 GB in bf16, which sm_86 supports |
| lytang/MiniCheck-RoBERTa-Large (revision 74c8919647e61ed0f71bc177d94f10930f090068) | AlignScore RoBERTa-large (MIT) | 355M (card: 0.4B) | pytorch_model.bin, 1.42 GB (fp32) | MIT | 512 tokens; chunks of about 400 tokens | 72.7 | Yes, but the 512-token limit leaves little room per chunk |
| lytang/MiniCheck-DeBERTa-v3-Large (revision 2f2d01a54fa022a7ffadb76260e1ea8bc88c82bb) | microsoft/deberta-v3-large (MIT) | 355M per paper (card: 0.4B) | pytorch_model.bin, 1.74 GB (fp32) | MIT | 2048 tokens; chunks of about 400 tokens | 72.6 | Yes |
| bespokelabs/Bespoke-MiniCheck-7B (revision 1ed7786bcda3fa1dc35f7c4ed9e3f36b785d33b8) | internlm/internlm2_5-7b-chat (licence: other) | 7.74B (BF16, API) | 4 safetensors shards, 15.5 GB (bf16) | CC BY-NC 4.0 (License.md and card; the API record has no license tag) | 32768 tokens; chunk default 32768 minus 300 | Not in the paper (released later) | No: weights alone are about 15.5 GB; would need untested 4-bit quantization, and the reference code runs it through vLLM |

Input format and scoring, from the reference code:

- Input is one document (plain text) and one claim. The document is split
  into sentences, which are packed into chunks of the sizes above. Each
  (chunk, claim) pair is scored on its own, and the claim's score is the
  highest chunk score.
- Flan-T5: the input is a fixed task prefix, the chunk, an end-of-sequence
  token, then the claim; the score is the softmax probability of the
  supported label token against the unsupported one, read from the first
  decoder step. RoBERTa and DeBERTa: chunk and claim joined by the
  end-of-sequence token into a two-class classifier; the score is the
  softmax probability of class 1.
- 7B model: a chat prompt holding the chunk and claim; the score is the
  probability of a yes first token. A multi-sentence claim is split into
  sentences; the final score is the lowest, over sentences, of the highest
  chunk score.
- All four: the label is supported when the score is above 0.5; no
  per-dataset threshold (paper Sec 4.1).

Notes for a decision (not legal advice):

- The three lytang models carry MIT on the Hub, but their fine-tuning data
  included 21K ANLI examples (ANLI's own repository states CC BY-NC 4.0) and
  GPT-4-generated synthetic data. For a local, personal tool this is not a
  barrier; record it if groundcast's use ever changes.
- The reference inference code (github.com/Liyan06/MiniCheck) is
  Apache-2.0 per the GitHub API record. groundcast would not need it: the
  small models load with plain `transformers` using the input format above.
- The three small models ship as pickled `pytorch_model.bin`. Pin the
  revision hash and load with weights-only loading (the default in torch
  2.6 and later), or convert to safetensors once and keep the result.
- The reference package now also offers an IBM Granite Guardian 8B option;
  it is outside the paper and was not assessed here.
- Candidate for groundcast: MiniCheck-Flan-T5-Large as an optional local
  second opinion (see the last candidate rule), behind a config switch, kept
  only if `groundcast eval` shows added detection at an acceptable
  false-flag rate.
