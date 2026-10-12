# Contributing

<p><b>English</b> | <a href="docs/i18n/CONTRIBUTING.zh-CN.md">简体中文</a></p>

Thanks for your interest in Groundcast. It is a personal project whose code is
public and whose scope follows the owner's design; this guide covers how to
propose a change and what a change must satisfy before it is merged.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
Report security problems privately as described in [SECURITY.md](SECURITY.md),
never in a public issue.

## Ways to Contribute

- **Report a bug**: open an issue with what you ran, what you expected, what
  happened, and your OS, Python version, and LLM backend (Claude Code CLI
  version, or API).
- **Suggest a change**: open an issue first for anything larger than a small
  fix, so the approach can be agreed before you write it.
- **Send a pull request**: fixes and improvements to code, prompts, and docs
  are welcome.

## Development Setup

1. Install git and conda (for example Miniforge).
2. Create and activate the environment:
   ```bash
   conda env create -f environment.yml
   conda activate groundcast_env_py312
   ```
3. After editing `environment.yml`, apply it with
   `conda env update -f environment.yml`.
4. Run the tests: `python -m pytest`. They use a fake LLM backend and a
   silent speech engine, so they need neither Claude nor the Kokoro model.
5. When a change touches the Verifier or its prompt, also run the seeded-error
   test, `groundcast eval`, which calls the configured LLM backend, and compare
   its detection and false-flag rates with the previous run. It exits with a
   non-zero status when the rates miss the pass thresholds in the
   `[evaluation]` settings.

## Workflow

1. Fork the repository and clone your fork.
2. Wire up the commit template: `git config commit.template .gitmessage`.
3. Create a short-lived branch off `main`, named
   `<type>/<scope>/<short-desc>` per the Branch Naming section of
   `.gitmessage` (for example `feature/tts/kokoro-render`); the
   `git-branch-create` skill does this for you.
4. Commit in the `.gitmessage` format, `<type>(<scope>): <subject>`, one
   logical change per commit; the `git-commit` skill drafts these for you.
5. Push to your fork and open a pull request against `main`. Describe what
   changed and why, and link the issue it resolves.

## Change Rules

- **Artifacts**: code, comments, logs, and in-repo docs are English and ASCII
  only. The README and CONTRIBUTING files and their translations are the
  exception, as `AGENTS.md` (Conventions) describes.
- **No user data**: never commit uploaded materials, extracted text, the
  profile database, generated scripts or audio, model weights, API keys, or
  tokens.
- **Test materials**: examples in tests are self-written or openly licensed,
  never course materials.
- **GPL programs**: Piper and espeak-ng run only as separate processes; the
  MIT code never imports them.
- **No hardcoded values**: take paths and settings from config files,
  arguments, or environment variables.
- **Docs move with the change**: when a change makes a doc inaccurate, fix it
  in the same pull request, including `README.md` and every translation in
  `docs/i18n/`.

## Before You Open a Pull Request

- [ ] Tests pass: `python -m pytest`.
- [ ] No user data, model weights, or secrets in the diff.
- [ ] No non-ASCII text outside the README and CONTRIBUTING files:
      `LC_ALL=C git grep -nI --untracked '[^[:print:][:space:]]' -- . ':!README.md' ':!CONTRIBUTING.md' ':!docs/i18n'`
      prints nothing.
- [ ] README and CONTRIBUTING files agree with their translations.
- [ ] Commit messages follow `.gitmessage`.

## License

Contributions are accepted under the repository's [MIT License](LICENSE).
