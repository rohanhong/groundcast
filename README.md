<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset=".github/assets/banner-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset=".github/assets/banner-light.svg">
  <img alt="groundcast" src=".github/assets/banner-light.svg" width="380">
</picture>

<h1>🎧 groundcast</h1>

<p><b>Turn your own study materials into podcast-style audio sessions, with every statement grounded in those materials.</b></p>

<p>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/rohanhong/groundcast"></a>
  <a href="https://www.python.org"><img alt="Python" src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white"></a>
  <a href="https://github.com/rohanhong/groundcast/commits/main"><img alt="Last commit" src="https://img.shields.io/github/last-commit/rohanhong/groundcast"></a>
  <a href="https://github.com/rohanhong/groundcast/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/rohanhong/groundcast?style=flat"></a>
  <a href="https://agents.md"><img alt="AGENTS.md" src="https://img.shields.io/badge/AGENTS.md-ready-24292f"></a>
  <a href="https://agentskills.io"><img alt="Agent Skills" src="https://img.shields.io/badge/Agent%20Skills-open%20format-8250df"></a>
  <!-- Reserved badges: uncomment when the service exists.
  <a href="https://github.com/rohanhong/groundcast/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/rohanhong/groundcast/ci.yml?branch=main"></a>
  <a href="https://github.com/rohanhong/groundcast/releases"><img alt="Release" src="https://img.shields.io/github/v/release/rohanhong/groundcast"></a>
  -->
</p>

<p>🌐 <b>English</b> | <a href="docs/i18n/README.zh-CN.md">简体中文</a></p>

</div>

groundcast is a personal, local web app that turns the study materials you
already have (PDFs, slides, notes, web pages, videos) into a podcast-style
session for a commute, a workout, or revision before an exam. A fixed pipeline
of LLM roles writes the script, checks every factual claim against your
materials, and only then polishes the style; local text-to-speech renders the
result as an MP3 you can play in any phone player.

> [!NOTE]
> Version 1: all five milestones are built; a few checks still need real use,
> such as chapters in your phone player and how well your own handwriting is
> read. Add PDF (with a text layer or scanned), PowerPoint, Word, Markdown, or
> text files, web pages by address, photos of notes, or video and audio;
> recognised speech and scanned text are checked by you before use. Describe a
> session in your own words and confirm the brief it proposes; you get a
> verified MP3, read by one narrator or two hosts, with chapter marks, and a
> transcript whose links open each source at its page, slide, or moment. Typed
> questions and multiple-choice quizzes about a finished session come from
> your materials, and a session can end with recall questions, each followed
> by a pause. The concepts in your materials go into one table, with your quiz
> results on each, which you can rename and merge. Preferences set your
> default voice, speed, and brief, and every change to the profile is logged
> and can be exported. At session start, ranked suggestions say why they fit
> you; what groundcast infers from your past sessions and your feedback is
> shown to you and never used silently.

## ✨ Highlights

- 🔎 **Grounded by design**: every claim in a script cites the source chunks
  it rests on, and a separate Verifier checks it; anything not from your
  materials is marked as such.
- 🧭 **Write, verify, then edit**: a code-driven pipeline passes typed JSON
  between roles; style edits may add no new claims and are verified again.
- 🏠 **Local first**: parsing, OCR, speech recognition, and speech synthesis
  run on your machine; only LLM calls leave it, to the provider you choose.
- 🎧 **Listen anywhere**: MP3 export with chapter marks, plus an HTML
  transcript whose links lead back to the source page, slide, or timestamp.
  In the app, a player with a waveform and chapter marks keeps playing as you
  move between pages, and the transcript follows along sentence by sentence;
  a click on a sentence plays from there.
- 🧠 **A profile you can see**: preferences and quiz results live in a local
  SQLite profile with an event log you can view, edit, export, or delete.

## 🚀 Quick Start

