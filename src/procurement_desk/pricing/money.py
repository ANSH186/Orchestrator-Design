"""Decimal money, Indian-notation, percentage, and rounding utilities.

All financial arithmetic in this project uses :class:`decimal.Decimal`.
Binary floating point is never used for prices, comparisons, or limits.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable

ZERO = Decimal("0")
ONE = Decimal("1")
TWELVE = Decimal("12")
HUNDRED = Decimal("100")

SUPPORTED_CURRENCIES: frozenset[str] = frozenset({"INR", "USD", "EUR", "GBP"})
STANDARD_FX_TO_INR: dict[str, Decimal] = {
    "INR": Decimal("1"),
    "USD": Decimal("84.5"),
    "EUR": Decimal("91"),
    "GBP": Decimal("106"),
}

CURRENCY_ALIASES: dict[str, str] = {
    "₹": "INR",
    "RS": "INR",
    "RS.": "INR",
    "INR": "INR",
    "RUPEE": "INR",
    "RUPEES": "INR",
    "$": "USD",
    "US$": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
}

# Codes that appear in the supplied data or are plausible currency codes.  Any
# currency outside the supported set is missing information per the playbook.
KNOWN_UNSUPPORTED_CURRENCIES: frozenset[str] = frozenset(
    {
        "AED",
        "AFN",
        "ALL",
        "AMD",
        "ANG",
        "AOA",
        "ARS",
        "AUD",
        "AWG",
        "AZN",
        "BAM",
        "BBD",
        "BDT",
        "BGN",
        "BHD",
        "BIF",
        "BMD",
        "BND",
        "BOB",
        "BRL",
        "BSD",
        "BTN",
        "BWP",
        "BYN",
        "BZD",
        "CAD",
        "CDF",
        "CHF",
        "CLP",
        "CNY",
        "COP",
        "CRC",
        "CUP",
        "CVE",
        "CZK",
        "DJF",
        "DKK",
        "DOP",
        "DZD",
        "EGP",
        "ERN",
        "ETB",
        "FJD",
        "FKP",
        "GEL",
        "GHS",
        "GIP",
        "GMD",
        "GNF",
        "GTQ",
        "GYD",
        "HKD",
        "HNL",
        "HTG",
        "HUF",
        "IDR",
        "ILS",
        "IQD",
        "IRR",
        "ISK",
        "JMD",
        "JOD",
        "JPY",
        "KES",
        "KGS",
        "KHR",
        "KMF",
        "KPW",
        "KRW",
        "KWD",
        "KYD",
        "KZT",
        "LAK",
        "LBP",
        "LKR",
        "LRD",
        "LSL",
        "LYD",
        "MAD",
        "MDL",
        "MGA",
        "MKD",
        "MMK",
        "MNT",
        "MOP",
        "MRU",
        "MUR",
        "MVR",
        "MWK",
        "MXN",
        "MYR",
        "MZN",
        "NAD",
        "NGN",
        "NIO",
        "NOK",
        "NPR",
        "NZD",
        "OMR",
        "PAB",
        "PEN",
        "PGK",
        "PHP",
        "PKR",
        "PLN",
        "PYG",
        "QAR",
        "RON",
        "RSD",
        "RUB",
        "RWF",
        "SAR",
        "SBD",
        "SCR",
        "SDG",
        "SEK",
        "SGD",
        "SHP",
        "SLE",
        "SOS",
        "SRD",
        "SSP",
        "STN",
        "SVC",
        "SYP",
        "SZL",
        "THB",
        "TJS",
        "TMT",
        "TND",
        "TOP",
        "TRY",
        "TTD",
        "TWD",
        "TZS",
        "UAH",
        "UGX",
        "UYU",
        "UZS",
        "VES",
        "VND",
        "VUV",
        "WST",
        "XAF",
        "XCD",
        "XOF",
        "XPF",
        "YER",
        "ZAR",
        "ZMW",
        "ZWL",
    }
)


def to_decimal(value: Decimal | int | str | float, *, allow_nan: bool = False) -> Decimal:
    """Safely convert a value to Decimal without float artefacts.

    Floats are converted through their string representation because the CSV
    loader already produces exact-looking decimal source values.
    """

    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("boolean is not a valid Decimal input")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value:
            if allow_nan:
                return Decimal("NaN")
            raise ValueError("NaN is not a valid Decimal input")
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            raise ValueError("empty string is not a valid Decimal input")
        try:
            return Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"invalid decimal value: {value!r}") from exc
    raise TypeError(f"unsupported Decimal input type: {type(value)!r}")


def clean_indian_number(token: str) -> str:
    """Normalise Indian/Western comma formatting and optional scale suffix."""

    text = token.strip().lower().replace(" ", "")
    multiplier = ONE
    if text.endswith("crore"):
        multiplier = Decimal("10000000")
        text = text[: -len("crore")]
    elif text.endswith("lakhs"):
        multiplier = Decimal("100000")
        text = text[: -len("lakhs")]
    elif text.endswith("lakh"):
        multiplier = Decimal("100000")
        text = text[: -len("lakh")]
    elif text.endswith("k"):
        multiplier = Decimal("1000")
        text = text[:-1]

    text = text.replace(",", "")
    if not text:
        raise ValueError("empty numeric token")
    try:
        base = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid numeric token: {token!r}") from exc
    return str(base * multiplier)


ENGLISH_NUMBER_WORDS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
    "thousand": 1000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
}

WORD_NUMBER_PATTERN = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|lakh|lakhs|"
    r"crore|crores|and)"
)


def words_to_int(phrase: str) -> int | None:
    """Convert an English/Indian number phrase to an integer.

    Supports forms such as ``two hundred sixty-six`` and
    ``one lakh seven thousand three hundred``.  Returns ``None`` if a token is
    not a recognised number word.
    """

    tokens = re.findall(r"[a-z]+", phrase.lower())
    if not tokens:
        return None
    total = 0
    current = 0
    seen_number = False
    for token in tokens:
        if token == "and":
            continue
        if token not in ENGLISH_NUMBER_WORDS:
            return None
        seen_number = True
        value = ENGLISH_NUMBER_WORDS[token]
        if value < 100:
            current += value
        elif value == 100:
            if current == 0:
                current = 1
            current *= 100
        elif value == 1000:
            total += current * 1000
            current = 0
        elif value in (100_000, 10_000_000):
            total += current * value
            current = 0
    if not seen_number:
        return None
    return total + current


def parse_percentage(value: str | Decimal | int) -> Decimal:
    """Parse a percentage as a Decimal *without* dividing by 100."""

    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace("%", "").replace("percent", "").strip()
    return to_decimal(text)


def fraction(percent: Decimal | str | int) -> Decimal:
    """Convert a percentage to a fractional multiplier (e.g. 10% -> 0.10)."""

    return parse_percentage(percent) / HUNDRED


def round_half_up_int(value: Decimal) -> int:
    """Round a Decimal to the nearest whole rupee, with exact .5 rounding up."""

    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quantize_rupees(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def decimal_to_plain(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def product(values: Iterable[Decimal], start: Decimal = ONE) -> Decimal:
    result = start
    for value in values:
        result *= value
    return result


def safe_divide(numerator: Decimal, denominator: Decimal, label: str) -> Decimal:
    if denominator == 0:
        raise ValueError(f"division by zero while calculating {label}")
    return numerator / denominator
