"""MiniCheck as a local claim checker: the M4 evaluation (spec section 6).

Scores every item of the seeded set with MiniCheck-Flan-T5-Large (MIT;
Tang, Laban and Durrett 2024, source S23) as its reference code does: the
input is "predict: " + passage chunk + end of sequence + claim, the score is
the probability of token 209 (supported) against 3 (unsupported) at the
first decoder step, and the best chunk counts. It then combines MiniCheck's
flags with the LLM Verifier's labels saved in a `groundcast eval` report:
a sentence counts as flagged when either flags it.

Result on 2026-10-12 (118 items; LLM labels from 3 runs of the Verifier,
sonnet at medium effort, with retrieval_context on):

| Checker | Detection | False flags |
|---|---|---|
| LLM Verifier alone | 0.985 | 0.000 |
| MiniCheck alone, threshold 0.5 | 0.677 | 0.264 |
| LLM or MiniCheck, threshold 0.5 | 0.985 | 0.264 |
| LLM or MiniCheck, threshold 0.1, claim with previous line | 0.985 | 0.132 |

MiniCheck added no detection and many false flags, so it was not adopted,
neither as a second opinion nor as a first pass before Claude (it would let
a third of the seeded errors through). It needs packages groundcast does not
install: pip install transformers sentencepiece. The model (3.1 GB) goes to
the cache directory given on the command line.

usage: python evals/experiments/minicheck.py evals/seeded/items.json <eval report.json> <cache dir> <out.json>
"""

import json
import sys
import tempfile
import time
from pathlib import Path

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from groundcast.config import load_settings
from groundcast.evaluation.seeded import EvalSet, _flagged, resolve_quote
from groundcast.ingest import ingest_file
from groundcast.models import Label
from groundcast.pipeline.verifier import passages_for
from groundcast.retrieval import BM25Index
from groundcast.storage import Store

CKPT = "lytang/MiniCheck-Flan-T5-Large"
REVISION = "96eafd01cee2d16cf81aaa2fb226b14f422a37b3"
CHUNK_WORDS = 400  # the reference code packs sentences into about this many words

set_path, report_path, cache, out_path = map(Path, sys.argv[1:5])
settings = load_settings()
ev = EvalSet.model_validate_json(set_path.read_text(encoding="utf-8"))
with tempfile.TemporaryDirectory() as tmp:
    store = Store(Path(tmp))
    chunks = []
    for rel in ev.materials:
        chunks += store.get_chunks(ingest_file(set_path.parent / rel, store, settings).id)
index = BM25Index(chunks)
by_id = {c.id: c for c in chunks}

t0 = time.time()
tok = AutoTokenizer.from_pretrained(CKPT, revision=REVISION, cache_dir=str(cache))
model = AutoModelForSeq2SeqLM.from_pretrained(CKPT, revision=REVISION, cache_dir=str(cache),
                                              torch_dtype=torch.bfloat16).to("cuda").eval()
print(f"loaded in {time.time() - t0:.0f}s; VRAM {torch.cuda.memory_allocated() / 2**30:.2f} GB", flush=True)


def score(doc: str, claim: str) -> float:
    words = doc.split()
    docs = [" ".join(words[i:i + CHUNK_WORDS]) for i in range(0, len(words), CHUNK_WORDS)] or [""]
    texts = ["predict: " + tok.eos_token.join([d, claim]) for d in docs]
    inputs = tok(texts, max_length=2048, truncation=True, padding=True, return_tensors="pt").to("cuda")
    with torch.no_grad():
        dec = torch.zeros((inputs["input_ids"].size(0), 1), dtype=torch.long, device="cuda")
        logits = model(**inputs, decoder_input_ids=dec).logits.squeeze(1).float()
    probs = torch.softmax(logits[:, [3, 209]], dim=-1)[:, 1]
    return probs.max().item()


report = json.loads(report_path.read_text(encoding="utf-8"))
runs = len(next(iter(report["items"].values()))["labels"])
results = {}
t0 = time.time()
for item in ev.items:
    cited = [resolve_quote(item.quote, chunks)]
    passages = passages_for(item.text, cited, by_id, index, settings.pipeline.bm25_top_k, item.context)
    doc = "\n".join(p.text for p in passages)
    # The claim alone, as MiniCheck is trained, and with the previous line, for answers in dialogue.
    alone = score(doc, item.text)
    with_context = score(doc, f"{item.context} {item.text}".strip()) if item.context else alone
    results[item.id] = {"alone": alone, "with_context": with_context}
print(f"scored {len(ev.items)} items in {time.time() - t0:.1f}s", flush=True)

errors = [i for i in ev.items if _flagged(i.expected)]
correct = [i for i in ev.items if not _flagged(i.expected)]
summary = {}
for variant in ("alone", "with_context"):
    for threshold in (0.5, 0.3, 0.1):
        mc = {i.id: results[i.id][variant] < threshold for i in ev.items}
        det_mc = sum(mc[i.id] for i in errors) / len(errors)
        ff_mc = sum(mc[i.id] for i in correct) / len(correct)
        det_union, ff_union = [], []
        for r in range(runs):
            llm = {i.id: _flagged(Label(report["items"][i.id]["labels"][r])) for i in ev.items}
            det_union.append(sum(llm[i.id] or mc[i.id] for i in errors) / len(errors))
            ff_union.append(sum(llm[i.id] or mc[i.id] for i in correct) / len(correct))
        key = f"{variant}@{threshold}"
        summary[key] = {
            "minicheck_detection": round(det_mc, 3), "minicheck_false_flags": round(ff_mc, 3),
            "union_detection": round(sum(det_union) / runs, 3), "union_false_flags": round(sum(ff_union) / runs, 3),
        }
        print(key, summary[key])
llm_det = report["summary"]["detection_rate"]["mean"]
llm_ff = report["summary"]["false_flag_rate"]["mean"]
print(f"LLM Verifier alone: detection {llm_det:.3f}, false flags {llm_ff:.3f}")
out_path.write_text(json.dumps({"summary": summary, "items": results, "llm": [llm_det, llm_ff]}, indent=1))
