"""
More file steps: Delete Files, Check Files, Zip Files and Unzip Files.

Like Copy Files, each records every file it handles as an operation, so the
operations log and the file trace cover them:

    DELETE     a file removed; the end of its route
    CHECK      a file looked at and found acceptable (or not); it stays where it is
    ZIP        a file put into an archive; ZIP_MOVE if the original was removed
    UNZIP      a file taken out of an archive
"""
import glob
import os
import shutil
import time
import zipfile
from pathlib import Path
from typing import Dict, List

from engine import job_log
from engine.handlers.base_handler import BaseHandler
from engine.step_catalog import BOOLEAN, DEST, INTEGER, LOCATION, SOURCE, STRING, Param
from engine.telemetry_client import utc_now_iso

ALLOW_NO_FILES = Param("AllowNoFiles", BOOLEAN, default="False",
                       description="Succeed when no files match. Otherwise a step that finds nothing fails.")
CREATE_FOLDER = Param("CreateFolder", BOOLEAN, default="True",
                      description="Create the destination folder if it does not exist")


def matching_files(pattern: str) -> List[str]:
    return sorted(f for f in glob.glob(pattern) if os.path.isfile(f))


def nothing_matched(pattern: str, allow: bool, result: Dict, extra: str = "") -> Dict:
    """What a step does when nothing matches: fail, unless that is allowed."""
    if not allow:
        raise FileNotFoundError(f"No files matched '{pattern}'{extra}. "
                                f"If that is acceptable for this step, set AllowNoFiles to True.")
    job_log.warning(f"No files matched '{pattern}'{extra}")
    result["details"]["summary"].append("No files matched; nothing was done.")
    return result


def empty_result() -> Dict:
    return {"details": {"summary": [], "ops": []}}


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class DeleteFilesHandler(BaseHandler):
    CODE = "DELETE_FILES"
    NAME = "Delete Files"
    DESCRIPTION = "Removes files, for example to clear a working folder or to keep only recent archives"

    PARAMETERS = (
        Param("Source", LOCATION, location_role=SOURCE, required=True,
              description="The files to remove. A pattern such as *.csv matches several."),
        Param("OlderThanDays", INTEGER,
              description="Only files last changed more than this many days ago. Leave empty for all matching files."),
        ALLOW_NO_FILES,
    )

    def execute_step(self, params: dict) -> dict:
        pattern, older_than = params["Source"], params.get("OlderThanDays")
        result = empty_result()
        files = matching_files(pattern)
        if older_than is not None:
            cutoff = time.time() - older_than * 86400
            files = [f for f in files if os.path.getmtime(f) < cutoff]
        extra = f" older than {plural(older_than, 'day')}" if older_than is not None else ""
        if not files:
            return nothing_matched(pattern, params["AllowNoFiles"], result, extra)

        for path in files:
            started_at, size = utc_now_iso(), os.path.getsize(path)
            try:
                os.remove(path)
            except OSError as e:
                self.record_file_operation("DELETE", "FAILED", path, None, size, error=str(e), started_at=started_at)
                job_log.error(f"Could not delete '{path}': {e}")
                raise
            self.record_file_operation("DELETE", "SUCCESS", path, None, size, started_at=started_at)
            job_log.detail(f"Deleted '{path}' ({size} bytes)")
        result["details"]["summary"].append(f"Deleted {plural(len(files), 'file')}.")
        return result


