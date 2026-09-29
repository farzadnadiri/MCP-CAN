from typing import Union

IntLike = Union[int, str]


def parse_int(value: IntLike) -> int:
    """Parse an ID/code given as an int or as a decimal/hex string.

    Accepts ``61444``, ``"61444"``, ``"0xF004"`` and bare hex like ``"F004"``.
    Bare digits are always decimal (``"10"`` is 10, not 16). Used by both the
    CLI and the MCP tools: LLMs -- small local ones especially -- tend to
    think in the hex notation automotive docs use and get the hex-to-decimal
    conversion wrong, so tools take the hex string as-is instead.
    """
    if isinstance(value, int):
        return value
    text = value.strip().replace("_", "")
    try:
        if text.lower().startswith("0x"):
            return int(text, 16)
        if text.isdigit():
            return int(text)
        return int(text, 16)
    except ValueError:
        raise ValueError(
            f"{value!r} is not a number; use decimal (61444) or hex ('0xF004')"
        ) from None
