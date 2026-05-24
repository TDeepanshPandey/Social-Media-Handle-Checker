from app import (
    app,
    check_username,
    generate_suggestions,
    parse_result_limit,
    parse_usernames,
    selected_platforms,
    validate_form,
)


class DummyResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def test_generate_suggestions_from_description(monkeypatch):
    monkeypatch.setattr("app.fetch_related_terms", lambda *args, **kwargs: ["plantbased", "meals"])

    suggestions = generate_suggestions("Fast vegan recipes and budget kitchen shortcuts")

    assert suggestions
    assert "vegan" in suggestions[0]
    assert len(suggestions) <= 10
    assert len(suggestions) == len(set(suggestions))


def test_generate_suggestions_honors_larger_limit(monkeypatch):
    related = [f"related{i}" for i in range(30)]
    monkeypatch.setattr("app.fetch_related_terms", lambda *args, **kwargs: related)

    suggestions = generate_suggestions(
        "Fast vegan recipes budget kitchen shortcuts families healthy weeknight lunches",
        limit=25,
    )

    assert len(suggestions) == 25
    assert len(suggestions) == len(set(suggestions))


def test_generate_suggestions_handles_short_tokens_without_crashing(monkeypatch):
    monkeypatch.setattr("app.fetch_related_terms", lambda *args, **kwargs: [])

    suggestions = generate_suggestions("ai ux")

    assert suggestions == []


def test_parse_result_limit_allows_known_options_only():
    assert parse_result_limit("30") == 30
    assert parse_result_limit("999") == 10
    assert parse_result_limit("not-a-number") == 10


def test_parse_usernames_splits_commas_and_deduplicates():
    assert parse_usernames("@clearhandle, second.handle, CLEARHANDLE, third_name") == [
        "clearhandle",
        "second.handle",
        "third_name",
    ]


def test_validate_form_requires_input_and_platform():
    errors = validate_form("", [], [])

    assert "Enter a username to check, a description for suggestions, or both." in errors
    assert "Select at least one platform to check." in errors


def test_validate_form_allows_username_without_description():
    errors = validate_form("", ["instagram"], ["clearhandle"])

    assert errors == []


def test_validate_form_short_description_only_gets_description_error():
    errors = validate_form("short", [], [])

    assert "Please enter at least 10 characters for description-based suggestions." in errors
    assert "Select at least one platform to check." in errors


def test_selected_platforms_filters_unknown_values():
    assert selected_platforms(["instagram", "mastodon", "tiktok"]) == ["instagram", "tiktok"]


def test_invalid_username_is_reported_without_network_call():
    result = check_username("bad username", "youtube")

    assert result.status == "invalid"
    assert "Letters" in result.message


def test_profile_404_is_available(monkeypatch):
    monkeypatch.setattr("app.requests.get", lambda *args, **kwargs: DummyResponse(404))

    result = check_username("openhandle", "instagram")

    assert result.status == "available"


def test_profile_200_is_taken(monkeypatch):
    monkeypatch.setattr("app.requests.get", lambda *args, **kwargs: DummyResponse(200))

    result = check_username("takenhandle", "tiktok")

    assert result.status == "taken"


def test_profile_200_with_unavailable_page_is_available(monkeypatch):
    monkeypatch.setattr("app.requests.get", lambda *args, **kwargs: DummyResponse(200, "Couldn't find this account"))

    result = check_username("openhandle", "tiktok")

    assert result.status == "available"


def test_redirect_to_unavailable_page_is_available(monkeypatch):
    responses = iter(
        [
            DummyResponse(302),
            DummyResponse(200, "Sorry, this page isn't available. The link you followed may be broken."),
        ]
    )
    monkeypatch.setattr("app.requests.get", lambda *args, **kwargs: next(responses))

    result = check_username("openhandle", "instagram")

    assert result.status == "available"


def test_redirect_to_profile_page_is_taken(monkeypatch):
    responses = iter(
        [
            DummyResponse(302),
            DummyResponse(200, "<title>@takenhandle</title>"),
        ]
    )
    monkeypatch.setattr("app.requests.get", lambda *args, **kwargs: next(responses))

    result = check_username("takenhandle", "instagram")

    assert result.status == "taken"
    assert "after following the redirect" in result.message


def test_blocked_probe_is_unknown(monkeypatch):
    monkeypatch.setattr("app.requests.get", lambda *args, **kwargs: DummyResponse(429))

    result = check_username("rate_limited", "youtube")

    assert result.status == "unknown"


def test_home_page_loads():
    client = app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    assert b"Find social usernames" in response.data


def test_generic_description_without_username_gets_helpful_error():
    client = app.test_client()
    response = client.post(
        "/",
        data={
            "description": "the and with that this for your brand",
            "platforms": ["instagram"],
        },
    )

    assert response.status_code == 200
    assert b"Try adding a few more descriptive words" in response.data


def test_username_only_submission_checks_name(monkeypatch):
    monkeypatch.setattr("app.requests.get", lambda *args, **kwargs: DummyResponse(404))

    client = app.test_client()
    response = client.post(
        "/",
        data={
            "username": "clearhandle",
            "platforms": ["instagram"],
        },
    )

    assert response.status_code == 200
    assert b"Please enter at least 10 characters" not in response.data
    assert b"@clearhandle" in response.data
    assert b"https://www.instagram.com/clearhandle/" in response.data


def test_username_list_submission_checks_each_name(monkeypatch):
    monkeypatch.setattr("app.requests.get", lambda *args, **kwargs: DummyResponse(404))

    client = app.test_client()
    response = client.post(
        "/",
        data={
            "username": "@clearhandle, secondhandle, clearhandle",
            "platforms": ["instagram"],
        },
    )

    assert response.status_code == 200
    assert b"@clearhandle" in response.data
    assert b"@secondhandle" in response.data
    assert response.data.count(b"@clearhandle") == 1
