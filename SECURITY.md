# Security Policy

## Supported Versions

groundcast has no releases yet. Fixes land on `main` only.

| Version | Supported |
|---|---|
| `main` (latest commit) | Yes |
| Older commits | No |

## Reporting a Vulnerability

Please do not report security problems in public issues, discussions, or pull
requests.

Report them privately through GitHub:
[Report a vulnerability](https://github.com/rohanhong/groundcast/security/advisories/new)
(the **Security** tab, then **Report a vulnerability**).

Include what you can of:

- the affected component and the commit you tested;
- steps to reproduce, and your OS and LLM backend;
- the impact, and a suggested fix if you have one.

## What to Expect

- An acknowledgement within 7 days. This is a single-maintainer project, so
  responses are best effort.
- Updates as the report is triaged and fixed, through the private advisory.
- Coordinated disclosure: the advisory is published once a fix is on `main`,
  with credit to you unless you prefer otherwise.

## Scope

In scope: anything in this repository that could expose the local service
beyond `127.0.0.1`, leak user materials, the profile, API keys, or tokens, make
the CLI backend run an unintended command, or write outside the data
directory.

Out of scope: vulnerabilities in third-party software groundcast calls (the
Claude Code CLI, LLM provider APIs, speech, OCR, and claim-checking models,
ffmpeg, poppler); report those upstream.
