"""Repository paths arrive from git as raw bytes. These helpers keep them lossless."""


def match_text(raw):
    """Text used for glob matching. Undecodable bytes become distinct lone surrogates."""
    return raw.decode("utf-8", "surrogateescape")


def display_path(raw):
    """Text used in findings: valid UTF-8 as is, other bytes as \\xNN escapes."""
    return raw.decode("utf-8", "backslashreplace")


def unsafe_path_reason(text):
    """Why `text` is not an acceptable repository path, or None if it is."""
    if text == "":
        return "empty path"
    if "\x00" in text:
        return "NUL in path"
    if text.startswith("/"):
        return "absolute path"
    for segment in text.split("/"):
        if segment == "":
            return "empty path segment"
        if segment in (".", ".."):
            return "dot segment"
    return None
