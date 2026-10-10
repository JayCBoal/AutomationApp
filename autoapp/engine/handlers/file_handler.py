import glob
import os
import shutil
from pathlib import Path
from engine.handlers.base_handler import BaseHandler


class FileOpHandler(BaseHandler):
    """
    Execution plugin for managing local file system operations (copy, move)
    within the AutoApp engine.
    """

    def execute_step(self, resolved_params: dict) -> dict:
        source_pattern = resolved_params.get("Source")
        dest_path = resolved_params.get("Dest")
        move = str(resolved_params.get("Move", "False")).lower() in ("true", "1", "yes")
        create_folder = str(resolved_params.get("CreateFolder", "True")).lower() in ("true", "1", "yes")

        result_data = {
            "source_path": source_pattern,
            "dest_path": dest_path,
            "bytes_transferred": 0,
            "details": {
                "summary": [],
                "ops": []
            }
        }

        # Ensure destination folder exists if CreateFolder=True
        dest_dir = Path(dest_path).parent if Path(dest_path).suffix else Path(dest_path)
        if create_folder and not dest_dir.exists():
            dest_dir.mkdir(parents=True, exist_ok=True)

        # Resolve source files (supports glob patterns)
        matched_files = glob.glob(source_pattern)
        if not matched_files:
            result_data["details"]["summary"].append(f"No files matched source pattern: {source_pattern}")
            return result_data

        total_bytes = 0
        processed_count = 0

        for src_file in matched_files:
            filename = os.path.basename(src_file)
            target = os.path.join(dest_path, filename) if dest_dir == Path(dest_path) else dest_path

            if move:
                shutil.move(src_file, target)
                op_type = "MOVE"
            else:
                shutil.copy2(src_file, target)
                op_type = "COPY"

            file_size = os.path.getsize(target)
            total_bytes += file_size
            processed_count += 1

            result_data["details"]["ops"].append({
                "OpType": op_type,
                "Source": src_file,
                "Dest": target,
                "BytesTransferred": file_size,
                "Status": "SUCCESS"
            })

        # Set summary and primary metrics for telemetry logging
        result_data["bytes_transferred"] = total_bytes
        result_data["source_filename"] = os.path.basename(source_pattern)
        result_data["dest_filename"] = os.path.basename(dest_path)
        result_data["details"]["summary"].append(
            f"Successfully processed {processed_count} file(s) from '{source_pattern}' to '{dest_path}'."
        )

        return result_data