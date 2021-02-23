"""Tests for the base62 codec."""

import pytest

from app.codec import ALPHABET, BASE, CODE_LENGTH, decode, encode


class TestEncode:
    def test_zero(self):
        assert encode(0) == "0"

    def test_known_values(self):
        assert encode(1) == "1"
        assert encode(61) == "z"
        assert encode(62) == "10"
        assert encode(62 ** 2) == "100"

    def test_large_value(self):
        n = 62 ** 6 - 1
        result = encode(n)
        assert len(result) == 6
        assert all(c in ALPHABET for c in result)

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            encode(-1)


class TestDecode:
    def test_zero(self):
        assert decode("0") == 0

    def test_single_digit(self):
        assert decode("z") == 61

    def test_two_digits(self):
        assert decode("10") == 62

    def test_invalid_char_raises(self):
        with pytest.raises(ValueError):
            decode("!")


class TestRoundTrip:
    def test_round_trip_small(self):
        for n in range(200):
            assert decode(encode(n)) == n

    def test_round_trip_large(self):
        for n in [999_999, 1_234_567, 62 ** 5, 62 ** 6 - 1]:
            assert decode(encode(n)) == n
