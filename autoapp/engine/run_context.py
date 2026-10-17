"""
What a run knows about itself as it goes, read in step parameters and conditions as %{...}.

    %{Check_files.Status}    an output of the step named Check_files (see docs/FLOW_CONTROL.md)
    %{File.Name}             a property of the file a For Each File loop is on

${...} is a job-level variable, filled in before the run; %{...} is filled in as each step starts.
"""
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# %{Name.Property}; %{Name} alone is caught so the message can say what to write instead
REFERENCE_PATTERN = re.compile(r"%\{([^}.]*)(?:\.([^}]*))?\}")

# What the file a For Each File loop is on offers, and the kind of value each holds
FILE_PROPERTIES = {
    "Name": "STRING", "BaseName": "STRING", "Extension": "STRING", "FullName": "STRING",
    "Directory": "STRING", "Size": "NUMBER", "Modified": "STRING", "Index": "NUMBER", "Count": "NUMBER",
}

SKIPPED = "SKIPPED"


def references(text: Any) -> List[Tuple[str, Optional[str]]]:
    """The %{...} a value mentions, as (name, property) pairs; property is None for %{Name} alone."""
    if not isinstance(text, str) or "%{" not in text:
        return []
    return [(name, prop) for name, prop in REFERENCE_PATTERN.findall(text)]


def shown_time(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def file_object(path: str, index: int, count: int) -> Dict[str, Any]:
    """The properties of one file, as a loop offers them to the steps inside it."""
    name = os.path.basename(path)
    base, extension = os.path.splitext(name)
    return {
        "Name": name, "BaseName": base, "Extension": extension, "FullName": path,
        "Directory": os.path.dirname(path), "Size": os.path.getsize(path),
        "Modified": shown_time(datetime.fromtimestamp(os.path.getmtime(path))), "Index": index, "Count": count,
    }


class RunContext:
    """Steps' outputs, by StepName, and the files of the loops the run is inside."""

    def __init__(self):
        self.outputs: Dict[str, Dict[str, Any]] = {}
        self.files: Dict[str, Dict[str, Any]] = {}

    def record(self, step_name: str, outputs: Dict[str, Any]) -> None:
        """A step's outputs. A later step of the same name replaces them."""
        self.outputs[step_name] = dict(outputs)

    def value(self, name: str, prop: Optional[str]) -> Any:
        """
        The value of %{name.prop}. A step that has not run has Status SKIPPED and nothing else.
        Raises ValueError for what the pre-run check would have refused.
        """
        if name in self.files:
            if not prop:
                raise ValueError(f"%{{{name}}} is a file, not a value: write %{{{name}.Name}}, "
                                 f"%{{{name}.FullName}} or another of {', '.join(FILE_PROPERTIES)}.")
            if prop not in FILE_PROPERTIES:
                raise ValueError(f"A file has no '{prop}': use one of {', '.join(FILE_PROPERTIES)}.")
            return self.files[name][prop]
        if not prop:
            raise ValueError(f"%{{{name}}} is a step, not a value: write %{{{name}.Status}} or another of its outputs.")
        outputs = self.outputs.get(name)
        if outputs is None:
            return SKIPPED if prop == "Status" else None
        return outputs.get(prop)

    def fill_in(self, text: Any) -> Any:
        """A parameter's text with each %{...} replaced by its value; nothing for an empty one."""
        if not isinstance(text, str) or "%{" not in text:
            return text

        def replace(match):
            found = self.value(match.group(1), match.group(2) or None)
            return "" if found is None else str(found)
        return REFERENCE_PATTERN.sub(replace, text)
