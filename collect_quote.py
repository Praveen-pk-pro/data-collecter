"""
Daily Motivational Quote Collector
-----------------------------------
Fetches ONE new motivational/inspirational quote from an AI model
(Gemini primary, OpenRouter fallback) and appends it to dataset.json
if it doesn't already exist (dedup by normalized quote text).

Run via GitHub Actions on a cron schedule (~20x/day) to build a
motivational quotes dataset over time and generate commit activity.
"""

import os
import re
import json
import hashlib
from datetime import datetime, timezone

# ---------------- Config ----------------
GOOGLEAPI1 = os.environ.get("GOOGLEAPI1", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
OPENROUTER_KEY2 = os.environ.get("OPENROUTER_KEY2", "")

DATASET_PATH = "dataset.json"

SYSTEM_PROMPT = """You are a quote curator for a motivational/inspirational quotes dataset.

Generate exactly ONE original or well-known motivational/inspirational quote.
Prefer real, attributable quotes (public domain figures, authors, philosophers,
entrepreneurs, athletes) over fabricated ones. Never repeat a quote already listed
as "used" below.

Respond with RAW JSON ONLY (no markdown, no code fences, no commentary), matching
this exact schema:

{
  "quote": "string, the quote text, no surrounding quotation marks",
  "author": "string, best-known attribution, or 'Unknown' if genuinely anonymous",
  "category": "one of: motivation, discipline, success, perseverance, growth, mindset, courage, gratitude",
  "tags": ["lowercase", "keyword", "list", "3 to 6 items"]
}
"""


# ---------------- Dataset helpers ----------------
def _normalize(text: str) -> str:
    """Lowercase + strip punctuation/whitespace for dedup comparison."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def load_dataset():
    if not os.path.exists(DATASET_PATH):
        return []
    try:
        with open(DATASET_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def save_dataset(dataset):
    with open(DATASET_PATH, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)


def get_existing_quotes_hashes(dataset):
    return {_normalize(item["quote"]) for item in dataset if "quote" in item}


def get_used_quotes_sample(dataset, limit=40):
    """Give the model a short list of recent quotes to avoid repeats."""
    return [item["quote"] for item in dataset[-limit:]]


def make_quote_id(quote_text: str) -> str:
    return hashlib.sha256(_normalize(quote_text).encode("utf-8")).hexdigest()[:12]


def _validate_package(pkg: dict) -> tuple[bool, str]:
    required = ["quote", "author", "category", "tags"]
    for field in required:
        if field not in pkg:
            return False, f"missing field: {field}"
    if not isinstance(pkg["quote"], str) or not pkg["quote"].strip():
        return False, "quote is empty"
    if len(pkg["quote"]) > 400:
        return False, "quote too long"
    if not isinstance(pkg["tags"], list):
        return False, "tags must be a list"
    return True, "ok"


# ---------------- 1a. Gemini primary ----------------
def _fetch_quote_gemini(used_list):
    if not GOOGLEAPI1:
        raise RuntimeError("GOOGLEAPI1 not configured.")
    from google import genai as gai

    client = gai.Client(api_key=GOOGLEAPI1)
    user_prompt = (
        f"Avoid these quotes (already used): {used_list}\n\n"
        "Generate one new motivational quote package as raw JSON only, "
        "per the system instructions."
    )
    print("   [Phase 1] Trying Google Gemini 2.5 Flash …")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"{SYSTEM_PROMPT}\n\n{user_prompt}",
    )
    content = response.text
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise RuntimeError("Gemini returned no JSON object.")
    package = json.loads(match.group(0))
    ok, reason = _validate_package(package)
    if not ok:
        raise RuntimeError(f"Gemini package invalid: {reason}")
    print(f"   [Phase 1] Gemini returned quote by: {package['author']}")
    return package


# ---------------- 1b. OpenRouter fallback ----------------
def _fetch_quote_openrouter(used_list):
    from openai import OpenAI

    api_keys = [k for k in [OPENROUTER_KEY, OPENROUTER_KEY2] if k]
    if not api_keys:
        raise RuntimeError("No OpenRouter API key configured.")

    user_prompt = (
        f"Avoid these quotes (already used): {used_list}\n\n"
        "Generate one new motivational quote package as raw JSON only, "
        "per the system instructions."
    )

    models_to_try = [
        "nvidia/nemotron-3-nano-30b-a3b:free",
        "qwen/qwen3-next-80b-a3b-instruct:free",
        "z-ai/glm-4.5-air:free",
        "openai/gpt-oss-20b:free",
        "google/gemma-3n-e2b-it:free",
        "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    ]

    last_err = None
    for key in api_keys:
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)
        for model_id in models_to_try:
            try:
                print(f"   [Phase 1 fallback] trying OpenRouter model {model_id} …")
                response = client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    timeout=45,
                )
                content = response.choices[0].message.content
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if not match:
                    print(f"   model {model_id} returned no JSON, trying next…")
                    continue
                package = json.loads(match.group(0))
                ok, reason = _validate_package(package)
                if not ok:
                    print(f"   model {model_id} invalid package ({reason}), trying next…")
                    continue
                print(f"   [Phase 1 fallback] {model_id} returned quote by: {package['author']}")
                return package
            except Exception as e:
                last_err = e
                print(f"   model {model_id} failed: {e}")
                continue

    raise RuntimeError(f"All OpenRouter models failed. Last error: {last_err}")


# ---------------- Orchestration ----------------
def fetch_quote_package(used_list):
    try:
        return _fetch_quote_gemini(used_list)
    except Exception as e:
        print(f"   [Phase 1] Gemini failed: {e}")
        print("   [Phase 1] Falling back to OpenRouter …")
        return _fetch_quote_openrouter(used_list)


def main():
    dataset = load_dataset()
    existing_hashes = get_existing_quotes_hashes(dataset)
    used_sample = get_used_quotes_sample(dataset)

    print(f"Loaded dataset with {len(dataset)} existing quotes.")

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        print(f"\nAttempt {attempt}/{max_attempts} to fetch a unique quote …")
        try:
            package = fetch_quote_package(used_sample)
        except Exception as e:
            print(f"Failed to fetch quote this attempt: {e}")
            continue

        norm = _normalize(package["quote"])
        if norm in existing_hashes:
            print("   Duplicate quote (already in dataset.json), retrying …")
            continue

        # Unique - build final record and save
        record = {
            "id": make_quote_id(package["quote"]),
            "quote": package["quote"].strip(),
            "author": package["author"].strip(),
            "category": package.get("category", "motivation"),
            "tags": package.get("tags", []),
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        dataset.append(record)
        save_dataset(dataset)
        print(f"\n✅ Added new quote (id={record['id']}) by {record['author']}")
        print(f"   Dataset now has {len(dataset)} quotes.")
        return

    print("\n⚠️  Could not obtain a unique quote after max attempts. Exiting without changes.")


if __name__ == "__main__":
    main()
