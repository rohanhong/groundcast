"""Command line: serve the app, ingest files, run a session, run evaluations."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from groundcast.config import CONFIG_ENV, default_config_path, load_settings


def _settings(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    return load_settings(Path(args.config) if args.config else None)


def cmd_paths(args: argparse.Namespace) -> int:
    import os

    settings = _settings(args)
    config = Path(args.config or os.environ.get(CONFIG_ENV) or default_config_path())
    print(f"config file : {config} ({'found' if config.is_file() else 'not found; defaults apply'})")
    print(f"data dir    : {settings.data_dir}")
    print(f"model dir   : {settings.model_dir}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from groundcast.web.app import create_app

    settings = _settings(args)
    print(f"Data directory: {settings.data_dir}")
    print(f"Open http://{settings.server.host}:{settings.server.port}/")
    uvicorn.run(create_app(settings), host=settings.server.host, port=settings.server.port, log_level="info")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from groundcast.ingest import ingest_file
    from groundcast.storage import Store

    settings = _settings(args)
    store = Store(settings.data_dir)
    for name in args.files:
        m = ingest_file(Path(name), store, settings)
        print(f"{m.id}  {m.filename}  {m.pages} page(s), {m.words} words")
    return 0


def cmd_materials(args: argparse.Namespace) -> int:
    from groundcast.storage import Store

    for m in Store(_settings(args).data_dir).list_materials():
        print(f"{m.id}  {m.filename}  {m.pages} page(s), {m.words} words")
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
        notes=args.notes,
    )
    record = new_session(store, brief)
    print(f"Session {record.id}")
    record = run_session(record, store, settings, on_update=lambda r: print(r.log[-1]))
    print(f"Files: {store.session_dir(record.id)}")
    return 0 if record.status == SessionStatus.DONE else 1


def cmd_eval(args: argparse.Namespace) -> int:
    from groundcast.evaluation.seeded import format_report, run_seeded, save_report
    from groundcast.llm import make_backend

    settings = _settings(args)
    set_path = Path(args.set) if args.set else _default_eval_set()
    report = run_seeded(set_path, settings, make_backend(settings.llm), args.runs)
    out = Path(args.out) if args.out else settings.data_dir / "evals" / f"seeded-{datetime.now():%Y%m%d-%H%M%S}.json"
    save_report(report, out)
    print(format_report(report))
    print(f"Report: {out}")
    return 0


def _default_eval_set() -> Path:
    """evals/seeded/items.json under the working directory or the source checkout."""
    relative = Path("evals") / "seeded" / "items.json"
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

    p = sub.add_parser("ingest", help="add material files to the data directory")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_ingest)

    sub.add_parser("materials", help="list materials").set_defaults(func=cmd_materials)

    p = sub.add_parser("session", help="produce one session from the command line")
    p.add_argument("--material", "-m", action="append", required=True, help="material ID (repeatable)")
    p.add_argument("--focus", required=True)
    p.add_argument("--title", default="")
    p.add_argument("--minutes", type=int, default=10)
    p.add_argument("--context", default="commute", choices=["desk", "commute", "exercise", "revision"])
    p.add_argument("--level", default="introductory", choices=["introductory", "intermediate", "advanced"])
    p.add_argument("--notes", default="")
    p.set_defaults(func=cmd_session)

    p = sub.add_parser("eval", help="run the seeded-error test of the Verifier")
    p.add_argument("--set", help="evaluation set file (default: evals/seeded/items.json in the repository)")
    p.add_argument("--runs", type=int, default=3, help="repeat runs to average out noise")
    p.add_argument("--out", help="report path (default: <data dir>/evals/)")
    p.set_defaults(func=cmd_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
