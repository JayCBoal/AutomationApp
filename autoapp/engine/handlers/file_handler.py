import glob
import hashlib
import os
import shutil
from pathlib import Path
from engine import job_log
from engine.handlers.base_handler import BaseHandler
from engine.telemetry_client import utc_now_iso


def _is_true(value) -> bool:
    return str(value).lower() in ("true", "1", "yes")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class FileOpHandler(BaseHandler):
    """
    Execution plugin for managing local file system operations (copy, move)
    within the AutoApp engine.

    Parameters: Source, Dest, Move (default False), CreateFolder (default True),
    Checksum (default False: when True, the file's SHA-256 is recorded and the
    copy is verified against it), AllowNoFiles (default False: a step that finds
    no files to handle fails, unless this is True).
    """

    PATH_PARAMS = {"Source": "source", "Dest": "dest"}

    def execute_step(self, resolved_params: dict) -> dict:
        source_pattern = resolved_params.get("Source")
        dest_path = resolved_params.get("Dest")
        if not source_pattern or not dest_path:
            raise ValueError("A file step needs both a source (Source or SourceEndpoint) and a destination (Dest or DestEndpoint).")
        move = _is_true(resolved_params.get("Move", "False"))
        create_folder = _is_true(resolved_params.get("CreateFolder", "True"))
        verify_checksum = _is_true(resolved_params.get("Checksum", "False"))
        allow_no_files = _is_true(resolved_params.get("AllowNoFiles", "False"))
        op_type = "MOVE" if move else "COPY"
        done = "Moved" if move else "Copied"

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
        matched_files = sorted(f for f in glob.glob(source_pattern) if os.path.isfile(f))
        job_log.debug(f"Files matching '{source_pattern}': {matched_files}")
        if not matched_files:
            if not allow_no_files:
                # Finding nothing usually means something upstream is late or broken
                raise FileNotFoundError(
                    f"No files matched '{source_pattern}'. "
                    f"If that is acceptable for this step, set AllowNoFiles to True."
                )
            job_log.warning(f"No files matched '{source_pattern}'")
            result_data["details"]["summary"].append("No files matched; nothing was done.")
            return result_data

        total_bytes = 0

        for src_file in matched_files:
            filename = os.path.basename(src_file)
            target = os.path.join(dest_path, filename) if dest_dir == Path(dest_path) else dest_path

            started_at = utc_now_iso()
            source_size = dest_size = checksum = None
            try:
                source_size = os.path.getsize(src_file)
                if verify_checksum:
                    checksum = _sha256(src_file)

                if move:
                    shutil.move(src_file, target)
                else:
                    shutil.copy2(src_file, target)

                dest_size = os.path.getsize(target)
                if dest_size != source_size:
                    raise IOError(
                        f"Size mismatch for '{filename}': {source_size} bytes at the source, "
                        f"{dest_size} bytes at the destination."
                    )
                if verify_checksum and _sha256(target) != checksum:
                    raise IOError(f"Checksum mismatch for '{filename}': the destination file differs from the source.")
            except Exception as e:
                self.record_file_operation(op_type, "FAILED", src_file, target, source_size, dest_size,
                                           checksum, error=str(e), started_at=started_at)
                job_log.error(f"Could not {op_type.lower()} '{src_file}' to '{target}': {e}")
                raise

            self.record_file_operation(op_type, "SUCCESS", src_file, target, source_size, dest_size,
                                       checksum, started_at=started_at)
            job_log.detail(f"{done} '{src_file}'\n\tto '{target}' ({dest_size} bytes)")
            total_bytes += dest_size
            result_data["details"]["ops"].append({
                "OpType": op_type,
                "Source": src_file,
                "Dest": target,
                "BytesTransferred": dest_size,
                "Status": "SUCCESS"
            })

        result_data["bytes_transferred"] = total_bytes
        result_data["details"]["summary"].append(f"{done} {len(matched_files)} file(s), {total_bytes} bytes.")

        return result_data
