from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable

import requests
from flask import Flask, render_template, request


app = Flask(__name__)

AVAILABLE_PLATFORMS = {
    "instagram": {
        "name": "Instagram",
        "url": "https://www.instagram.com/{username}/",
        "help": "Letters, numbers, underscores, and periods; 1-30 characters.",
        "pattern": re.compile(r"^(?!.*\.\.)(?!.*\.$)[A-Za-z0-9._]{1,30}$"),
    },
    "youtube": {
        "name": "YouTube",
        "url": "https://www.youtube.com/@{username}",
        "help": "Letters, numbers, underscores, hyphens, and periods; 3-30 characters.",
        "pattern": re.compile(r"^[A-Za-z0-9._-]{3,30}$"),
    },
    "tiktok": {
        "name": "TikTok",
        "url": "https://www.tiktok.com/@{username}",
        "help": "Letters, numbers, underscores, and periods; 2-24 characters.",
        "pattern": re.compile(r"^(?!.*\.\.)(?!.*\.$)[A-Za-z0-9._]{2,24}$"),
    },
}

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "brand",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "your",
}

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

DATAMUSE_WORDS_URL = "https://api.datamuse.com/words"
RESULT_LIMIT_OPTIONS = (10, 15, 20, 25, 30, 50)
DEFAULT_RESULT_LIMIT = 10
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
BLOCKED_STATUS_CODES = {401, 403, 429}
UNAVAILABLE_PAGE_MARKERS = {
    "instagram": (
        "sorry, this page isn't available",
        "the link you followed may be broken",
        "page isn't available",
    ),
    "youtube": (
        "this channel doesn't exist",
        "this page isn't available",
        "404 not found",
    ),
    "tiktok": (
        "couldn't find this account",
        "couldn\u2019t find this account",
        "account not found",
        "user doesn't exist",
    ),
}


@dataclass(frozen=True)
class ProbeResult:
    platform: str
    username: str
    status: str
    message: str
    url: str | None = None


def clean_username(username: str) -> str:
    return username.strip().lstrip("@")


def parse_usernames(value: str) -> list[str]:
    usernames: list[str] = []
    seen: set[str] = set()

    for part in value.split(","):
        username = clean_username(part)
        normalized = username.lower()
        if username and normalized not in seen:
            seen.add(normalized)
            usernames.append(username)

    return usernames


def selected_platforms(raw_platforms: Iterable[str]) -> list[str]:
    return [platform for platform in raw_platforms if platform in AVAILABLE_PLATFORMS]


def parse_result_limit(value: str | None) -> int:
    try:
        parsed = int(value or DEFAULT_RESULT_LIMIT)
    except ValueError:
        return DEFAULT_RESULT_LIMIT

    return parsed if parsed in RESULT_LIMIT_OPTIONS else DEFAULT_RESULT_LIMIT


def validate_form(description: str, platforms: list[str], usernames: list[str]) -> list[str]:
    errors: list[str] = []
    has_description = bool(description.strip())
    has_username = bool(usernames)

    if not has_description and not has_username:
        errors.append("Enter a username to check, a description for suggestions, or both.")

    if has_description and len(description.strip()) < 10:
        errors.append("Please enter at least 10 characters for description-based suggestions.")

    if len(description) > 500:
        errors.append("Please keep the description under 500 characters.")

    if not platforms:
        errors.append("Select at least one platform to check.")

    invalid_usernames = [username for username in usernames if not re.match(r"^[A-Za-z0-9._-]{1,30}$", username)]
    if invalid_usernames:
        errors.append("Each username can only include letters, numbers, periods, underscores, and hyphens.")

    return errors


def tokenize_description(description: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", description.lower())
    filtered = [word for word in words if word not in STOP_WORDS and len(word) > 1]
    return filtered[:8]


def username_candidate(value: str) -> str:
    value = re.sub(r"[^a-z0-9_]", "", value.lower().replace("-", "_").replace(".", "_"))
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:24]


