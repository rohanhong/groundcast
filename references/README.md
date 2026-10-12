# References

Local library of the sources used to distil groundcast's prompts and rubric:
papers, books and book notes, podcast transcripts, broadcast-writing guides,
archived tutorial pages, and read-only copies of external repositories.

Everything in this directory except this README and `.gitignore` is ignored by
git and stays on your machine. Nothing here is imported, built, or sent to a
model. The rules distilled from these sources, written in our own words, live
in [`docs/distillation/`](../docs/distillation/README.md).

What does not belong here:

- Your own study materials: they are user data and go into the data directory
  (`GROUNDCAST_DATA_DIR`) through the app.
- Test and evaluation materials: they must be self-written or openly licensed
  and live in `tests/fixtures/` and `evals/`.

## Adding a source

1. Save the file here, named after its ID, for example `S07-npr-campfire-tales.pdf`.
   For a repository, clone it into a directory named after its ID.
2. Fill in the `Local file` cell below (for a repository, also the commit hash
   and the date in `Notes`).
3. A new source gets the next free ID and a row in the matching table.

## Sources in use

Tiers: T1 learning research; T2 writing for the ear (broadcast and radio
guidance); T3 educational podcasts, used for structure only; T4 fact-checking
and claim-verification research. Access: free, paywall, or book.

