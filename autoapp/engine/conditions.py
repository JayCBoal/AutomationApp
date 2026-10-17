"""
Conditions for If, ElseIf and While, written as a SQL WHERE clause (see docs/FLOW_CONTROL.md):

    %{Check_files.Status} = 'SUCCESS' AND %{File.Size} > ${MinBytes}

SQLite, which comes with Python, works them out, in a database of its own that
holds nothing and is only allowed to compute values. How values go in:

  - inside quotes, a %{...} or ${...} is filled in as text, any quote in it doubled,
    so nothing in a value can end the text early: '%{File.BaseName}_old';
  - outside quotes, a value is handed to SQLite separately (a "bound parameter"), never
    pasted into the condition, so a value cannot change what the condition means. A
    number stays a number; a variable's text that reads as a number counts as one.

Double quotes are accepted for text too, and mean the same as single quotes.
"""
import re
import sqlite3
from typing import Any, Callable, List, Optional, Tuple

NUMBER, STRING = "NUMBER", "STRING"

# The pieces a condition is cut into, outside quotes and placeholders
_PIECE = re.compile(r"(?P<number>\d+(?:\.\d+)?)|(?P<word>[A-Za-z_][A-Za-z0-9_]*)|(?P<op><>|!=|<=|>=|==|=|<|>)"
                    r"|(?P<space>\s+)|(?P<other>.)", re.S)
_LOOKS_NUMERIC = re.compile(r"^\s*-?\d+(\.\d+)?\s*$")
# Words that start or end the operands of a comparison, for the text-against-number check
_JOINERS = {"AND", "OR", "NOT", "("}
_ENDERS = {"AND", "OR", ")"}


class Token:
    """One piece of a condition: kind is STRING, REF, NUMBER, WORD, OP or OTHER."""
    def __init__(self, kind: str, text: str, parts: Optional[list] = None):
        self.kind, self.text, self.parts = kind, text, parts or []

    @property
    def upper(self) -> str:
        return self.text.upper()


def _placeholder_end(text: str, start: int) -> int:
    end = text.find("}", start)
    if end < 0:
        raise ValueError(f"'{text[start:]}' has no closing }}.")
    return end + 1


def _quoted(text: str, start: int) -> Tuple[Token, int]:
    """Text in quotes, as a STRING token whose parts are plain text and placeholders."""
    quote, i, parts, plain = text[start], start + 1, [], ""
    while i < len(text):
        if text[i] == quote:
            if text[i + 1:i + 2] == quote:          # a doubled quote is the quote itself
                plain, i = plain + quote, i + 2
                continue
            parts.append(plain)
            return Token(STRING, text[start:i + 1], parts), i + 1
        if text.startswith(("%{", "${"), i):
            end = _placeholder_end(text, i)
            parts += [plain, Token("REF", text[i:end])]
            plain, i = "", end
            continue
        plain, i = plain + text[i], i + 1
    raise ValueError(f"The text starting {text[start:start + 20]} has no closing {quote}.")


def tokens(text: str) -> List[Token]:
    """Cuts a condition into its pieces. Raises ValueError for unclosed quotes or placeholders."""
    found, i = [], 0
    while i < len(text):
        if text[i] in "'\"":
            token, i = _quoted(text, i)
        elif text.startswith(("%{", "${"), i):
            end = _placeholder_end(text, i)
            token, i = Token("REF", text[i:end]), end
        else:
            match = _PIECE.match(text, i)
            kind = match.lastgroup
            i = match.end()
            if kind == "space":
                continue
            token = Token({"number": NUMBER, "word": "WORD", "op": "OP"}.get(kind, "OTHER"), match.group(0))
        found.append(token)
    return found


def _as_text(value: Any) -> str:
    return "" if value is None else str(value)


def _bound(token: Token, value: Any) -> Any:
    """A value as SQLite gets it: a variable's numeric text as a number, True/False as 1/0."""
    if isinstance(value, bool):
        return int(value)
    if token.text.startswith("${") and isinstance(value, str) and _LOOKS_NUMERIC.match(value):
        return float(value) if "." in value else int(value)
    return value


def _compile(found: List[Token], value_of: Callable[[str], Any]) -> Tuple[str, list]:
    """The condition as SQLite runs it, and the values handed to it separately."""
    sql, values = [], []
    for token in found:
        if token.kind == STRING:
            content = "".join(p if isinstance(p, str) else _as_text(value_of(p.text)) for p in token.parts)
            sql.append("'" + content.replace("'", "''") + "'")
        elif token.kind == "REF":
            sql.append("?")
            values.append(_bound(token, value_of(token.text)))
        else:
            sql.append(token.text)
    return " ".join(sql), values


def _only_compute(action, *_):
    """SQLite's authorizer: a condition may compute values and nothing else."""
    return sqlite3.SQLITE_OK if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION) else sqlite3.SQLITE_DENY