class CheckFilesHandler(BaseHandler):
    CODE = "CHECK_FILES"
    NAME = "Check Files"
    DESCRIPTION = "Fails the job unless the files look right: how many there are, none empty, none too old"

    PARAMETERS = (
        Param("Source", LOCATION, location_role=SOURCE, required=True,
              description="The files to check. A pattern such as *.csv matches several."),
        Param("MinCount", INTEGER, default="1", description="At least this many files must match"),
        Param("MaxCount", INTEGER, description="At most this many files may match. Leave empty for no limit."),
        Param("AllowEmpty", BOOLEAN, default="False", description="Accept files with nothing in them"),
        Param("MaxAgeHours", INTEGER,
              description="Every file must have been changed within this many hours. Leave empty for any age."),
    )

    def execute_step(self, params: dict) -> dict:
        pattern = params["Source"]
        least, most = params["MinCount"], params.get("MaxCount")
        allow_empty, max_age = params["AllowEmpty"], params.get("MaxAgeHours")
        result = empty_result()
        files = matching_files(pattern)

        problems = []
        if len(files) < least:
            problems.append(f"{plural(len(files), 'file')} matched '{pattern}'; at least {least} expected.")
        if most is not None and len(files) > most:
            problems.append(f"{plural(len(files), 'file')} matched '{pattern}'; at most {most} expected.")

        now = time.time()
        for path in files:
            started_at, size = utc_now_iso(), os.path.getsize(path)
            wrong = []
            if size == 0 and not allow_empty:
                wrong.append("it is empty")
            if max_age is not None and now - os.path.getmtime(path) > max_age * 3600:
                wrong.append(f"it was last changed more than {plural(max_age, 'hour')} ago")
            if wrong:
                reason = f"'{os.path.basename(path)}': " + " and ".join(wrong) + "."
                problems.append(reason)
                self.record_file_operation("CHECK", "FAILED", path, None, size, error=reason, started_at=started_at)
                job_log.error(f"Check failed for '{path}': {' and '.join(wrong)}")
            else:
                self.record_file_operation("CHECK", "SUCCESS", path, None, size, started_at=started_at)
                job_log.detail(f"Checked '{path}' ({size} bytes)")

        if problems:
            raise ValueError("The files did not pass the check. " + " ".join(problems))
        result["details"]["summary"].append(f"Checked {plural(len(files), 'file')}; all as expected.")
        return result


def archive_path(dest: str, archive_name) -> str:
    """The archive's full path: Dest itself, or ArchiveName inside the folder Dest names."""
    path = os.path.join(dest, archive_name) if archive_name else dest
    if not path.lower().endswith(".zip"):
        raise ValueError(
            f"'{os.path.basename(path)}' is not a .zip file name. Give Dest as the archive's name, such as "
            f"out/batch.zip, or set ArchiveName when Dest is a folder or an endpoint.")
    return path


class ZipFilesHandler(BaseHandler):
    CODE = "ZIP_FILES"
    NAME = "Zip Files"
    DESCRIPTION = "Packs files into one .zip archive"

    PARAMETERS = (
        Param("Source", LOCATION, location_role=SOURCE, required=True,
              description="The files to pack. A pattern such as *.csv matches several."),
        Param("Dest", LOCATION, location_role=DEST, required=True,
              description="The archive to make, such as out/batch_${DATE:yyyyMMdd}.zip; or a folder, with ArchiveName"),
        Param("ArchiveName", STRING,
              description="The archive's name, when Dest is a folder or an endpoint, such as batch_${DATE:yyyyMMdd}.zip"),
        Param("Move", BOOLEAN, default="False", description="Remove each file once it is safely in the archive"),
        Param("Overwrite", BOOLEAN, default="False", description="Replace an archive of the same name if there is one"),
        CREATE_FOLDER,
        ALLOW_NO_FILES,
    )

    def execute_step(self, params: dict) -> dict:
        pattern, move = params["Source"], params["Move"]
        archive = archive_path(params["Dest"], params.get("ArchiveName"))
        op_type = "ZIP_MOVE" if move else "ZIP"
        result = empty_result()
        files = matching_files(pattern)
        if not files:
            return nothing_matched(pattern, params["AllowNoFiles"], result)

        names = [os.path.basename(f) for f in files]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            raise ValueError(f"Two files named '{repeated[0]}' matched '{pattern}'; an archive can hold only one.")
        if os.path.exists(archive) and not params["Overwrite"]:
            raise FileExistsError(f"The archive '{archive}' already exists. Set Overwrite to True to replace it.")
        if params["CreateFolder"]:
            Path(archive).parent.mkdir(parents=True, exist_ok=True)

        started_at = utc_now_iso()
        sizes = {f: os.path.getsize(f) for f in files}
        partial = archive + ".partial"
        try:
            # Written under another name and renamed when complete, so nothing ever sees half an archive
            with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
                for path in files:
                    zipped.write(path, arcname=os.path.basename(path))
            with zipfile.ZipFile(partial) as zipped:
                broken = zipped.testzip()
                if broken:
                    raise IOError(f"'{broken}' was not stored correctly in the archive.")
                for path in files:
                    if zipped.getinfo(os.path.basename(path)).file_size != sizes[path]:
                        raise IOError(f"'{os.path.basename(path)}' is a different size in the archive.")
            os.replace(partial, archive)
        except Exception as e:
            if os.path.exists(partial):
                os.remove(partial)
            for path in files:
                self.record_file_operation(op_type, "FAILED", path, archive, sizes[path], error=str(e), started_at=started_at)
            job_log.error(f"Could not make the archive '{archive}': {e}")
            raise

        archive_size = os.path.getsize(archive)
        for path in files:
            if move:
                os.remove(path)
            self.record_file_operation(op_type, "SUCCESS", path, archive, sizes[path], archive_size, started_at=started_at)
            job_log.detail(f"{'Moved' if move else 'Added'} '{path}'\n\tinto '{archive}'")
        result["details"]["summary"].append(
            f"Put {plural(len(files), 'file')} into {os.path.basename(archive)} ({archive_size} bytes).")
        return result


