from engine.handlers.file_handler import FileOpHandler

# Every step type AutoApp can run. Adding a handler here adds it to the catalog the job editor reads.
HANDLERS = [FileOpHandler]

HANDLER_REGISTRY = {handler.CODE: handler for handler in HANDLERS}


def get_handler(step_type: str):
    """
    Factory method to retrieve the correct handler class based on step type string.
    Raises a standard ValueError if the step type is unknown.
    """
    normalized = step_type.strip().upper().replace(" ", "_")
    handler_cls = HANDLER_REGISTRY.get(normalized)
    if not handler_cls:
        raise ValueError(f"Unknown step type: {step_type}")
    return handler_cls
