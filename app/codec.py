"""Base62 codec for generating short URL codes."""

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(ALPHABET)
CODE_LENGTH = 6

__all__ = ["ALPHABET", "BASE", "CODE_LENGTH", "encode", "decode", "pad"]


def encode(n: int) -> str:
    """Encode a non-negative integer to a base62 string."""
    if n < 0:
        raise ValueError("Cannot encode negative integers")
    if n == 0:
        return ALPHABET[0]
    digits = []
    while n:
        digits.append(ALPHABET[n % BASE])
        n //= BASE
    return "".join(reversed(digits))


def decode(s: str) -> int:
    """Decode a base62 string to a non-negative integer."""
    result = 0
    for char in s:
        if char not in ALPHABET:
            raise ValueError(f"Invalid base62 character: {char!r}")
        result = result * BASE + ALPHABET.index(char)
    return result


def pad(s: str, length: int = CODE_LENGTH) -> str:
    """Left-pad a base62 string with '0' to a fixed length."""
    return s.rjust(length, ALPHABET[0])
