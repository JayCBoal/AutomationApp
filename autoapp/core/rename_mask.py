"""
Rename masks: giving each file a step handles a new name on the way.

A mask is ordinary text with placeholders for parts of the file's own name:

    ${FILE:NAME}   the whole name          Legal_Batch_1.csv
    ${FILE:STEM}   without the extension   Legal_Batch_1
    ${FILE:EXT}    the extension           .csv      (with its full stop; empty if there is none)

so  ${FILE:STEM}_${DATE:yyyyMMdd}${FILE:EXT}  turns Legal_Batch_1.csv into Legal_Batch_1_20261013.csv.

Every other placeholder in a mask (${DATE:...}, variables) is resolved once, before the
job starts. The ${FILE:...} ones are filled in here, once for each file.
"""
import os
import re
from typing import Dict, List

PLACEHOLDERS = ("NAME", "STEM", "EXT")
_FILE_PLACEHOLDER = re.compile(r"\$\{FILE:([^}]*)\}")


def check_mask(mask: str) -> None:
    """Raises ValueError if the mask uses a ${FILE:...} placeholder that does not exist."""
    for name in _FILE_PLACEHOLDER.findall(mask):
        if name not in PLACEHOLDERS:
            allowed = ", ".join(f"${{FILE:{p}}}" for p in PLACEHOLDERS)
            raise ValueError(f"${{FILE:{name}}} is not a file placeholder. A rename mask can use {allowed}.")


def new_name(mask: str, filename: str) -> str:
    """The name the mask gives a file. Raises ValueError if the result cannot be a filename."""
    stem, extension = os.path.splitext(filename)
    parts = {"NAME": filename, "STEM": stem, "EXT": extension}
    renamed = _FILE_PLACEHOLDER.sub(lambda match: parts[match.group(1)], mask)
    if not renamed.strip() or "/" in renamed or "\\" in renamed or renamed in (".", ".."):
        raise ValueError(f"The rename mask '{mask}' turns '{filename}' into '{renamed}', which is not a filename.")
    return renamed


def new_names(mask: str, filenames: List[str]) -> Dict[str, str]:
    """
    The new name for each file. Raises ValueError if two files would get the same
    name, which happens when a mask leaves out the file's own name.
    """
    check_mask(mask)
    renamed = {filename: new_name(mask, filename) for filename in filenames}
    seen: Dict[str, str] = {}
    for filename, target in renamed.items():
        if target in seen:
            raise ValueError(
                f"The rename mask '{mask}' gives '{seen[target]}' and '{filename}' the same name, '{target}'. "
                f"Include ${{FILE:NAME}} or ${{FILE:STEM}} in the mask so that each file keeps a name of its own."
            )
        seen[target] = filename
    return renamed
