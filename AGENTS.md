# Agent Instructions

Shared instructions for every AI agent tool working in this repository. This
file is the single source of instructions; edit it, never an adapter file.

## Project

Groundcast: a local web app (browser UI plus a local Python service) that
turns the owner's own study materials into podcast-style audio sessions, in
which every statement is grounded in those materials.

## Commands

- Install for a user in one step: `install.cmd` (Windows) or `./install.sh`
  (creates or updates the environment, then runs `groundcast setup` in it).
- Choose the optional parts (PyTorch build from `nvidia-smi`, speech
  recognition, Piper, API backend; the choices live in
  `src/groundcast/install.toml`): `groundcast setup` (`--yes`, `--dry-run`,
  `--torch <build>|keep`, `--[no-]asr`, `--[no-]piper`, `--[no-]api`).
  Check the installation: `groundcast doctor` (also `GET /api/doctor`).
- Start without a terminal: `groundcast launch` (what the desktop and menu
  shortcuts run, through pythonw on Windows; starts the service if needed,
  opens an app window, and stops the service once no page is open and no
  work runs; settings in `[launcher]`). Make the shortcuts:
  `groundcast shortcut` (`--remove`, `--no-desktop`); setup offers them.
- Create the environment: `conda env create -f environment.yml`
- Activate it: `conda activate groundcast_env_py312`
- Apply edits to `environment.yml`: `conda env update -f environment.yml`
  (it installs this package in editable mode with the `dev` extra).
- Add speech synthesis: `pip install -e ".[tts]"`; speech recognition for
  video and audio: `pip install -e ".[asr]"` (for its GPU use, also
  `pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"`); the Piper
  fallback voices: `pip install piper-tts` (GPL; groundcast only runs the
  program); the API backend: `pip install -e ".[api]"`.
- GPU speech synthesis (the owner's machine: RTX 3070 Laptop, sm_86, driver
  595.97): `pip install "torch==2.14.1+cu130" --index-url
  https://download.pytorch.org/whl/cu130`. Re-run it after anything that
  reinstalls torch from PyPI, which brings back the CPU build.