| ID | Tier | Source | Access | Used for | Local file |
|---|---|---|---|---|---|
| S1 | T1 | Mayer, R.E. *Multimedia Learning*, 3rd ed. Cambridge University Press, 2021. doi:10.1017/9781316941355 | book | Modality, redundancy, signalling, segmenting, personalisation | none (book; see S25) |
| S3 | T1 | Dunlosky, J. et al. 2013. Improving Students' Learning With Effective Learning Techniques. *Psychological Science in the Public Interest* 14(1), 4-58. doi:10.1177/1529100612453266 | free | Practice testing and spacing: quiz and recap design | `S03-dunlosky-2013.pdf` |
| S5 | T1 | Sweller, J., van Merrienboer, J.J.G. and Paas, F. 2019. Cognitive Architecture and Instructional Design: 20 Years Later. *Educational Psychology Review* 31(2), 261-292. doi:10.1007/s10648-019-09465-5 | free | Transient information effect: short units and recaps in audio | `S05-sweller-2019.pdf` |
| S6 | T2 | Socolovsky, J. *Sound Reporting*, 2nd ed. University of Chicago Press, 2024 | book | Broadcast and podcast writing craft | none (book; S7 quotes its first edition) |
| S7 | T2 | NPR Training pages: "Campfire tales: The essentials of writing for radio"; "'Would you say it that way?' Tips on writing for your voice"; "Writing through sound"; "Steve Inskeep: Three songs that will change how you write for radio" | free | One idea per sentence, attribution first, signposting, reading aloud | `S07-npr-campfire-tales.html`, `S07-npr-would-you-say-it.html`, `S07-npr-writing-through-sound.html`, `S07-npr-inskeep-three-songs.html` |
| S9 | T2 | Abel, J. 2015. *Out on the Wire: The Storytelling Secrets of the New Masters of Radio*. Broadway Books | book | Narrative structure | none (book; see S26) |
| S11 | T3 | In Our Time (BBC Radio 4) | free (audio) | Academic discussion format; structure only | none (no official transcripts) |
| S13 | T3 | Hidden Brain (Hidden Brain Media) | free (audio, most transcripts) | Single host, narration plus interview; structure only | `S13-hidden-brain-why-conversations-go-wrong.html`, `S13-hidden-brain-what-art-does-for-your-brain.html` |
| S14 | T3 | Science Vs (Spotify Studios) | free (transcripts with citations) | Evidence-checking format; structure only | `S14-science-vs-collagen.html`, `S14-science-vs-stress.html`, `S14-science-vs-insect-apocalypse.html` |
| S15 | T3 | Philosophize This! (Stephen West) | free (episode text) | Single-narrator scripted explainer; structure only | `S15-philosophize-this-ep001.html`, `S15-philosophize-this-descartes-pt1.html`, `S15-philosophize-this-ep145.html` |
| S17 | T4 | Min, S. et al. 2023. FActScore. EMNLP 2023, 12076-12100. doi:10.18653/v1/2023.emnlp-main.741 | free | Splitting a script into atomic claims | `S17-factscore.pdf` |
| S19 | T4 | Laban, P. et al. 2022. SummaC. TACL 10, 163-177. doi:10.1162/tacl_a_00453 | free | Sentence-level consistency of script versus notes | `S19-summac.pdf` |
| S20 | T4 | Thorne, J. et al. 2018. FEVER. NAACL-HLT 2018, 809-819. doi:10.18653/v1/N18-1074 | free | Supported / refuted / not-enough-info labels | `S20-fever.pdf` |
| S22 | T4 | Manakul, P. et al. 2023. SelfCheckGPT. EMNLP 2023, 9004-9017. doi:10.18653/v1/2023.emnlp-main.557 | free | Checks without a source text (Q&A answers) | `S22-selfcheckgpt.pdf` |
| S23 | T4 | Tang, L., Laban, P. and Durrett, G. 2024. MiniCheck. EMNLP 2024, 8818-8847. doi:10.18653/v1/2024.emnlp-main.499 | free, models released | Low-cost claim checking against documents | `S23-minicheck.pdf` |
| S18 | T4 | Wei, J. et al. 2024. Long-form factuality in large language models (SAFE). NeurIPS 37, 80756-80827. doi:10.52202/079017-2567 | free | Per-claim checking with search; evidence count versus accuracy | `S18-safe.pdf` |
| S21 | T4 | Es, S. et al. 2024. RAGAs. EACL 2024 Demos, 150-158. doi:10.18653/v1/2024.eacl-demo.16 | free | Faithfulness of answers to retrieved context (Q&A) | `S21-ragas.pdf` |
| S24 | T4 | Jacovi, A. et al. 2025. The FACTS Grounding Leaderboard. arXiv:2501.03200 | free | Judging grounding sentence by sentence, never as a whole | `S24-facts-grounding.pdf` |
| S25 | T1 | Mayer, R.E. 2024. The Past, Present, and Future of the Cognitive Theory of Multimedia Learning. *Educational Psychology Review* 36, article 8. doi:10.1007/s10648-023-09842-1 (open access, CC BY 4.0) | free | Stands in for S1: the fifteen principles of Mayer 2021 | `S25-mayer-2024.pdf` |
| S26 | T2 | Dahlstrom, M.F. 2014. Using narratives and storytelling to communicate science with nonexpert audiences. *PNAS* 111(Suppl. 4), 13614-13620. doi:10.1073/pnas.1320645111 | free | Stands in for S9: narrative and examples in science communication | `S26-dahlstrom-2014.html` (PubMed Central PMC4183170) |

## Other sources (not held)

| ID | Tier | Source | Access |
|---|---|---|---|
| S2 | T1 | Clark, R.C. and Mayer, R.E. *e-Learning and the Science of Instruction*, 5th ed. Wiley, 2024 | book |
| S4 | T1 | Roediger, H.L. III and Karpicke, J.D. 2006. Test-Enhanced Learning. *Psychological Science* 17(3), 249-255. doi:10.1111/j.1467-9280.2006.01693.x | paywall |
| S8 | T2 | BBC Academy "Writing radio cues" and BBC News style guide | free, not checked first-hand |
| S10 | T2 | Biewen, J. and Dilworth, A. (eds) 2017. *Reality Radio*, 2nd ed. UNC Press | book |
| S12 | T3 | Radiolab (WNYC Studios) | free (partial transcripts) |
| S16 | T3 | History of Philosophy without any gaps (Peter Adamson) | free (audio) |