def fetch_related_terms(description: str, limit: int = 10, timeout: float = 4.0) -> list[str]:
    if os.environ.get("USE_DATAMUSE", "true").lower() in {"0", "false", "no"}:
        return []

    try:
        response = requests.get(
            DATAMUSE_WORDS_URL,
            params={"ml": description, "max": limit},
            headers=REQUEST_HEADERS,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return []

    terms: list[str] = []
    for item in payload:
        word = str(item.get("word", ""))
        candidate = username_candidate(word)
        if 3 <= len(candidate) <= 16 and candidate not in terms:
            terms.append(candidate)

    return terms


def generate_suggestions(description: str, limit: int = DEFAULT_RESULT_LIMIT) -> list[str]:
    tokens = tokenize_description(description)
    if not tokens:
        return []

    related_terms = fetch_related_terms(description, limit=max(20, limit))
    words = []
    seen_words: set[str] = set()
    for word in [*tokens, *related_terms]:
        candidate = username_candidate(word)
        if 3 <= len(candidate) <= 16 and candidate not in seen_words:
            seen_words.add(candidate)
            words.append(candidate)
    if not words:
        return []

    bases: list[str] = []
    bases.append("".join(words[:2]))
    bases.append("_".join(words[:2]))

    if len(words) >= 3:
        bases.append("".join(words[:3]))
        bases.append("_".join(words[:3]))

    first = words[0]
    second = words[1] if len(words) > 1 else "social"
    third = words[2] if len(words) > 2 else "club"
    bases.extend(
        [
            f"{first}hq",
            f"{first}studio",
            f"{first}daily",
            f"{first}lab",
            f"{first}{second}tv",
            f"{first}{third}",
            f"{second}{first}",
            f"get{first}",
            f"try{first}",
            f"{first}_official",
            f"{first}_{second}",
            f"{first}online",
        ]
    )

    for word in related_terms[:6]:
        bases.extend([f"{word}hub", f"{word}daily", f"{word}_{first}"])

    suffixes = ("hq", "studio", "daily", "lab", "hub", "club", "tv", "now", "social", "online")
    prefixes = ("get", "try", "my", "go", "the")
    for word in words[:12]:
        bases.extend(f"{word}{suffix}" for suffix in suffixes)
        bases.extend(f"{prefix}{word}" for prefix in prefixes)

    for index, left in enumerate(words[:10]):
        for right in words[index + 1 : index + 6]:
            bases.extend([f"{left}{right}", f"{left}_{right}", f"{right}{left}"])

    suggestions: list[str] = []
    seen: set[str] = set()
    for base in bases:
        candidate = username_candidate(base)
        if 3 <= len(candidate) <= 24 and candidate not in seen:
            seen.add(candidate)
            suggestions.append(candidate)
        if len(suggestions) >= limit:
            break

    return suggestions


def validate_for_platform(username: str, platform: str) -> str | None:
    pattern = AVAILABLE_PLATFORMS[platform]["pattern"]
    if not pattern.match(username):
        return AVAILABLE_PLATFORMS[platform]["help"]
    return None


def page_says_profile_unavailable(platform: str, response: requests.Response) -> bool:
    text = getattr(response, "text", "") or ""
    normalized_text = " ".join(text.lower().split())
    markers = UNAVAILABLE_PAGE_MARKERS.get(platform, ())

    return any(marker in normalized_text for marker in markers)


def check_username(username: str, platform: str, timeout: float = 6.0) -> ProbeResult:
    invalid_message = validate_for_platform(username, platform)
    url = AVAILABLE_PLATFORMS[platform]["url"].format(username=username)

    if invalid_message:
        return ProbeResult(platform, username, "invalid", invalid_message, url)

    try:
        response = requests.get(
            url,
            headers=REQUEST_HEADERS,
            allow_redirects=False,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return ProbeResult(platform, username, "unknown", f"Could not reach platform: {exc.__class__.__name__}.", url)

    if response.status_code == 404:
        return ProbeResult(platform, username, "available", "No public profile was found.", url)

    if page_says_profile_unavailable(platform, response):
        return ProbeResult(platform, username, "available", "No public profile was found.", url)

    if response.status_code == 200:
        return ProbeResult(platform, username, "taken", "A public profile appears to exist.", url)

    if response.status_code in BLOCKED_STATUS_CODES:
        return ProbeResult(
            platform,
            username,
            "unknown",
            f"Platform returned HTTP {response.status_code}; it may be blocking automated checks.",
            url,
        )

    if response.status_code in REDIRECT_STATUS_CODES:
        try:
            followed_response = requests.get(
                url,
                headers=REQUEST_HEADERS,
                allow_redirects=True,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            return ProbeResult(
                platform,
                username,
                "unknown",
                f"Profile URL redirected, but the follow-up check failed: {exc.__class__.__name__}.",
                url,
            )

        if followed_response.status_code == 404 or page_says_profile_unavailable(platform, followed_response):
            return ProbeResult(
                platform,
                username,
                "available",
                "No public profile was found after following the redirect.",
                url,
            )

        if followed_response.status_code == 200:
            return ProbeResult(
                platform,
                username,
                "taken",
                "A public profile appears to exist after following the redirect.",
                url,
            )

        if followed_response.status_code in BLOCKED_STATUS_CODES:
            return ProbeResult(
                platform,
                username,
                "unknown",
                f"Platform returned HTTP {followed_response.status_code}; it may be blocking automated checks.",
                url,
            )

        return ProbeResult(platform, username, "unknown", f"Redirect ended with HTTP {followed_response.status_code}.", url)

    return ProbeResult(platform, username, "unknown", f"Platform returned HTTP {response.status_code}.", url)


def run_checks(usernames: list[str], platforms: list[str]) -> dict[str, dict[str, ProbeResult]]:
    results: dict[str, dict[str, ProbeResult]] = {username: {} for username in usernames}

    with ThreadPoolExecutor(max_workers=min(12, max(1, len(usernames) * len(platforms)))) as executor:
        future_map = {
            executor.submit(check_username, username, platform): (username, platform)
            for username in usernames
            for platform in platforms
        }

        for future in as_completed(future_map):
            username, platform = future_map[future]
            results[username][platform] = future.result()

    return results


@app.get("/")
def home():
    return render_template(
        "index.html",
        platforms=AVAILABLE_PLATFORMS,
        result_limit_options=RESULT_LIMIT_OPTIONS,
        result_limit=DEFAULT_RESULT_LIMIT,
        selected=["instagram", "youtube", "tiktok"],
        description="",
        username="",
        suggestions=[],
        results={},
        errors=[],
    )


@app.post("/")
def check_handles():
    description = request.form.get("description", "").strip()
    username_input = request.form.get("username", "")
    direct_usernames = parse_usernames(username_input)
    result_limit = parse_result_limit(request.form.get("result_limit"))
    platforms = selected_platforms(request.form.getlist("platforms"))
    errors = validate_form(description, platforms, direct_usernames)

    suggestions = generate_suggestions(description, limit=result_limit) if description else []
    usernames = suggestions.copy()

    for username in reversed(direct_usernames):
        if username.lower() not in {candidate.lower() for candidate in usernames}:
            usernames.insert(0, username)

    if description and not suggestions and not direct_usernames:
        errors.append("Try adding a few more descriptive words so username suggestions can be generated.")

    results = {} if errors else run_checks(usernames, platforms)

    return render_template(
        "index.html",
        platforms=AVAILABLE_PLATFORMS,
        result_limit_options=RESULT_LIMIT_OPTIONS,
        result_limit=result_limit,
        selected=platforms,
        description=description,
        username=", ".join(direct_usernames),
        suggestions=suggestions,
        results=results,
        errors=errors,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
