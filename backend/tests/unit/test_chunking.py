import pytest

from app.services.chunking import chunk_text

LOREM = (
    "Restart the VPN client and sign in again. If the problem continues, check that your laptop clock is "
    "correct because the certificate is time sensitive. Then run the diagnostics tool from the tray menu."
)


def test_a_short_article_is_one_chunk():
    assert chunk_text(LOREM) == [LOREM]


def test_empty_and_whitespace_only_text_has_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\n \t ") == []


def test_every_chunk_respects_the_size_limit_including_the_overlap():
    body = "\n\n".join(f"Paragraph {i}. " + LOREM for i in range(40))
    chunks = chunk_text(body, max_chars=400, overlap=60)
    assert len(chunks) > 5
    assert all(0 < len(c) <= 400 for c in chunks), max(len(c) for c in chunks)


def test_nothing_is_lost_every_word_of_the_source_survives_in_order():
    body = "\n\n".join(f"Step {i}: " + LOREM for i in range(15))
    chunks = chunk_text(body, max_chars=350, overlap=50)
    joined = " ".join(chunks)
    for i in range(15):
        assert f"Step {i}:" in joined
    # Overlap repeats text, never reorders it: the step numbers first appear in increasing order.
    firsts = [joined.index(f"Step {i}:") for i in range(15)]
    assert firsts == sorted(firsts)


def test_consecutive_chunks_share_context_at_the_boundary():
    body = "\n\n".join(f"Section {i}. " + LOREM for i in range(10))
    chunks = chunk_text(body, max_chars=400, overlap=80)
    for before, after in zip(chunks, chunks[1:], strict=False):
        tail_words = before.split()[-3:]
        assert " ".join(tail_words) in after, (before[-80:], after[:120])


def test_a_huge_paragraph_is_split_on_sentences():
    sentences = [f"This is sentence number {i} about resetting the device." for i in range(60)]
    chunks = chunk_text(" ".join(sentences), max_chars=300, overlap=40)
    assert all(len(c) <= 300 for c in chunks)
    assert not any(c.endswith(("sentence number", "about resetting")) for c in chunks[:-1])


def test_a_single_endless_token_cannot_blow_the_limit():
    blob = "x" * 5000  # a base64 blob, a URL
    chunks = chunk_text(f"See {blob} for details.", max_chars=300, overlap=40)
    assert all(len(c) <= 300 for c in chunks)
    assert "".join(c.replace(" ", "") for c in chunks).count("x") >= 5000


def test_unicode_and_windows_newlines_are_handled():
    body = "Reiniciá el cliente VPN.\r\n\r\nLuego iniciá sesión de nuevo — ¿funcionó? 完成\r\n"
    chunks = chunk_text(body)
    assert chunks == ["Reiniciá el cliente VPN.\n\nLuego iniciá sesión de nuevo — ¿funcionó? 完成"]


def test_it_is_deterministic():
    body = "\n\n".join(LOREM for _ in range(30))
    assert chunk_text(body) == chunk_text(body)


def test_an_overlap_that_leaves_no_room_is_rejected():
    with pytest.raises(ValueError):
        chunk_text("anything", max_chars=100, overlap=60)
