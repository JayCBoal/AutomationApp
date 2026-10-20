"""The one error a workflow save can fail with, shared by the modules that check a workflow."""


class WorkflowError(Exception):
    """A workflow that cannot be saved as submitted; the message says why, for the person saving it."""