def _plain(message: str) -> str:
    """SQLite's complaint, in the app's own words."""
    patterns = [
        (r"no such column: (.+)", "'{0}' is not a value. Put text in quotes ('{0}'), or write %{{Name.Output}} "
                                  "for a value from the run."),
        # The condition is run inside brackets of our own, so this ")" is where it ran out
        (r'near "\)": syntax error', "The condition stops before it is complete."),
        (r'near "(.+)": syntax error', "The condition is not valid near '{0}'."),
        (r"incomplete input", "The condition stops before it is complete."),
        (r"no such function: (.+)", "There is no function called {0}."),
        (r"wrong number of arguments to function (.+)\(\)", "The function {0} was given the wrong number of values."),
        (r"You can only execute one statement at a time.*", "A condition cannot hold a ';'."),
        (r"not authorized", "A condition can only compute values; it cannot read or change anything."),
    ]
    for pattern, wording in patterns:
        match = re.match(pattern, message)
        if match:
            return wording.format(*match.groups())
    return f"The condition is not valid: {message}."


def _run(sql: str, values: list) -> bool:
    connection = sqlite3.connect(":memory:")
    connection.set_authorizer(_only_compute)
    try:
        row = connection.execute(f"SELECT CASE WHEN ({sql}) THEN 1 ELSE 0 END", values).fetchone()
    except (sqlite3.Error, sqlite3.Warning, OverflowError) as e:
        raise ValueError(_plain(str(e))) from None
    finally:
        connection.close()
    return bool(row[0])


def _refs(found: List[Token]) -> List[str]:
    """Every placeholder in the condition, in or out of quotes, once each, in order."""
    seen = []
    for token in found:
        for ref in ([token] if token.kind == "REF" else [p for p in token.parts if isinstance(p, Token)]):
            if ref.text not in seen:
                seen.append(ref.text)
    return seen


def mismatches(found: List[Token], type_of: Callable[[str], Optional[str]]) -> List[str]:
    """
    Comparisons of text with a number, where both sides are known: a number is never equal
    to text, and sorts before all of it. Only simple sides are looked at: a value, a quoted
    text or a placeholder, between AND, OR, NOT or brackets.
    """
    def kind_of(token: Token) -> Optional[str]:
        if token.kind in (NUMBER, STRING):
            return token.kind
        return type_of(token.text) if token.kind == "REF" else None

    warnings = []
    for i, token in enumerate(found):
        if token.kind != "OP" or i == 0 or i == len(found) - 1:
            continue
        left, right = found[i - 1], found[i + 1]
        if i >= 2 and found[i - 2].upper not in _JOINERS:
            continue
        if i + 2 < len(found) and found[i + 2].upper not in _ENDERS:
            continue
        sides = {kind_of(left), kind_of(right)}
        if sides == {NUMBER, STRING}:
            warnings.append(f"{left.text} {token.text} {right.text} compares a number with text: they are never "
                            f"equal, and a number always counts as less. Quote both sides, or neither.")
    return warnings


def check(text: str, variable: Callable[[str], str],
          run_value_type: Callable[[str], Tuple[Optional[str], Optional[str]]]) -> Tuple[List[str], List[str]]:
    """
    Checks a condition before the run. variable(placeholder) gives a ${...} its value, raising
    ValueError if it has none; run_value_type(placeholder) says of a %{...} (problem, kind).
    Returns (problems, warnings).
    """
    try:
        found = tokens(text)
    except ValueError as e:
        return [str(e)], []
    problems, kinds = [], {}
    for ref in _refs(found):
        if ref.startswith("${"):
            try:
                value = variable(ref)
                kinds[ref] = None if "${" in value else (NUMBER if _LOOKS_NUMERIC.match(value) else STRING)
            except ValueError as e:
                problems.append(str(e))
        else:
            problem, kinds[ref] = run_value_type(ref)
            if problem:
                problems.append(problem)
    try:
        _run(*_compile(found, lambda ref: None))
    except ValueError as e:
        problems.append(str(e))
    return problems, mismatches(found, kinds.get)


def evaluate(text: str, value_of: Callable[[str], Any]) -> Tuple[bool, List[str], List[str]]:
    """
    Works a condition out during the run. value_of(placeholder) gives any placeholder its value.
    Returns (whether it holds, the values it used as "name = value", warnings). NULL counts as false.
    """
    found = tokens(text)
    values = {ref: value_of(ref) for ref in _refs(found)}
    used = [f"{ref} = {'NULL' if value is None else repr(_bound(Token('REF', ref), value))}"
            for ref, value in values.items()]

    def kind(ref):
        value = _bound(Token("REF", ref), values[ref])
        return None if value is None else (NUMBER if isinstance(value, (int, float)) else STRING)
    return _run(*_compile(found, values.get)), used, mismatches(found, kind)
