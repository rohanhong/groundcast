# S18 Long-form factuality (SAFE)

- Source: Wei, J. et al. 2024. Long-form factuality in large language models (SAFE). NeurIPS 37. doi:10.52202/079017-2567 (read as arXiv:2403.18802v4)
- Read: 2026-10-12, sections 1 to 9, appendices A.1 to A.7 (labels, failure
  causes, recall, postamble), C.1 to C.10 (implementation, failed ratings,
  splitting quality, query diversity, search scope and hyperparameter
  ablations, open model comparison, professional domains), and D.1 to D.2.

Locators are section and appendix numbers of the arXiv version.

## Candidate rules

| Rule (our words) | Locator | Role | Pass example (ours) | Fail example (ours) |
|---|---|---|---|---|
| Before judging a sentence that leans on the line before it, resolve every reference (it, this, they, the same) to the full thing it names, and keep every specific in the resolved form. A rewrite that drops a name or number was a distinct cause of wrong verdicts. | Sec 3; App A.3, Fig 7; App C.3, Table 21 | Verifier | Previous: "The Ostra feeds Lake Varne." Sentence: "It rises in the Kell Hills." Judged as: the Ostra rises in the Kell Hills. | Judged as: a river rises in the Kell Hills. The name is lost, so any passage about any river seems to support it. |
| Word verdicts as relative to the learner's materials: supported or not supported by them, never true or false. A fact can be true and still absent from the notes. | App A.2; Sec 8 | Verifier, Tutor | Warning shown to the learner: "This is not in your materials." | Warning shown: "This is false." The fact is correct, it is just not in the notes. |
| Keep the label set small and give each label a decision test; measure confusions between labels, not only the pass or fail outcome. Over a third of human rating errors came from mixing up two neighbouring labels. | App A.4, Fig 8 | Evaluation | Eval report includes a confusion table (expected label by given label), so a rise in no_claim given to claims is visible. | Report gives only detection and false-flag rates; a Verifier that calls factual questions no_claim looks fine. |
| Give the checker a few relevant evidence pieces, not as many as possible. Three results per query beat both fewer and more; extra text lowered agreement with humans. Tune the Verifier's retrieved-passage count with the eval. | App C.8, Fig 13 | Evaluation, Verifier | Eval runs with two, four, and eight retrieved passages; the setting with the best detection at an acceptable false-flag rate is kept in config. | Verifier always receives the whole document on the theory that more context cannot hurt. |
| Compound sentences in dense subjects (law, medicine) caused most rating failures through bad splitting and bad reference resolution, not through bad judging. Keep script claims to one fact per sentence so the Verifier never has to split. | App C.10 | Writer | "The permit lasts two years. It can be renewed once." | "The permit, which lasts two years unless the holder, having applied before expiry, renews it once, covers fishing." |
| Asking for many specific details (names, numbers, dates) raised the amount said but lowered precision. When the brief asks for depth, the Writer adds detail only where the passages give it, and the eval should weight seeded errors toward such specifics. | App A.7, Fig 10 | Writer, Evaluation | Brief asks for detail; the script gives the two dates the notes state and nothing more precise. | Script adds an exact hour and a named engineer to sound thorough; neither is in the notes. |
| A coverage metric must count each distinct fact once. Recaps repeat key points on purpose, so deduplicate before counting what the script covered. | Sec 8; App D.1 | Evaluation | Coverage counts "Varne is fed by the Ostra" once, though the segment recap repeats it. | Coverage counts it three times and rewards a script that recaps one fact and skips the rest. |
| Pair precision with recall against a target amount. A response with no errors but almost no content should not score as well as a full, correct one. | Sec 5, Eq 1; App A.6 | Evaluation | Session score combines the share of supported claims with how many of the brief's key points were covered. | Session score is the share of supported claims only; a two-sentence script scores 100 percent. |

## Not adopted

- Google Search as the knowledge source and the multi-step query agent:
  groundcast grounds only in the learner's materials and runs locally; web
  evidence would break the core guarantee.
- The relevance step as a separate label: groundcast's Writer stays on the
  brief, and off-topic content is an Editor concern.
- The K hyperparameter as the ideal number of facts: groundcast sizes scripts
  with its pacing model, so recall is measured against the brief's key
  points instead.
- LongFact prompts and the model benchmark: not applicable to grounded
  scripts.
- The claim that an LLM rater beats crowd raters: it holds against Wikipedia
  limited annotators in open-web factuality, not in our closed setting.
