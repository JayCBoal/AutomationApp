"""
Date and time masks: ${DATE:yyyyMMdd}, ${DATE:yyyy-MM-dd_HHmmss}, ...

The mask letters are the ones .NET uses, where case tells months from minutes:

    yyyy  2026        yy    26
    MMMM  October     MMM   Oct       MM  10      M  10      (months: capital M)
    dddd  Tuesday     ddd   Tue       dd  06      d  6
    HH    14          H     14        (24-hour)   hh  02     h  2     (12-hour)
    mm    05          m     5         (minutes: small m)
    ss    09          s     9         fff 042     (milliseconds)
    tt    PM

Anything that is not a letter is copied as it is: - _ . : / and spaces.
Text in single quotes is copied as it is: yyyyMMdd'T'HHmm gives 20261013T1405.
Any other letter is an error, so a mask written in the wrong case, such as
YYYYMMDD, is refused instead of quietly producing the wrong text.
"""
import re
from datetime import datetime

_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"]
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_TOKENS = {
    "yyyy": lambda t: f"{t.year:04d}",
    "yy": lambda t: f"{t.year % 100:02d}",
    "MMMM": lambda t: _MONTHS[t.month - 1],
    "MMM": lambda t: _MONTHS[t.month - 1][:3],
    "MM": lambda t: f"{t.month:02d}",
    "M": lambda t: str(t.month),
    "dddd": lambda t: _DAYS[t.weekday()],
    "ddd": lambda t: _DAYS[t.weekday()][:3],
    "dd": lambda t: f"{t.day:02d}",
    "d": lambda t: str(t.day),
    "HH": lambda t: f"{t.hour:02d}",
    "H": lambda t: str(t.hour),
    "hh": lambda t: f"{(t.hour % 12) or 12:02d}",
    "h": lambda t: str((t.hour % 12) or 12),
    "mm": lambda t: f"{t.minute:02d}",
    "m": lambda t: str(t.minute),
    "ss": lambda t: f"{t.second:02d}",
    "s": lambda t: str(t.second),
    "fff": lambda t: f"{t.microsecond // 1000:03d}",
    "tt": lambda t: "AM" if t.hour < 12 else "PM",
}

# Longest first, so that MMMM is not read as MM followed by MM
_PIECE = re.compile(
    "|".join(sorted(map(re.escape, _TOKENS), key=len, reverse=True))     # a mask token
    + r"|'[^']*'"                                                          # 'literal text'
    + r"|[A-Za-z]"                                                         # a letter that is not a token: an error
    + r"|[^A-Za-z']+"                                                      # punctuation, digits and spaces
)

_HINT = ("Use yyyy for the year, MM for the month, dd for the day, HH for the hour, mm for the minute "
         "and ss for the second; put other text in single quotes.")


def format_date(mask: str, moment: datetime) -> str:
    """Applies a mask to a date and time. Raises ValueError for a mask that is not understood."""
    if not mask or not mask.strip():
        raise ValueError(f"A date placeholder needs a mask, for example ${{DATE:yyyyMMdd}}. {_HINT}")
    if mask.count("'") % 2:
        raise ValueError(f"The date mask '{mask}' has a single quote that is never closed.")

    out = []
    for piece in _PIECE.findall(mask):
        if piece in _TOKENS:
            out.append(_TOKENS[piece](moment))
        elif piece.startswith("'"):
            out.append(piece[1:-1])
        elif piece[0].isalpha():
            raise ValueError(f"'{piece}' in the date mask '{mask}' is not understood. {_HINT}")
        else:
            out.append(piece)
    return "".join(out)
