from spike.scrub import scrub

RAW = {
    "html_url": (
        "https://canvas.school.edu/courses/12/assignments/34"
        "?access_token=1234~AbCdEfGhIjKlMnOpQrStUvWxYz"
    ),
    "title": "Essay about Jane Doe",
    "context_name": "BIO 201 - Section 4",
    "description": "<p>secret instructions</p>",
    "user": {"name": "Jane Doe", "email": "jane@school.edu", "id": 987654},
    "nested": [{"note": "token 5678~ZyXwVuTsRqPoNmLkJiHgFeDcBa here"}],
}


def test_scrub_removes_tokens_emails_names_host_and_descriptions() -> None:
    out = repr(scrub(RAW, canvas_host="canvas.school.edu"))
    for needle in [
        "1234~",
        "5678~",
        "jane@school.edu",
        "Jane Doe",
        "canvas.school.edu",
        "secret instructions",
        "987654",
    ]:
        assert needle not in out
    assert "canvas.example.edu" in out


def test_scrub_is_deterministic_and_keeps_structure() -> None:
    a = scrub(RAW, "canvas.school.edu")
    b = scrub(RAW, "canvas.school.edu")
    assert a == b
    assert set(a) == set(RAW) - {"description"}
