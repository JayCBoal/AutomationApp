import glob
import hashlib
import os
import shutil
from pathlib import Path
from core import job_log
from core.handlers.base_handler import BaseHandler
from core.rename_mask import new_names
from core.step_catalog import BOOLEAN, DEST, LOCATION, NUMBER, SOURCE, STRING, PARTLY_DONE, Output, Param
from core.telemetry_client import utc_now_iso


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
    """

    CODE = "COPY_FILES"
    FAILURE_KNOWLEDGE = PARTLY_DONE
    NAME = "Copy Files"
    DESCRIPTION = "Copies or moves files between a registered endpoint and the job's working folder"

    PARAMETERS = (
        Param("Source", LOCATION, location_role=SOURCE, required=True,
              description="The files to take. A pattern such as *.csv matches several."),
        Param("Dest", LOCATION, location_role=DEST, required=True,
              description="The folder to put them in, or a new filename when one file is taken"),
        Param("RenameMask", STRING, file_placeholders=True,
              description="A new name for each file, such as ${FILE:STEM}_${DATE:yyyyMMdd}${FILE:EXT}. "
                          "${FILE:NAME} is the file's own name, ${FILE:STEM} its name without the extension, "
                          "${FILE:EXT} its extension."),
        Param("Move", BOOLEAN, default="False",
              description="Remove each file from the source once it has arrived"),
        Param("CreateFolder", BOOLEAN, default="True",
              description="Create the destination folder if it does not exist"),
        Param("Checksum", BOOLEAN, default="False",
              description="Record each file's SHA-256 and verify the copy against it"),
        Param("AllowNoFiles", BOOLEAN, default="False",
              description="Succeed when no files match. Otherwise a step that finds nothing fails."),
    )
    OUTPUTS = (
        Output("FileCount", NUMBER, "How many files it copied or moved"),
        Output("Bytes", NUMBER, "How many bytes it copied or moved, in all"),
    )

    def execute_step(self, params: dict) -> dict:
        source_pattern, dest_path = params["Source"], params["Dest"]
        move, create_folder = params["Move"], params["CreateFolder"]
        verify_checksum, allow_no_files = params["Checksum"], params["AllowNoFiles"]
        rename_mask = params.get("RenameMask")
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

        # Ensure destination folder exists if CreateFolder=True.
        # With a rename mask, Dest is always the folder; the mask supplies each filename.
        dest_dir = Path(dest_path).parent if Path(dest_path).suffix and not rename_mask else Path(dest_path)
        if create_folder and not dest_dir.exists():
            dest_dir.mkdir(parents=True, exist_ok=True)

        # Resolve source files (supports glob patterns)
        matched_files = sorted(f for f in glob.glob(source_pattern) if os.path.isfile(f))
        job_log.debug(f"Files matching '{source_pattern}': {matched_files}")
        carried = self.journal.finished_earlier()       # files an earlier attempt of this step already did
        self.outputs.update(FileCount=len(carried), Bytes=sum(r.get("size") or 0 for r in carried))
        if not matched_files and not carried:
            if not allow_no_files:
                # Finding nothing usually means something upstream is late or broken
                raise FileNotFoundError(
                    f"No files matched '{source_pattern}'. "
                    f"If that is acceptable for this step, set AllowNoFiles to True."
                )
            job_log.warning(f"No files matched '{source_pattern}'")
            result_data["details"]["summary"].append("No files matched; nothing was done.")
            return result_data

        # A Dest that names one file can take one file. Several would each overwrite the last.
        if dest_dir != Path(dest_path) and len(matched_files) > 1:
            raise ValueError(
                f"'Dest' names a single file ('{os.path.basename(dest_path)}'), but {len(matched_files)} files "
                f"matched '{source_pattern}'. Give a folder as 'Dest' to keep each file's own name."
            )

        # Work out every new name before copying anything, so a mask that cannot work stops the step first
        names = [os.path.basename(f) for f in matched_files]
        renamed = new_names(rename_mask, names) if rename_mask else {name: name for name in names}

        already = {r["src"] for r in carried} | self._settle_unfinished(move)
        total_bytes = self.outputs["Bytes"]

        for src_file in matched_files:
            if src_file in already:
                job_log.detail(f"Skipped '{src_file}': the earlier attempt already did it.")
                continue
            filename = renamed[os.path.basename(src_file)]
            target = os.path.join(dest_path, filename) if dest_dir == Path(dest_path) else dest_path

            started_at = utc_now_iso()
            source_size = dest_size = checksum = None
            try:
                source_size = os.path.getsize(src_file)
                if verify_checksum:
                    checksum = _sha256(src_file)
                self.journal.begin(src_file, target, source_size, checksum)

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

            self.journal.end(src_file, target, dest_size, checksum)
            self.record_file_operation(op_type, "SUCCESS", src_file, target, source_size, dest_size,
                                       checksum, started_at=started_at)
            job_log.detail(f"{done} '{src_file}'\n\tto '{target}' ({dest_size} bytes)")
            total_bytes += dest_size
            self.outputs.update(FileCount=self.outputs["FileCount"] + 1, Bytes=total_bytes)
            result_data["details"]["ops"].append({
                "OpType": op_type,
                "Source": src_file,
                "Dest": target,
                "BytesTransferred": dest_size,
                "Status": "SUCCESS"
            })

        result_data["bytes_transferred"] = total_bytes
        result_data["details"]["summary"].append(f"{done} {self.outputs['FileCount']} file(s), {total_bytes} bytes.")

        return result_data

    def _settle_unfinished(self, move: bool) -> set:
        """
        Files the earlier attempt had begun but not noted as done. One whose copy is complete at its
        destination (by size, and by checksum where it was recorded) is done: noted now, and for a move its
        source removed. Any other is done again. Returns the sources settled as done.
        """
        settled = set()
        for earlier in self.journal.unfinished_earlier():
            dest = earlier.get("dest")
            complete = dest and os.path.isfile(dest) and os.path.getsize(dest) == earlier.get("size") \
                and (not earlier.get("checksum") or _sha256(dest) == earlier["checksum"])
            if not complete:
                job_log.detail(f"'{earlier['src']}' was being copied when the earlier attempt stopped; it is done again.")
                continue
            if move and os.path.isfile(earlier["src"]):
                os.remove(earlier["src"])
            self.journal.end(earlier["src"], dest, earlier["size"], earlier.get("checksum"))
            self.outputs.update(FileCount=self.outputs["FileCount"] + 1, Bytes=self.outputs["Bytes"] + earlier["size"])
            job_log.detail(f"'{earlier['src']}' had arrived complete when the earlier attempt stopped.")
            settled.add(earlier["src"])
        return settled
