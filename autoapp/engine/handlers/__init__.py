from engine.handlers.file_handler import FileOpHandler

HANDLER_REGISTRY = {
    "FILE_OP": FileOpHandler,
    "COPY_FILES": FileOpHandler,
}

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