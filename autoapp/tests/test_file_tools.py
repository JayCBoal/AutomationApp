"""
Delete Files, Check Files, Zip Files and Unzip Files: real files in a temp folder,
the real handlers, real spool output.
"""
import os
import time
import zipfile

import pytest

from engine.handlers.file_tools import CheckFilesHandler, DeleteFilesHandler, UnzipFilesHandler, ZipFilesHandler
from engine.telemetry_client import LocalSpoolTelemetryClient


@pytest.fixture
def folders(tmp_path):
    """A source folder holding two .csv files and one .txt, plus an output folder and a spool."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.csv").write_text("id,val\n1,alpha")
    (src / "b.csv").write_text("id,val\n2,beta")
    (src / "notes.txt").write_text("not a csv")
    return src, tmp_path / "out", tmp_path / "spool"


def run_handler(handler_cls, spool, params):
    config = {"StepID": 301, "StepType": handler_cls.CODE, "StepOrder": 1, "Title": "Test"}
    with LocalSpoolTelemetryClient(spool_dir=str(spool), instance_id="T1") as telemetry:
        return handler_cls(step_config=config, telemetry_client=telemetry).run(params)


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def age(path, days=0, hours=0):
    """Makes a file look as if it was last changed this long ago."""
    then = time.time() - days * 86400 - hours * 3600
    os.utime(path, (then, then))


def zip_of(path, **members):
    with zipfile.ZipFile(path, "w") as zipped:
        for name, text in members.items():
            zipped.writestr(name, text)
    return path


# --- Delete Files --------------------------------------------------------------------------

def test_delete_removes_only_matching_files(folders, spool_records):
    src, _, spool = folders

    result = run_handler(DeleteFilesHandler, spool, {"Source": str(src / "*.csv")})

    assert result["status"] == "SUCCESS"
    assert names(src) == ["notes.txt"]
    assert "Deleted 2 files." in result["result"]["details"]["summary"]
    first, second = spool_records(spool)
    assert (first["OpType"], first["Status"], first["SourcePath"], first["SourceFilename"]) == (
        "DELETE", "SUCCESS", str(src), "a.csv")
    assert first["SourceSize"] == len("id,val\n1,alpha")
    assert (first["DestPath"], first["DestFilename"], first["DestEndpointID"]) == (None, None, None)
    assert second["SourceFilename"] == "b.csv"


def test_delete_can_keep_recent_files(folders, spool_records):
    src, _, spool = folders
    age(src / "a.csv", days=10)
    age(src / "b.csv", days=2)

    run_handler(DeleteFilesHandler, spool, {"Source": str(src / "*.csv"), "OlderThanDays": "7"})

    assert names(src) == ["b.csv", "notes.txt"]
    assert [r["SourceFilename"] for r in spool_records(spool)] == ["a.csv"]


def test_delete_with_nothing_to_delete_fails_unless_allowed(folders, spool_records):
    src, _, spool = folders

    with pytest.raises(FileNotFoundError) as error:
        run_handler(DeleteFilesHandler, spool, {"Source": str(src / "*.csv"), "OlderThanDays": "7"})
    assert f"No files matched '{src}/*.csv' older than 7 days" in str(error.value)
    assert "AllowNoFiles" in str(error.value)

    result = run_handler(DeleteFilesHandler, spool,
                         {"Source": str(src / "*.csv"), "OlderThanDays": "7", "AllowNoFiles": "True"})
    assert result["status"] == "SUCCESS"
    assert names(src) == ["a.csv", "b.csv", "notes.txt"]
    assert spool_records(spool) == []


def test_delete_needs_a_whole_number_of_days(folders):
    src, _, spool = folders

    with pytest.raises(ValueError):
        run_handler(DeleteFilesHandler, spool, {"Source": str(src / "*.csv"), "OlderThanDays": "a week"})
    assert names(src) == ["a.csv", "b.csv", "notes.txt"]


# --- Check Files ---------------------------------------------------------------------------

def test_check_passes_files_that_look_right_and_touches_nothing(folders, spool_records):
    src, _, spool = folders

    result = run_handler(CheckFilesHandler, spool, {"Source": str(src / "*.csv"), "MinCount": "2", "MaxCount": "2"})

    assert result["status"] == "SUCCESS"
    assert "Checked 2 files; all as expected." in result["result"]["details"]["summary"]
    assert names(src) == ["a.csv", "b.csv", "notes.txt"]
    records = spool_records(spool)
    assert [(r["OpType"], r["Status"], r["SourceFilename"], r["DestFilename"]) for r in records] == [
        ("CHECK", "SUCCESS", "a.csv", None), ("CHECK", "SUCCESS", "b.csv", None)]


def test_check_fails_when_too_few_files_arrived(folders, spool_records):
    src, _, spool = folders

    with pytest.raises(ValueError) as error:
        run_handler(CheckFilesHandler, spool, {"Source": str(src / "*.csv"), "MinCount": "3"})

    assert f"2 files matched '{src}/*.csv'; at least 3 expected." in str(error.value)


def test_check_fails_when_nothing_arrived(folders):
    src, _, spool = folders

    with pytest.raises(ValueError) as error:
        run_handler(CheckFilesHandler, spool, {"Source": str(src / "*.xml")})

    assert "0 files matched" in str(error.value) and "at least 1 expected" in str(error.value)


def test_check_can_accept_no_files(folders):
    src, _, spool = folders

    result = run_handler(CheckFilesHandler, spool, {"Source": str(src / "*.xml"), "MinCount": "0"})

    assert result["status"] == "SUCCESS"


def test_check_fails_when_too_many_files_arrived(folders):
    src, _, spool = folders

    with pytest.raises(ValueError) as error:
        run_handler(CheckFilesHandler, spool, {"Source": str(src / "*"), "MaxCount": "2"})

    assert "3 files matched" in str(error.value) and "at most 2 expected" in str(error.value)


def test_check_fails_an_empty_file_and_says_which(folders, spool_records):
    src, _, spool = folders
    (src / "b.csv").write_text("")

    with pytest.raises(ValueError) as error:
        run_handler(CheckFilesHandler, spool, {"Source": str(src / "*.csv")})

    assert "'b.csv': it is empty." in str(error.value)
    by_name = {r["SourceFilename"]: r for r in spool_records(spool)}
    assert by_name["a.csv"]["Status"] == "SUCCESS"
    assert (by_name["b.csv"]["Status"], by_name["b.csv"]["Error"]) == ("FAILED", "'b.csv': it is empty.")


def test_check_can_allow_empty_files(folders):
    src, _, spool = folders
    (src / "b.csv").write_text("")

    result = run_handler(CheckFilesHandler, spool, {"Source": str(src / "*.csv"), "AllowEmpty": "True"})

    assert result["status"] == "SUCCESS"


def test_check_fails_a_stale_file(folders):
    """Yesterday's file still sitting there usually means today's never came."""
    src, _, spool = folders
    age(src / "a.csv", hours=30)

    with pytest.raises(ValueError) as error:
        run_handler(CheckFilesHandler, spool, {"Source": str(src / "*.csv"), "MaxAgeHours": "24"})

    assert "'a.csv': it was last changed more than 24 hours ago." in str(error.value)
    assert "b.csv" not in str(error.value)


def test_check_lists_every_problem_at_once(folders):
    src, _, spool = folders
    (src / "a.csv").write_text("")
    age(src / "a.csv", hours=30)

    with pytest.raises(ValueError) as error:
        run_handler(CheckFilesHandler, spool, {"Source": str(src / "*.csv"), "MinCount": "3", "MaxAgeHours": "24"})

    message = str(error.value)
    assert "at least 3 expected" in message
    assert "'a.csv': it is empty and it was last changed more than 24 hours ago." in message


# --- Zip Files -----------------------------------------------------------------------------

def test_zip_packs_matching_files_into_one_archive(folders, spool_records):
    src, out, spool = folders

    result = run_handler(ZipFilesHandler, spool, {"Source": str(src / "*.csv"), "Dest": str(out / "batch.zip")})

    assert result["status"] == "SUCCESS"
    assert names(out) == ["batch.zip"]                         # no .partial left behind
    with zipfile.ZipFile(out / "batch.zip") as zipped:
        assert sorted(zipped.namelist()) == ["a.csv", "b.csv"]
        assert zipped.read("a.csv").decode() == "id,val\n1,alpha"
    assert names(src) == ["a.csv", "b.csv", "notes.txt"]      # the originals are still there
    first, second = spool_records(spool)
    assert (first["OpType"], first["Status"], first["SourceFilename"]) == ("ZIP", "SUCCESS", "a.csv")
    assert (first["DestPath"], first["DestFilename"]) == (str(out), "batch.zip")
    assert first["DestSize"] == (out / "batch.zip").stat().st_size
    assert (second["SourceFilename"], second["DestFilename"]) == ("b.csv", "batch.zip")


def test_zip_with_move_removes_the_originals(folders, spool_records):
    src, out, spool = folders

    run_handler(ZipFilesHandler, spool, {"Source": str(src / "*.csv"), "Dest": str(out / "batch.zip"), "Move": "True"})

    assert names(src) == ["notes.txt"]
    assert {r["OpType"] for r in spool_records(spool)} == {"ZIP_MOVE"}


def test_zip_into_a_folder_needs_an_archive_name(folders):
    src, out, spool = folders

    with pytest.raises(ValueError) as error:
        run_handler(ZipFilesHandler, spool, {"Source": str(src / "*.csv"), "Dest": str(out)})
    assert "ArchiveName" in str(error.value)

    run_handler(ZipFilesHandler, spool, {"Source": str(src / "*.csv"), "Dest": str(out), "ArchiveName": "batch.zip"})
    assert names(out) == ["batch.zip"]


def test_zip_does_not_replace_an_archive_unless_told_to(folders):
    src, out, spool = folders
    out.mkdir()
    zip_of(out / "batch.zip", old="yesterday")
    params = {"Source": str(src / "*.csv"), "Dest": str(out / "batch.zip")}

    with pytest.raises(FileExistsError) as error:
        run_handler(ZipFilesHandler, spool, params)
    assert "Overwrite" in str(error.value)
    with zipfile.ZipFile(out / "batch.zip") as zipped:
        assert zipped.namelist() == ["old"]

    run_handler(ZipFilesHandler, spool, {**params, "Overwrite": "True"})
    with zipfile.ZipFile(out / "batch.zip") as zipped:
        assert sorted(zipped.namelist()) == ["a.csv", "b.csv"]


def test_zip_with_nothing_to_pack_fails_unless_allowed(folders, spool_records):
    src, out, spool = folders
    params = {"Source": str(src / "*.xml"), "Dest": str(out / "batch.zip")}

    with pytest.raises(FileNotFoundError):
        run_handler(ZipFilesHandler, spool, params)

    result = run_handler(ZipFilesHandler, spool, {**params, "AllowNoFiles": "True"})
    assert result["status"] == "SUCCESS"
    assert not out.exists()
    assert spool_records(spool) == []


def test_a_failed_zip_leaves_the_originals_and_no_archive(folders, spool_records, monkeypatch):
    src, out, spool = folders
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda self: "a.csv")

    with pytest.raises(IOError):
        run_handler(ZipFilesHandler, spool,
                    {"Source": str(src / "*.csv"), "Dest": str(out / "batch.zip"), "Move": "True"})

    assert names(out) == []
    assert names(src) == ["a.csv", "b.csv", "notes.txt"]
    assert {(r["OpType"], r["Status"]) for r in spool_records(spool)} == {("ZIP_MOVE", "FAILED")}


# --- Unzip Files ---------------------------------------------------------------------------

def test_unzip_takes_every_file_out(folders, spool_records):
    src, out, spool = folders
    zip_of(src / "batch.zip", **{"a.csv": "one", "reports/b.csv": "two"})

    result = run_handler(UnzipFilesHandler, spool, {"Source": str(src / "*.zip"), "Dest": str(out)})

    assert result["status"] == "SUCCESS"
    assert "Took 2 files out of 1 archive." in result["result"]["details"]["summary"]
    assert (out / "a.csv").read_text() == "one"
    assert (out / "reports" / "b.csv").read_text() == "two"
    assert (src / "batch.zip").exists()
    first, second = spool_records(spool)
    assert (first["OpType"], first["SourceFilename"], first["DestPath"], first["DestFilename"]) == (
        "UNZIP", "batch.zip", str(out), "a.csv")
    assert (second["DestPath"], second["DestFilename"], second["DestSize"]) == (str(out / "reports"), "b.csv", 3)
    assert first["SourceSize"] == (src / "batch.zip").stat().st_size     # the archive's size, not the file's


def test_unzip_does_not_replace_files_unless_told_to(folders):
    src, out, spool = folders
    zip_of(src / "batch.zip", **{"a.csv": "new"})
    out.mkdir()
    (out / "a.csv").write_text("old")
    params = {"Source": str(src / "batch.zip"), "Dest": str(out)}

    with pytest.raises(FileExistsError):
        run_handler(UnzipFilesHandler, spool, params)
    assert (out / "a.csv").read_text() == "old"

    run_handler(UnzipFilesHandler, spool, {**params, "Overwrite": "True"})
    assert (out / "a.csv").read_text() == "new"


def test_unzip_refuses_an_archive_that_would_write_outside_the_folder(folders, tmp_path, spool_records):
    src, out, spool = folders
    zip_of(src / "evil.zip", **{"fine.csv": "ok", "../escaped.csv": "bad"})

    with pytest.raises(ValueError) as error:
        run_handler(UnzipFilesHandler, spool, {"Source": str(src / "evil.zip"), "Dest": str(out)})

    assert "outside the destination folder" in str(error.value)
    assert not (tmp_path / "escaped.csv").exists()
    assert names(out) == []                                   # nothing was taken out, not even the safe one
    assert spool_records(spool) == []


def test_unzip_says_plainly_when_a_file_is_not_an_archive(folders):
    src, out, spool = folders
    (src / "fake.zip").write_text("not really")

    with pytest.raises(ValueError) as error:
        run_handler(UnzipFilesHandler, spool, {"Source": str(src / "*.zip"), "Dest": str(out)})

    assert "'fake.zip' is not a readable .zip archive" in str(error.value)


def test_unzip_with_no_archives_fails_unless_allowed(folders):
    src, out, spool = folders
    params = {"Source": str(src / "*.zip"), "Dest": str(out)}

    with pytest.raises(FileNotFoundError):
        run_handler(UnzipFilesHandler, spool, params)
    assert run_handler(UnzipFilesHandler, spool, {**params, "AllowNoFiles": "True"})["status"] == "SUCCESS"
