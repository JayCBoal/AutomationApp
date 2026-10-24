from core.handlers.file_handler import FileOpHandler
from core.handlers.file_tools import CheckFilesHandler, DeleteFilesHandler, UnzipFilesHandler, ZipFilesHandler
from core.handlers.flow import FLOW_HANDLERS
from core.handlers.set_return_code import SetReturnCodeHandler
from core.handlers.simulate import SimulateHandler
from core.handlers.sql_handler import RunSqlHandler

# Every step type AutoApp can run. Adding a handler here adds it to the catalog the job editor reads.
HANDLERS = [FileOpHandler, DeleteFilesHandler, CheckFilesHandler, ZipFilesHandler, UnzipFilesHandler,
            RunSqlHandler, SimulateHandler, SetReturnCodeHandler] + FLOW_HANDLERS

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
