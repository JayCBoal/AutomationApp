"""
Lists of return codes, as written in a job's Success return codes and in a workflow's
prerequisites: "0", "0, 4", "0-4", "0-4, 8". Whole numbers from 0 up; spaces don't matter.
"""
from typing import List, Optional, Tuple

DEFAULT_SUCCESS = "0"


def parse(text: str) -> List[Tuple[int, int]]:
    """The list as (lowest, highest) pairs. Raises ValueError, saying what is wrong, for one that cannot be read."""
    if not text or not text.strip():
        raise ValueError("No return codes were given. Write them as 0, or 0, 4, or 0-4.")
    ranges = []
    for piece in text.split(","):
        piece = piece.strip()
        low, dash, high = piece.partition("-")
        if not low.strip().isdigit() or (dash and not high.strip().isdigit()):
            raise ValueError(f"'{piece}' in '{text}' is not a return code or a range of them. "
                             f"Write whole numbers from 0, as 0, or 0, 4, or 0-4.")
        low_number, high_number = int(low), int(high) if dash else int(low)
        if high_number < low_number:
            raise ValueError(f"The range '{piece}' in '{text}' runs backwards. Write the lower code first, as 0-4.")
        ranges.append((low_number, high_number))
    return ranges


def problem(text: Optional[str]) -> Optional[str]:
    """Why the list cannot be read, or None if it can."""
    try:
        parse(text or "")
    except ValueError as e:
        return str(e)
    return None


def matches(code: Optional[int], text: Optional[str]) -> bool:
    """Whether the code is in the list. No code (the job never ran) is in no list."""
    if code is None:
        return False
    return any(low <= code <= high for low, high in parse(text or DEFAULT_SUCCESS))


def normal(text: Optional[str]) -> Optional[str]:
    """The list written tidily ("0,4" gives "0, 4"); empty stays None."""
    if not text or not text.strip():
        return None
    return ", ".join(str(low) if low == high else f"{low}-{high}" for low, high in parse(text))
