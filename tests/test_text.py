from app.text import brief


def test_brief_is_the_gist_or_else_the_first_sentence_within_200_characters():
    assert brief("Said hi.", "Hello there. How are you?") == "Said hi."
    assert brief("  ", "Hello there. How are you?") == brief(None, "Hello there. How are you?") == "Hello there."
    assert brief(None, "a" * 201) == "a" * 200 + "..." and brief("b" * 201, "") == "b" * 200 + "..."
    assert brief(None, None) == "" and brief("", "") == ""