> [!NOTE]
> Needs git, conda (for example [Miniforge](https://conda-forge.org/download/)),
> and, for the default LLM backend, an installed and signed-in Claude Code CLI
> (an API key works too). Developed on Windows 11 with an 8 GB NVIDIA GPU; the
> default TTS model also runs on CPU.

1. Clone the repository:
   ```bash
   git clone https://github.com/rohanhong/groundcast.git
   cd groundcast
   ```
2. Run the installer. It creates the conda environment (Python 3.12, ffmpeg,
   poppler, Tesseract for scans, and groundcast itself in editable mode), then
   asks which parts to add: the PyTorch build for speech synthesis (it reads
   `nvidia-smi` and recommends the newest build your GPU and driver can run,
   or the CPU build), speech recognition for video and audio, the Piper
   fallback voices, and the API backend. Enter takes each recommendation; at
   the end it checks the installation, makes a groundcast shortcut on the
   desktop and in the Start menu (the applications menu on Linux,
   `~/Applications` on macOS), and offers to start groundcast.
   - Windows: double-click `install.cmd`, or run `.\install.cmd` in a terminal.
   - Linux or macOS: `./install.sh`

   Add `--yes` to take every recommendation without questions, `--dry-run`
   to only print the pip commands, or choices such as `--torch cpu --no-asr`.
   Model weights download on first use (Kokoro about 330 MB, the speech
   recognition model about 1.6 GB).
3. Double-click the groundcast shortcut. No terminal opens: the service
   starts in the background and groundcast opens in its own window (an Edge
   or Chrome app window, otherwise a tab in your default browser) at
   <http://127.0.0.1:8765/>, on `127.0.0.1` only. A second double-click
   only brings up another window. When every groundcast window is closed
   and no session or recognition is running, the service stops by itself;
   "Stop groundcast" in the sidebar stops it at once. Without a console, its
   output goes to `logs/launcher.log` in the data directory.

   From a terminal, `groundcast launch` does the same, and `groundcast serve`
   runs the service in the foreground; `groundcast shortcut` makes the
   shortcuts again (`--remove` removes them). The `[launcher]` settings choose
   the window and when the service stops.

Inside the environment, `groundcast setup` offers the same choices again (for
example after a driver update), and `groundcast doctor` checks every part and
prints the command that fixes anything missing; the app shows the same check
in its preferences.

<details>
<summary>Manual installation</summary>

1. Create and activate the environment:
   ```bash
   conda env create -f environment.yml
   conda activate groundcast_env_py312
   ```
2. Add speech synthesis (Kokoro-82M with a CPU build of PyTorch):
   ```bash
   pip install -e ".[tts]"
   ```
   On an NVIDIA GPU, replace PyTorch with a CUDA build. Pick the build from
   the [PyTorch compatibility matrix](https://github.com/pytorch/pytorch/blob/main/RELEASE.md)
   that your driver supports (`nvidia-smi` shows the highest CUDA version);
   for example, the CUDA 13.0 build of PyTorch 2.14.1:
   ```bash
   pip install "torch==2.14.1+cu130" --index-url https://download.pytorch.org/whl/cu130
   ```
   With `tts.device = "auto"` (the default), groundcast then uses the GPU.
3. Optional: add speech recognition for video and audio (faster-whisper):
   ```bash
   pip install -e ".[asr]"
   ```
   It runs on the CPU as is. For the GPU, add the CUDA 12 libraries that
   CTranslate2 needs (PyTorch's CUDA libraries are a different version):
   ```bash
   pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
   ```
   On Linux, also add their `lib` folders to `LD_LIBRARY_PATH`.
4. Optional: the Piper fallback voices (`pip install piper-tts`) and the API
   backend (`pip install -e ".[api]"`).

</details>

The same pipeline runs from the command line: `groundcast ingest <files>`
(or `--url <address>` for a web page; check recognised speech or scanned
text with `groundcast review <material id>`), then `groundcast session -m <material id> --focus "<what to cover>"` (add
`--format two_hosts` for two hosts, `--recall` for recall questions at the
end). Ask about a finished session with `groundcast ask <session id>
"<question>"`, or print a checked quiz with `groundcast quiz <session id>`;
list the concept table with `groundcast concepts`; set preferences with
`groundcast prefs --set speed=1.1`; rate a session with `groundcast feedback
<session id> --rating 4 --length too_long`; see ranked suggestions with
`groundcast suggest`. Run `groundcast --help` for every
command.

## 🗺️ Roadmap

v1 is complete when all five milestones are done; each stage stays usable on
its own.

| Stage | Adds |
|---|---|
| M1 | Text-layer PDF, Markdown, text; brief form; Writer, Verifier, Editor through Claude; Kokoro single narrator; MP3 plus HTML transcript |
| M2 | Dialogue set-up; two hosts; chapters; text Q&A; quizzes; offline recall prompts; preferences and event log |
| M3 | PPTX, DOCX, web pages; video through local speech recognition |
| M4 | Ranked suggestions from learned preferences; rubric-driven prompt tuning; local claim-checker evaluation |
| M5 | Scans and handwriting through local OCR, confirmed by you before use |

## ⚙️ Configuration

- **Data directory**: materials, chunks, the profile, and sessions live
  outside the repository, in the per-user data directory of the OS, overridable
  by `GROUNDCAST_DATA_DIR`.
- **Model weights**: downloaded on first use into the per-user cache directory
  of the OS, overridable by `GROUNDCAST_MODEL_DIR`; never into the repository.
- **Settings**: an optional TOML file outside the repository (the per-user
  config file, or the file named by `GROUNDCAST_CONFIG`), plus environment
  variables of the form `GROUNDCAST_<SECTION>_<KEY>`, which win.
  [`config/groundcast.example.toml`](config/groundcast.example.toml) lists every
  key and its default; `groundcast paths` shows the paths in use. API keys come
  only from environment variables, never from files.

## 🧩 Models and Licences

MIT covers only this repository's code. Each model and program below keeps its
own licence; weights are downloaded, never committed.

| Component | Used for | Code / weights licence | How groundcast runs it |
|---|---|---|---|
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | Speech synthesis (M1) | Apache-2.0 / Apache-2.0 | Python package; its in-process espeak-ng loader is blocked |
| [spaCy `en_core_web_sm`](https://github.com/explosion/spacy-models) | English text analysis for Kokoro's pronunciation | MIT / MIT | Python package |
| [Piper](https://github.com/OHF-Voice/piper1-gpl) | Fallback speech synthesis (`tts.engine = "piper"`; see the example config) | GPL-3.0 / per voice | Separate process only (`pip install piper-tts`) |
| espeak-ng | Optional pronunciation fallback for words Kokoro does not know | GPL | Separate program only (`tts.espeak_bin`) |
| ffmpeg, poppler | Audio encoding, PDF text | LGPL build, GPL | Separate programs (conda-forge) |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with [Whisper large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) | Speech recognition for video and audio (M3) | MIT / MIT | Python package (the `asr` extra) |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) with its English data | Text recognition for scans and handwriting (M5) | Apache-2.0 / Apache-2.0 | Separate program (conda-forge) |

## ⚠️ Responsible Use

- **Subscription mode** only launches your own installed CLI. You are
  responsible for your provider's terms; sharing one subscription across users
  is not supported.
- **Your data stays yours**: materials, extracted text, the profile, scripts,
  and audio stay in the data directory. Do not redistribute audio built from
  course materials.
- **Synthetic voices**: every audio file states that it is AI-generated, and
  groundcast never clones real people's voices.
- **Limits**: LLM verification reduces errors but cannot remove them, and it
  cannot catch errors already in your materials.

## 📚 Documentation

| Topic | Where |
|---|---|
| Agent instructions, commands, layout | [`AGENTS.md`](AGENTS.md) |
| Commit format, workflow, branch naming | [`.gitmessage`](.gitmessage) |
| Environment definition | [`environment.yml`](environment.yml), [`pyproject.toml`](pyproject.toml) |
| Settings reference | [`config/groundcast.example.toml`](config/groundcast.example.toml) |
| Verifier evaluation set (`groundcast eval`) | [`evals/seeded/`](evals/seeded/) |
| Script-quality briefs (`groundcast eval-quality`) | [`evals/quality/`](evals/quality/) |
| Source register for prompt distillation (files stay local) | [`references/`](references/README.md) |
| Distilled rules and their sources | [`docs/distillation/`](docs/distillation/README.md) |

## 🤝 Contributing

Issues and pull requests are welcome. groundcast is a personal project, so its
scope follows the owner's design; read the [Contributing guide](CONTRIBUTING.md)
first.

## 🔗 Resources

- [Claude Code](https://github.com/anthropics/claude-code): the default LLM backend, driven in headless mode.
- [FastAPI](https://fastapi.tiangolo.com): the local service framework.
- [FActScore](https://doi.org/10.18653/v1/2023.emnlp-main.741): splitting long text into atomic claims.
- [MiniCheck](https://doi.org/10.18653/v1/2024.emnlp-main.499): low-cost claim checking against source documents.
- [Dunlosky et al. 2013](https://doi.org/10.1177/1529100612453266): evidence for practice testing and spacing, behind the quiz and recap design.

## ⚖️ Legal

- **License**: [MIT](LICENSE)
- **Code of Conduct**: [Contributor Covenant 3.0](CODE_OF_CONDUCT.md)
- **Security**: report vulnerabilities privately per [SECURITY.md](SECURITY.md)
<!-- - **Terms of Service**: [TERMS.md](TERMS.md) (add when the project runs a hosted service) -->

## ⭐ Star History

<a href="https://www.star-history.com/#rohanhong/groundcast&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=rohanhong/groundcast&type=Date&theme=dark">
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=rohanhong/groundcast&type=Date">
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=rohanhong/groundcast&type=Date" width="600">
  </picture>
</a>
