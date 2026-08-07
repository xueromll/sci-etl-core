from __future__ import annotations


def truncate_to_tokens(text: str, max_tokens: int, encoding_name: str = "cl100k_base") -> str | None:
    """Truncate ``text`` to at most ``max_tokens`` using ``tiktoken``.

    Returns ``None`` when ``tiktoken`` is not installed, signaling callers to
    fall back to character-based truncation.
    """
    try:
        import tiktoken
    except ImportError:
        return None

    encoding = tiktoken.get_encoding(encoding_name)
    tokens = encoding.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return encoding.decode(tokens[:max_tokens])