class UnzipFilesHandler(BaseHandler):
    CODE = "UNZIP_FILES"
    NAME = "Unzip Files"
    DESCRIPTION = "Takes the files out of one or more .zip archives"

    PARAMETERS = (
        Param("Source", LOCATION, location_role=SOURCE, required=True,
              description="The archives to open. A pattern such as *.zip matches several."),
        Param("Dest", LOCATION, location_role=DEST, required=True, description="The folder to put the files in"),
        Param("Overwrite", BOOLEAN, default="False", description="Replace files of the same name that are already there"),
        CREATE_FOLDER,
        ALLOW_NO_FILES,
    )

    def execute_step(self, params: dict) -> dict:
        pattern, dest = params["Source"], params["Dest"]
        result = empty_result()
        archives = matching_files(pattern)
        if not archives:
            return nothing_matched(pattern, params["AllowNoFiles"], result)
        if params["CreateFolder"]:
            Path(dest).mkdir(parents=True, exist_ok=True)
        root = os.path.abspath(dest)

        count = 0
        for archive in archives:
            try:
                zipped = zipfile.ZipFile(archive)
            except zipfile.BadZipFile as e:
                raise ValueError(f"'{os.path.basename(archive)}' is not a readable .zip archive: {e}") from e
            archive_size = os.path.getsize(archive)
            with zipped:
                members = [m for m in zipped.infolist() if not m.is_dir()]
                # Check every name before taking anything out
                for member in members:
                    target = os.path.abspath(os.path.join(root, member.filename))
                    if os.path.commonpath([root, target]) != root:
                        raise ValueError(f"'{member.filename}' in '{os.path.basename(archive)}' would be written outside "
                                         f"the destination folder, so the archive was not opened.")
                    if os.path.exists(target) and not params["Overwrite"]:
                        raise FileExistsError(f"'{target}' already exists. Set Overwrite to True to replace it.")
                for member in members:
                    started_at = utc_now_iso()
                    target = os.path.abspath(os.path.join(root, member.filename))
                    try:
                        Path(target).parent.mkdir(parents=True, exist_ok=True)
                        with zipped.open(member) as inside, open(target, "wb") as out:
                            shutil.copyfileobj(inside, out)
                        size = os.path.getsize(target)
                        if size != member.file_size:
                            raise IOError(f"'{member.filename}' came out a different size from the archive.")
                    except Exception as e:
                        self.record_file_operation("UNZIP", "FAILED", archive, target, archive_size,
                                                   error=str(e), started_at=started_at)
                        job_log.error(f"Could not unzip '{member.filename}' from '{archive}': {e}")
                        raise
                    self.record_file_operation("UNZIP", "SUCCESS", archive, target, archive_size, size,
                                               started_at=started_at)
                    job_log.detail(f"Unzipped '{member.filename}' from '{archive}'\n\tto '{target}' ({size} bytes)")
                    count += 1
        result["details"]["summary"].append(
            f"Unzipped {plural(count, 'file')} from {plural(len(archives), 'archive')}.")
        return result