- Test: `python -m pytest` (fake LLM backend, silent TTS; no network).
- Run the app: `groundcast serve` (http://127.0.0.1:8765/); other commands:
  `groundcast --help`.
- Verifier baseline: `groundcast eval --runs 3` (calls the configured LLM
  backend; reports detection and false-flag rates and balanced accuracy on
  `evals/seeded/`, overall and per item tag, such as `hard` or one error
  type, with a table of the labels given; exits non-zero when they miss the
  pass thresholds in the `[evaluation]` settings).
- Script quality: `groundcast eval-quality` (writes scripts for the briefs in
  `evals/quality/` and scores them with the LLM judge against the fixed
  criteria in `prompts/judge.md`; run it before and after a prompt change,
  with `--generations 2` or more since scripts vary, and keep the change
  only if the scores improve).

## Code layout

- `src/groundcast/`: `ingest/` (PDF, Office, web pages; speech
  recognition for video and audio and OCR for scans and images, whose text
  waits for the user's review), `material_view.py` (source labels, links,
  and the per-material text view), `pipeline/` (writer, verifier,
  editor, run), `llm/` (the `LLMBackend` interface and its Claude Code
  CLI, Codex CLI, and API backends), `elicit.py` (brief by dialogue), `voice_direction.py` (pace
  per segment), `tts/`, `sessions.py` (export), `qa.py` and `quiz.py`
  (text Q&A and quizzes), `trash.py` (deleted materials, sessions,
  questions, quizzes, and concepts, with their profile rows, until
  restored or purged), `profile/` (the SQLite profile:
  preferences, inferred preferences and ranked suggestions, session
  feedback, concept table, quiz results, event log), `web/` (FastAPI app and
  static UI), `evaluation/`, `install.py` and `install.toml` (`groundcast
  setup`), `doctor.py` (`groundcast doctor`), `launcher.py` (`groundcast
  launch`), `shortcuts.py` and `icon.py` (`groundcast shortcut`). `icon.py`
  holds the one drawing of the brand (a flat G of sound waves whose crossbar
  is the ground line, with a simpler drawing at 24 px and below), and
  `wordmark.py` the product name and tagline as Fraunces outlines, written
  by `scripts/outline_wordmark.py`. The brand kit in `assets/brand/` (see its
  README), `web/static/favicon.svg`, `logo.svg`, and `wordmark.svg`, and the
  README banners in `.github/assets/` are its output, listed in
  `BRAND_FILES`, and the shortcut icons are rendered from it at install
  time. The tracked binary images are `assets/brand/social-preview.png`
  (listed in `RASTER_FILES`), rendered with resvg-py from its SVG and
  carrying that SVG's SHA-256, and the README demo recordings in
  `assets/demo/` (see its README), which `scripts/record_demo.py`
  records from the live app as `olm-session.toml` there describes, with
  a real LLM run. After changing the drawing, run `python -m
  groundcast.icon` to rewrite the drawn files (tests compare them). The
  page links the favicon and logo with the drawing's digest, and on
  Windows the launcher sets the .ico on the app windows, since the browser
  would show its cached, stretched favicon there.
- Prompts live in `src/groundcast/prompts/*.md`; `rubric.md` is shared by
  the Writer, reviser, and Editor prompts; `dialogue.md` and `recall.md` are
  added to the Writer prompt for two-host sessions and recall prompts.
- Tests mirror the modules (`tests/test_<module>.py`); the fake LLM backend,
  the scripted pipeline run, and shared fixtures live in `tests/conftest.py`.
- Every setting is a field in `src/groundcast/config.py`; add new ones there
  and to `config/groundcast.example.toml` (a test keeps the two in step).
- Tests and eval materials must be self-written or openly licensed.
- `references/` holds the distillation sources (books, papers, transcripts)
  on the local machine only; git tracks just its README register. Rules
  distilled from them, in our own words with source IDs, go in
  `docs/distillation/`; never copy source text into prompts or docs.

## Conventions

- The product name is Groundcast (capital G) in prose, the UI, window
  titles, and shortcuts; `groundcast` stays for the command, the Python
  package, file and folder names, and identifiers such as the data directory.
- Commits and branching follow `.gitmessage` (see its `Workflow:` and
  `Adopted:` lines).
- Use the git-* skills for git operations. `.gitmessage` is normative for
  the repository's commit and merge messages;
  `.agents/skills/git-commit/references/message-spec.md` is the skills'
  detailed reading of it and defers to `.gitmessage` on any conflict.
- `README.md` and `CONTRIBUTING.md` are canonical English; each
  translation (`docs/i18n/<NAME>.<locale>.md`) changes in the same change
  set. The `repo-docs` skill owns the front-page documents (README,
  CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, LICENSE, and when needed TERMS,
  NOTICE, and COPYING), their translations, the header images in
  `.github/assets/`, and the settings record `.github/settings.yml`.
  README files may use emoji; README and CONTRIBUTING files and their
  translations may use non-English text.
- `.github/settings.yml` records the GitHub "About" panel (description,
  website, topics) and the template flag. GitHub does not read it: change
  the file first, then apply it on GitHub by hand; a change made on GitHub
  is copied back into the file.
- `.github/rulesets/protect-main.json` records the GitHub ruleset that
  blocks deleting and force-pushing `main`. GitHub does not read it
  either: it is imported on GitHub by hand, and only when the user asks
  for it, for example by choosing **protect** at `repo-init` step 6h. The template copy
  holds only rules that apply under every workflow variant; step 6h adds a
  pull request rule for `github-flow` and `git-flow` on request. A change
  made on GitHub is copied back into the file.

## Layout

Canonical content lives only in the two open-convention locations:

- `AGENTS.md` (this file): instructions.
- `.agents/skills/<name>/SKILL.md`: skills, one directory each.

A tool that does not read these locations gets a thin adapter, never a copy.
Add adapters only for such tools: a tool that reads both a canonical location
and an adapter may list the same content twice.

- Instruction adapter: a file in the tool's own format and location whose
  only content imports or points to `AGENTS.md` (for example, a single
  `@AGENTS.md` import line where the tool supports imports).
- Skills adapter: a relative symbolic link from the tool's skills directory to
  `.agents/skills` (for example, `.<tool>/skills -> ../.agents/skills`).

The template ships two adapters, both for Claude Code:

- `CLAUDE.md` holds only the `@AGENTS.md` import. When a `CLAUDE.md` exists,
  Claude Code loads it instead of reading `AGENTS.md` directly, so this import
  is how `AGENTS.md` reaches Claude Code; it never loads the file twice.
- `.claude/skills` is an accepted exception to the adapter rule above: Claude
  Code discovers skills only in `.claude/skills`, but several other tools read
  both `.agents/skills` and `.claude/skills`, so they may list each skill
  twice. Some of those tools offer a setting to ignore the Claude location.
  Some tools read `.claude/skills` but not `.agents/skills` (Cline, for
  example), so for them this link is the only way to the skills: when it is
  broken (see the Windows notes below), those tools find no skills.

Some tools need an adapter the template does not ship. For example, Gemini
CLI reads `GEMINI.md` by default (an instruction adapter, or its setting for
the context file name), and Kiro reads skills only from `.kiro/skills` (a
skills adapter). Add a skills adapter with a relative link where symbolic
links work:

```sh
MSYS=winsymlinks:nativestrict ln -s ../.agents/skills .<tool>/skills &&
  [ -L .<tool>/skills ]
```

The `MSYS` setting is ignored outside Git Bash. Without it, Git Bash lacking
symlink permission silently copies the directory instead of linking it; with
it, `ln` fails with `Operation not permitted`, a nonzero exit status, and no
copy left behind.

Where links do not work (Windows without symlink permission), write the
target as a plain file and register it in the index as a link, so every
symlink-aware checkout gets a real link:

```sh
printf %s ../.agents/skills > .<tool>/skills
git update-index --add --cacheinfo "120000,$(printf %s ../.agents/skills | git hash-object -w --stdin),.<tool>/skills"
```

Adding support for a tool means adding its adapters, plus its directory and
root instruction file to the AI tool `export-ignore` list in `.gitattributes`
when not already listed (commented out while the other lines there are);
nothing canonical moves or is duplicated. Adapter links are recognized by
target, not by path: a symbolic link whose target ends in `.agents/skills`.
Where a link has to be written as a plain file, its content is the target
alone, with no trailing newline.

On Windows, links need Developer Mode or administrator rights, plus
`core.symlinks`. Before a fresh clone, run `git config --global core.symlinks
true` (or clone with `git clone -c core.symlinks=true <url>`); to repair an
existing checkout, run `git config core.symlinks true` in it, then `rm <link>
&& git checkout -- <link>` for each broken link. Otherwise git writes each
link as a plain text file and the tool reading it sees nothing.

## Skill authoring

Skills must run under any agent tool, so they follow these rules:

- Frontmatter requires `name` and `description`. The only optional field
  allowed is `compatibility` (Agent Skills specification, at most 500
  characters), for environment needs such as network access or an installed
  program. Frontmatter must be valid YAML: quote a value, or use a block
  scalar such as `>-`, when it contains `: `.
- Size follows the Agent Skills specification: `name` at most 64
  characters, `description` at most 1024 characters and about 100 tokens,
  `compatibility` at most 500 characters, and SKILL.md under 500 lines
  with a body under 5000 tokens. Keep each body under 4500 tokens as the
  o200k tokenizer counts them, since other tokenizers count more. Move
  detail an agent needs only at one step into `references/`, and name the
  file at that step; gates and Hard rules stay in SKILL.md.
- Skills need git 2.22 or later (they use `git branch --show-current`) and a
  POSIX shell.
- A skill may use another skill's file only through a path relative to its
  own directory (`../<skill>/...`) and must name that dependency in its body;
  the template ships the skills as one set.
- Every SKILL.md begins its Procedure with this line: "Terms such as choice
  question, independent reads, invoke, and suggest follow AGENTS.md (Skill
  authoring); in a non-interactive session every gate ends this skill."
- Name capabilities, never a specific tool's feature or tool names. Each tool
  maps these terms to its own features:
  - **gate**: a step whose action waits on the user: a choice question used
    as a gate, a confirmation, or an explicit in-turn opt-in.
  - **choice question**: 2 to 4 options, mutually exclusive unless the
    question is multi-select, each with its tradeoff; the user may always
    answer in their own words. Use the tool's structured question interface
    when it has one, otherwise numbered options in plain text, then wait. A
    choice question used as a gate blocks the gated action until the user
    answers.
  - **explicit in-turn opt-in**: a reply in the current turn that names the
    protected action and its target, either typed or by choosing an option
    whose label states that action and target (for example `yes, merge
    directly into main`). A generic yes, or approval from an earlier turn, is
    not an opt-in.
  - **non-interactive session**: when the session cannot put a question to
    the user and receive the answer (batch, CI, or cloud runs), every gate
    ends the skill: stop, report the pending question and the current state,
    and take no gated action. Never pick an option on the user's behalf; an
    explicit in-turn opt-in can only come from the user.
  - **POSIX shell**: run commands in a POSIX shell (Git Bash on Windows);
    snippets use POSIX redirections and heredocs. When the agent's default
    shell is not POSIX (for example PowerShell on Windows), run each snippet
    through bash. From Windows PowerShell 5.1, pass the snippet verbatim in a
    single-quoted here-string on stdin:

    ```powershell
    try { $bash = (Resolve-Path -ErrorAction Stop (Join-Path (git --exec-path) '../../../bin/bash.exe')).Path } catch { throw "Git Bash not found: $_" }
    $OutputEncoding = [Console]::InputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    @'
    <snippet, unchanged>
    '@ | & $bash -c "tr -d '\r' | bash /dev/fd/3 3<&0 </dev/null"
    ```

    The first line finds Git Bash next to git (a bare `bash` may be WSL's)
    and throws, ending the command, when git or Git Bash is missing, so a
    stale `$LASTEXITCODE` is never read as the snippet's status; report that
    and stop. The single-quoted here-string keeps quotes, `$`, and quoted
    heredocs literal; stdin avoids the 5.1 bug that drops double quotes from
    native arguments such as `bash -c '<snippet>'`. The encoding line stops
    5.1 from prepending a byte order mark and makes non-ASCII output decode
    as UTF-8; these settings persist for the rest of that PowerShell session.
    `tr` drops the carriage returns PowerShell adds. The inner bash reads the
    script from descriptor 3 and gives its commands an empty stdin, so a
    command that reads stdin cannot swallow the rest of the snippet (with
    `bash -s`, later lines would silently never run and the status would
    still be 0). The closing `'@` must start its line, so a snippet cannot
    contain a line that starts with `'@`. `$LASTEXITCODE` holds the snippet's
    exit status.
  - **independent reads**: commands that do not depend on each other; run
    them concurrently when the agent can, otherwise one after another in any
    order.
  - **in-place edit** / **write the file**: change part of a file while
    preserving the rest, versus create or replace a whole file.
  - **the agent**: whichever tool is executing the skill.
  - **skill directory** (`<skill-dir>`): the absolute path of the directory
    holding the running skill's SKILL.md. Paths such as `references/x.md` or
    `scripts/x.sh` in a skill resolve against it, and `../<skill>/...`
    reaches a sibling skill. When the tool does not show it, use
    `<repository toplevel>/.agents/skills/<name>`. Quote it in commands,
    since it may contain spaces.
  - **invoke `<skill>`**: the agent runs that skill now, under that skill's
    own gates, however the tool triggers skills.
  - **suggest `<skill>`**: name that skill to the user as a next step without
    running it.
