from engine.handlers.file_handler import FileOpHandler
# Future handlers can be imported here:
# from engine.handlers.sql_handler import SQLHandler
# from engine.handlers.rest_handler import RESTHandler

# Registry mapping StepType string from DB to Handler Class
HANDLER_REGISTRY = {
    "FILE_OP": FileOpHandler,
    "COPY_FILES": FileOpHandler,  # Alias mapping for our test configuration
    # "SQL_EXEC": SQLHandler,
    # "REST_CALL": RESTHandler,
}

def get_handler(step_type: str):
    """
    Factory method to retrieve the correct handler class based on step type string.
    """
    handler_cls = HANDLER_REGISTRY.get(step_type)
    if not handler_cls:
        raise ValueError(f"Unsupported StepType: {step_type}")
    return handler_cls