"""Command line: serve the app, ingest files, run a session, run evaluations."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from groundcast.config import config_file_path, load_settings


def _settings(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    return load_settings(Path(args.config) if args.config else None)


def cmd_paths(args: argparse.Namespace) -> int:
    settings = _settings(args)
    config = config_file_path(args.config)
    print(f"config file : {config} ({'found' if config.is_file() else 'not found; defaults apply'})")
    print(f"data dir    : {settings.data_dir}")
    print(f"model dir   : {settings.model_dir}")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    from groundcast.install import run_setup

    settings = _settings(args)
    args.llm = settings.llm
    return run_setup(args, out=lambda line: print(line, flush=True))


def cmd_doctor(args: argparse.Namespace) -> int:
    from groundcast.doctor import failed, format_checks, run_checks

    checks = run_checks(_settings(args), config_file_path(args.config))
    print(format_checks(checks))
    if failed(checks):
        print("Some required parts are missing; run the fix shown for each.")
        return 1
    print("Ready: run `groundcast serve`.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from groundcast.launcher import make_server, server_url
    from groundcast.web.app import create_app

    settings = _settings(args)
    print(f"Data directory: {settings.data_dir}")
    print(f"Open {server_url(settings)}")
    make_server(settings, create_app(settings)).run()
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    from groundcast.launcher import launch

    return launch(_settings(args), window=args.window)


def cmd_shortcut(args: argparse.Namespace) -> int:
    from groundcast.shortcuts import make_shortcuts

    try:
        paths = make_shortcuts(_settings(args), desktop=args.desktop, remove=args.remove, config=args.config)
    except OSError as exc:
        print(exc)
        return 1
    verb = "Removed" if args.remove else "Made"
    print("\n".join(f"{verb} {p}" for p in paths) or "No shortcuts to remove.")
    return 0


def _material_line(m) -> str:  # type: ignore[no-untyped-def]
    status = "" if m.status == "ready" else f"  [{m.status}{': ' + m.error if m.error else ''}]"
    return f"{m.id}  {m.filename}  {m.kind}, {m.pages} unit(s), {m.words} words{status}"


def cmd_ingest(args: argparse.Namespace) -> int:
    from groundcast.ingest import ExtractionError, ingest_file, ingest_url, recognise_material
    from groundcast.storage import Store

    settings = _settings(args)
    store = Store(settings.data_dir)
    failed = 0
    for name in args.files + args.url:
        try:
            if name in args.url:
                m = ingest_url(name, store, settings)
            else:
                m = ingest_file(Path(name), store, settings, defer=True)
                if m.status in ("processing", "failed"):  # a failed recognition is tried again
                    m = recognise_material(store, settings, m.id, progress=lambda msg: print(msg, end="\r"))
                    print()
        except ExtractionError as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            failed += 1
            continue
        print(_material_line(m))
        if m.status == "review":
            print(f"  Check the recognised text, then confirm it: groundcast review {m.id} (or in the web app)")
    return 1 if failed else 0


def cmd_materials(args: argparse.Namespace) -> int:
    from groundcast.storage import Store

    for m in Store(_settings(args).data_dir).list_materials():
        print(_material_line(m))
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    from groundcast.ingest import review_material
    from groundcast.material_view import place
    from groundcast.storage import Store

    settings = _settings(args)
    store = Store(settings.data_dir)
    material = store.get_material(args.material)
    if not args.confirm:
        media = material.kind in ("video", "audio")
        threshold = settings.asr.review_below if media else settings.ocr.review_below
        for c in store.get_chunks(material.id):
            if c.confidence is None:
                continue  # not recognised: a PDF page with a text layer
            low = c.confidence < threshold
            flag = f"  <- low confidence {c.confidence:.2f}" if low else ""
            check = f"  check: {', '.join(c.uncertain)}" if c.uncertain else ""
            print(f"[{c.id}] {place(c.locator, material)}{flag}{check}\n{c.text}\n")
        print(f"{material.filename} is {material.status}. Correct passages in the web app, or confirm with --confirm.")
        return 0
    material = review_material(store, material.id, {})
    print(f"{material.filename} is ready for sessions.")
    return 0


def cmd_session(args: argparse.Namespace) -> int:
    from groundcast.models import Brief, SessionStatus
    from groundcast.sessions import run_session, new_session
    from groundcast.storage import Store

    settings = _settings(args)
    store = Store(settings.data_dir)
    brief = Brief(
        title=args.title,
        focus=args.focus,
        material_ids=args.material,
        minutes=args.minutes,
        context=args.context,
        level=args.level,
        format=args.format,
        recall_prompts=args.recall,
        notes=args.notes,
    )
    record = new_session(store, brief)
    print(f"Session {record.id}")
    record = run_session(record, store, settings, on_update=lambda r: print(r.log[-1]))
    print(f"Files: {store.session_dir(record.id)}")
    return 0 if record.status == SessionStatus.DONE else 1


def cmd_ask(args: argparse.Namespace) -> int:
    from groundcast.llm import make_backend, roles
    from groundcast.models import SessionStatus
    from groundcast.qa import answer_question, load_history, save_history
    from groundcast.storage import Store

    settings = _settings(args)
    store = Store(settings.data_dir)
    record = store.get_session(args.session)
    if record.status != SessionStatus.DONE:
        raise SystemExit(f"session {record.id} is {record.status.value}; questions open once it is done")
    materials = {m: store.get_material(m) for m in record.brief.material_ids}
    chunks = [c for m in record.brief.material_ids for c in store.get_chunks(m)]
    history = load_history(store, record.id)
    exchange = answer_question(
        make_backend(settings.llm), roles(settings.llm), settings, chunks, materials, args.question, history.exchanges
    )
    history.exchanges.append(exchange)
    save_history(store, record.id, history)
    numbers = {s.chunk_id: n for n, s in enumerate(exchange.sources, start=1)}
    if not exchange.covered:
        print("(Your materials do not answer this.)")
    for s in exchange.sentences:
        refs = "".join(f"[{numbers[c]}]" for c in s.sources)
        warning = "" if s.verified else f"  <- not verified against your materials ({s.label})"
        print(f"{s.text}{refs}{warning}")
    for src in exchange.sources:
        print(f"[{numbers[src.chunk_id]}] {src.label}")
    return 0


def cmd_quiz(args: argparse.Namespace) -> int:
    from groundcast.llm import make_backend, roles
    from groundcast.models import Script, SessionStatus
    from groundcast.profile.concepts import list_concepts
    from groundcast.profile.db import ProfileDB
    from groundcast.quiz import load_quizzes, make_quiz, save_quizzes
    from groundcast.sessions import SCRIPT_FILE
    from groundcast.storage import Store, read_model

    settings = _settings(args)
    store = Store(settings.data_dir)
    record = store.get_session(args.session)
    if record.status != SessionStatus.DONE:
        raise SystemExit(f"session {record.id} is {record.status.value}; quizzes open once it is done")
    materials = {m: store.get_material(m) for m in record.brief.material_ids}
    chunks = [c for m in record.brief.material_ids for c in store.get_chunks(m)]
    script = read_model(store.session_dir(record.id) / SCRIPT_FILE, Script)
    concepts = list_concepts(ProfileDB(settings.data_dir), record.brief.material_ids)
    quiz = make_quiz(make_backend(settings.llm), roles(settings.llm), settings, script, chunks, materials, concepts)
    data = load_quizzes(store, record.id)
    data.quizzes.append(quiz)
    save_quizzes(store, record.id, data)
    print(f"Quiz {quiz.id}: {len(quiz.questions)} question(s), {quiz.dropped} dropped by the check")
    for n, q in enumerate(quiz.questions, start=1):
        tags = f"; concepts: {', '.join(q.concepts)}" if q.concepts else ""
        print(f"\n{n}. {q.question}  ({q.topic}{tags})")
        for m, option in enumerate(q.options):
            print(f"   {'*' if m == q.correct else ' '} {chr(65 + m)}. {option}")
        print(f"   {q.explanation} [{'; '.join(s.label for s in q.sources)}]")
    return 0


def cmd_concepts(args: argparse.Namespace) -> int:
    from groundcast.profile.concepts import list_concepts
    from groundcast.profile.db import ProfileDB
    from groundcast.storage import Store

    settings = _settings(args)
    db = ProfileDB(settings.data_dir)
    if args.extract:
        from groundcast.llm import make_backend, roles
        from groundcast.profile.extract import extract_concepts

        store = Store(settings.data_dir)
        material = store.get_material(args.extract)
        n = extract_concepts(make_backend(settings.llm), roles(settings.llm)["concepts"], settings, db, material,
                             store.get_chunks(material.id))  # fmt: skip
        print(f"{material.filename}: linked to {n} concepts")
    for c in list_concepts(db):
        quiz = f", quiz {c.right}/{c.asked}" if c.asked else ""
        print(f"{c.id}  {c.name}  ({c.chunks} passage(s) in {len(c.material_ids)} material(s){quiz})")
    return 0


def cmd_prefs(args: argparse.Namespace) -> int:
    import json

    from groundcast.profile.db import ProfileDB
    from groundcast.profile.preferences import effective, load_preferences, set_preferences

    settings = _settings(args)
    db = ProfileDB(settings.data_dir)
    changes: dict[str, object] = {key: None for key in args.clear}
    for item in args.set:
        key, sep, value = item.partition("=")
        if not sep:
            raise SystemExit(f"--set needs KEY=VALUE, got {item!r}")
        try:
            changes[key] = json.loads(value)
        except json.JSONDecodeError:
            changes[key] = value  # a plain string, such as a voice name
    if changes:
        try:
            set_preferences(db, settings, changes)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    prefs = load_preferences(db)
    for key, value in effective(settings, prefs).items():
        source = "set" if getattr(prefs, key) is not None else "default"
        print(f"{key} = {json.dumps(value)}  ({source})")
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    from groundcast.profile.db import ProfileDB
    from groundcast.profile.feedback import Feedback, get_feedback, set_feedback
    from groundcast.storage import Store

    settings = _settings(args)
    record = Store(settings.data_dir).get_session(args.session)
    db = ProfileDB(settings.data_dir)
    if args.rating is not None or args.length or args.comment is not None:
        old = get_feedback(db, record.id)
        fb = Feedback(
            rating=args.rating if args.rating is not None else (old.rating if old else None),
            length=args.length or (old.length if old else None),
            comment=args.comment if args.comment is not None else (old.comment if old else ""),
        )
        set_feedback(db, record.id, fb)
    current = get_feedback(db, record.id)
    print(current.model_dump_json(indent=1) if current else "No feedback on this session yet.")
    return 0


def cmd_suggest(args: argparse.Namespace) -> int:
    from groundcast.profile.db import ProfileDB
    from groundcast.profile.suggest import suggest
    from groundcast.storage import Store

    settings = _settings(args)
    store = Store(settings.data_dir)
    view = suggest(ProfileDB(settings.data_dir), settings, store.list_materials(), store.list_sessions())
    for n, s in enumerate(view.suggestions, start=1):
        b = s.brief
        print(f"{n}. {s.title}\n   {b.minutes} min, {b.format}, {b.context}, {b.level}, recall {b.recall_prompts}; "
              f"materials {', '.join(b.material_ids)}")  # fmt: skip
        for line in s.why:
            print(f"   - {line}")
    if not view.suggestions:
        print("No suggestions yet: add materials first.")
    print("Learned from your sessions:" if view.inference_on else "Learning from sessions is switched off.")
    for i in view.inferred:
        state = "used" if i.applied else "not yet used"
        print(f"  {i.key} = {i.value!r} (confidence {i.confidence:.2f}, {i.sessions} of {i.of_sessions}; {state})")
    a = view.acceptance
    rate = "-" if a.rate is None else f"{a.rate:.2f}"
    print(f"Suggestions accepted without edits: {a.accepted} of {a.accepted + a.edited} ({rate})")
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    import json

    from groundcast.profile.db import ProfileDB
    from groundcast.profile.preferences import delete_profile, export_profile

    db = ProfileDB(_settings(args).data_dir)
    if args.export:
        Path(args.export).write_text(json.dumps(export_profile(db), indent=1), encoding="utf-8")
        print(f"Exported the profile to {args.export}")
    if args.delete:
        if input("Delete the whole profile (preferences, concepts, quiz results, log)? Type yes: ") != "yes":
            raise SystemExit("Not deleted.")
        delete_profile(db)
        print("Profile deleted.")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from groundcast.evaluation.seeded import format_report, run_seeded, save_report, threshold_failures
    from groundcast.llm import make_backend

    settings = _settings(args)
    set_path = Path(args.set) if args.set else _default_eval_set()
    report = run_seeded(set_path, settings, make_backend(settings.llm), args.runs)
    out = Path(args.out) if args.out else settings.data_dir / "evals" / f"seeded-{datetime.now():%Y%m%d-%H%M%S}.json"
    save_report(report, out)
    print(format_report(report))
    print(f"Report: {out}")
    failures = threshold_failures(report, settings.evaluation)
    for failure in failures:
        print(f"FAIL: {failure}")
    print("Thresholds: " + ("not met" if failures else "met"))
    return 1 if failures else 0


def cmd_eval_quality(args: argparse.Namespace) -> int:
    from groundcast.evaluation.quality import format_quality, run_quality, save_quality
    from groundcast.llm import make_backend

    settings = _settings(args)
    set_path = Path(args.set) if args.set else _default_eval_set("quality", "briefs.json")
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    out = Path(args.out) if args.out else settings.data_dir / "evals" / f"quality-{stamp}.json"
    report = run_quality(set_path, settings, make_backend(settings.llm), args.judge_runs, out.with_suffix(""),
                         generations=args.generations)  # fmt: skip
    save_quality(report, out)
    print(format_quality(report))
    print(f"Report: {out} (scripts in {out.with_suffix('')})")
    return 0


def _default_eval_set(*parts: str) -> Path:
    """An evaluation set under evals/ in the working directory or the source checkout."""
    relative = Path("evals").joinpath(*(parts or ("seeded", "items.json")))
    checkout = Path(__file__).resolve().parents[2]
    for base in (Path.cwd(), checkout):
        if (base / relative).is_file():
            return base / relative
    raise SystemExit(f"evaluation set not found: {relative}; pass --set <file>")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="groundcast", description=__doc__)
    parser.add_argument("--config", help="TOML settings file (default: GROUNDCAST_CONFIG or the per-user config file)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log debug output")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("paths", help="show the config file, data, and model paths").set_defaults(func=cmd_paths)
    sub.add_parser("serve", help="run the local web app").set_defaults(func=cmd_serve)

    p = sub.add_parser("launch", help="start the app if needed and open its window; what the shortcut runs")
    p.add_argument("--window", choices=["app", "browser", "none"], help="override launcher.window")
    p.set_defaults(func=cmd_launch)

    p = sub.add_parser("shortcut", help="make desktop and menu shortcuts that start groundcast")
    p.add_argument("--no-desktop", dest="desktop", action="store_false", help="only the Start or applications menu")
    p.add_argument("--remove", action="store_true", help="remove the shortcuts instead")
    p.set_defaults(func=cmd_shortcut)

    p = sub.add_parser("setup", help="install the optional parts: PyTorch build, speech recognition, Piper, API")
    p.add_argument("--yes", "-y", action="store_true", help="take every recommendation without asking")
    p.add_argument("--dry-run", action="store_true", help="show the pip commands without running them")
    p.add_argument("--torch", metavar="BUILD", help="PyTorch build from install.toml (for example cu130 or cpu), or keep")
    for key, what in (("asr", "speech recognition for video and audio"), ("piper", "the Piper fallback voices"),
                      ("api", "the Anthropic API backend")):  # fmt: skip
        p.add_argument(f"--{key}", action=argparse.BooleanOptionalAction, help=f"add {what} (or not)")
    p.add_argument("--shortcut", action=argparse.BooleanOptionalAction,
                   help="make desktop and menu shortcuts at the end (or not)")
    p.set_defaults(func=cmd_setup)

    sub.add_parser("doctor", help="check the installation and show how to fix what is missing").set_defaults(
        func=cmd_doctor)

    p = sub.add_parser("ingest", help="add material files or web pages to the data directory")
    p.add_argument("files", nargs="*", help="PDF, PowerPoint, Word, Markdown, text, HTML, video, or audio files")
    p.add_argument("--url", action="append", default=[], help="a web page to fetch (repeatable)")
    p.set_defaults(func=cmd_ingest)

    sub.add_parser("materials", help="list materials").set_defaults(func=cmd_materials)

    p = sub.add_parser("review", help="show the recognised text of a material (speech or OCR); --confirm accepts it")
    p.add_argument("material", help="material ID")
    p.add_argument("--confirm", action="store_true", help="mark the text as checked, so sessions may use it")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("session", help="produce one session from the command line")
    p.add_argument("--material", "-m", action="append", required=True, help="material ID (repeatable)")
    p.add_argument("--focus", required=True)
    p.add_argument("--title", default="")
    p.add_argument("--minutes", type=int, default=10)
    p.add_argument("--context", default="commute", choices=["desk", "commute", "exercise", "revision"])
    p.add_argument("--level", default="introductory", choices=["introductory", "intermediate", "advanced"])
    p.add_argument("--format", default="narrator", choices=["narrator", "two_hosts"])
    p.add_argument("--recall", action="store_true", help="end with recall questions, each followed by a pause")
    p.add_argument("--notes", default="")
    p.set_defaults(func=cmd_session)

    p = sub.add_parser("ask", help="ask a question about a finished session, answered from its materials")
    p.add_argument("session", help="session ID")
    p.add_argument("question")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("quiz", help="write a quiz on a finished session and print it with its answers")
    p.add_argument("session", help="session ID")
    p.set_defaults(func=cmd_quiz)

    p = sub.add_parser("concepts", help="list the concept table; --extract finds a material's concepts first")
    p.add_argument("--extract", metavar="MATERIAL_ID", help="extract this material's concepts now")
    p.set_defaults(func=cmd_concepts)

    p = sub.add_parser("prefs", help="show preferences; --set and --clear change them")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="for example speed=1.1")
    p.add_argument("--clear", action="append", default=[], metavar="KEY", help="go back to the configured default")
    p.set_defaults(func=cmd_prefs)

    p = sub.add_parser("feedback", help="rate a session and say if it was too short or too long")
    p.add_argument("session", help="session ID")
    p.add_argument("--rating", type=int, choices=range(1, 6), help="1 to 5")
    p.add_argument("--length", choices=["too_short", "right", "too_long"])
    p.add_argument("--comment")
    p.set_defaults(func=cmd_feedback)

    p = sub.add_parser("suggest", help="show ranked session suggestions and what was learned from past sessions")
    p.set_defaults(func=cmd_suggest)

    p = sub.add_parser("profile", help="export or delete the whole profile")
    p.add_argument("--export", metavar="FILE", help="write every profile table to a JSON file")
    p.add_argument("--delete", action="store_true", help="delete the whole profile, after a confirmation")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("eval", help="run the seeded-error test of the Verifier")
    p.add_argument("--set", help="evaluation set file (default: evals/seeded/items.json in the repository)")
    p.add_argument("--runs", type=int, default=3, help="repeat runs to average out noise")
    p.add_argument("--out", help="report path (default: <data dir>/evals/)")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("eval-quality", help="write scripts for fixed briefs and score them with the LLM judge")
    p.add_argument("--set", help="brief set file (default: evals/quality/briefs.json in the repository)")
    p.add_argument("--judge-runs", type=int, default=3, help="judging runs per script, averaged")
    p.add_argument("--generations", type=int, default=1, help="scripts written per brief, averaged")
    p.add_argument("--out", help="report path (default: <data dir>/evals/); scripts go next to it")
    p.set_defaults(func=cmd_eval_quality)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
