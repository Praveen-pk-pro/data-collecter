# Daily Quote Collector

Fetches one motivational/inspirational quote from an AI model (Gemini primary,
OpenRouter fallback), dedupes it against `dataset.json`, and appends it —
running automatically ~20x/day via GitHub Actions.

## Setup

1. Push this repo to GitHub.
2. Add repo secrets (Settings → Secrets and variables → Actions):
   - `GOOGLEAPI1` — Google Gemini API key (primary)
   - `OPENROUTER_KEY` — OpenRouter API key (fallback)
   - `OPENROUTER_KEY2` — second OpenRouter key (optional, extra fallback)
3. Confirm the default branch is `main` (or edit `git push origin main` /
   `git pull --rebase origin main` in the workflow if yours is `master`).
4. Enable Actions on the repo if prompted. The workflow also has
   `workflow_dispatch`, so you can trigger it manually from the Actions tab
   to test it immediately instead of waiting for the next cron slot.

## How it works

- `collect_quote.py`:
  1. Loads `dataset.json` (a JSON array of quote records).
  2. Asks Gemini 2.5 Flash for one new quote as raw JSON (falls back through
     several free OpenRouter models if Gemini fails/is unconfigured).
  3. Normalizes + hashes the quote text to check for duplicates.
  4. If unique, appends a record and rewrites `dataset.json`. If it collides,
     it retries (up to 5 attempts) before giving up for that run.
- The workflow installs deps, runs the script, and commits `dataset.json`
  only if it actually changed — so failed/duplicate runs don't create empty
  commits.

## Record shape

```json
{
  "id": "a1b2c3d4e5f6",
  "quote": "The way to get started is to quit talking and begin doing.",
  "author": "Walt Disney",
  "category": "motivation",
  "tags": ["action", "beginning", "discipline"],
  "added_at": "2026-07-14T09:05:00+00:00"
}
```

## Local test

```bash
pip install google-genai openai
export GOOGLEAPI1=your_key_here
python collect_quote.py
```
