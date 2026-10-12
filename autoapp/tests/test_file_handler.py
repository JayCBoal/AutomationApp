"""
File handler: real files in a temp folder, the real handler, real spool output.
"""
import hashlib

import pytest

from engine.handlers.file_handler import FileOpHandler
from engine.telemetry_client import LocalSpoolTelemetryClient

STEP_CONFIG = {"StepID": 201, "StepType": "COPY_FILES"}


@pytest.fixture
def folders(tmp_path):
    """A source folder holding two .csv files and one .txt, plus dest and spool paths."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.csv").write_text("id,val\n1,alpha")
    (src / "b.csv").write_text("id,val\n2,beta")
    (src / "notes.txt").write_text("not a csv")
    return src, tmp_path / "dest", tmp_path / "spool"


def run_handler(spool, params):
    with LocalSpoolTelemetryClient(spool_dir=str(spool), instance_id="T1") as telemetry:
        return FileOpHandler(step_config=STEP_CONFIG, telemetry_client=telemetry).run(params)


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def test_copy_copies_only_matching_files(folders):
    src, dest, spool = folders

    result = run_handler(spool, {"Source": str(src / "*.csv"), "Dest": str(dest)})

    assert result["status"] == "SUCCESS"
    assert names(dest) == ["a.csv", "b.csv"]
    assert (dest / "a.csv").read_text() == "id,val\n1,alpha"
    assert (dest / "b.csv").read_text() == "id,val\n2,beta"


def test_copy_leaves_source_files_in_place(folders):
    src, dest, spool = folders

    run_handler(spool, {"Source": str(src / "*.csv"), "Dest": str(dest)})

    assert names(src) == ["a.csv", "b.csv", "notes.txt"]


def test_move_removes_matching_files_from_source(folders):
    src, dest, spool = folders

    run_handler(spool, {"Source": str(src / "*.csv"), "Dest": str(dest), "Move": "True"})

    assert names(dest) == ["a.csv", "b.csv"]
    assert names(src) == ["notes.txt"]


def test_single_file_can_be_copied_to_a_new_filename(folders):
    src, dest, spool = folders

    run_handler(spool, {"Source": str(src / "a.csv"), "Dest": str(dest / "renamed.csv")})

    assert names(dest) == ["renamed.csv"]
    assert (dest / "renamed.csv").read_text() == "id,val\n1,alpha"


def test_destination_folder_is_created_by_default(folders):
    src, dest, spool = folders
    nested = dest / "2026" / "10"

    run_handler(spool, {"Source": str(src / "*.csv"), "Dest": str(nested)})

    assert names(nested) == ["a.csv", "b.csv"]


def test_missing_destination_fails_when_create_folder_is_off(folders):
    src, dest, spool = folders

    with pytest.raises(FileNotFoundError):
        run_handler(spool, {"Source": str(src / "*.csv"), "Dest": str(dest), "CreateFolder": "False"})

    assert not dest.exists()


def test_no_matching_files_copies_nothing(folders):
    src, dest, spool = folders

    result = run_handler(spool, {"Source": str(src / "*.xml"), "Dest": str(dest)})

    assert result["result"]["bytes_transferred"] == 0
    assert result["result"]["details"]["ops"] == []
    assert names(dest) == []


def test_bytes_transferred_is_total_size_of_copied_files(folders):
    src, dest, spool = folders
    expected = (src / "a.csv").stat().st_size + (src / "b.csv").stat().st_size

    result = run_handler(spool, {"Source": str(src / "*.csv"), "Dest": str(dest)})

    assert result["result"]["bytes_transferred"] == expected


def test_each_file_gets_its_own_spool_record(folders, spool_records):
    src, dest, spool = folders

    run_handler(spool, {"Source": str(src / "*.csv"), "Dest": str(dest)})

    first, second = spool_records(spool)
    assert first["Record"] == "OPERATION"
    assert (first["Status"], first["OpType"], first["StepID"]) == ("SUCCESS", "COPY", 201)
    assert (first["SourcePath"], first["SourceFilename"]) == (str(src), "a.csv")
    assert (first["DestPath"], first["DestFilename"]) == (str(dest), "a.csv")
    assert first["SourceSize"] == first["DestSize"] == (src / "a.csv").stat().st_size
    assert first["Checksum"] is None
    assert (second["SourceFilename"], second["DestFilename"]) == ("b.csv", "b.csv")


def test_a_move_is_recorded_as_a_move(folders, spool_records):
    src, dest, spool = folders

    run_handler(spool, {"Source": str(src / "a.csv"), "Dest": str(dest), "Move": "True"})

    [record] = spool_records(spool)
    assert record["OpType"] == "MOVE"
    assert record["SourceSize"] == record["DestSize"] == (dest / "a.csv").stat().st_size


def test_a_rename_is_recorded_with_both_filenames(folders, spool_records):
    src, dest, spool = folders

    run_handler(spool, {"Source": str(src / "a.csv"), "Dest": str(dest / "renamed.csv")})

    [record] = spool_records(spool)
    assert (record["SourceFilename"], record["DestFilename"]) == ("a.csv", "renamed.csv")


def test_a_file_that_fails_is_recorded_with_the_error(folders, spool_records):
    src, dest, spool = folders

    with pytest.raises(FileNotFoundError):
        run_handler(spool, {"Source": str(src / "*.csv"), "Dest": str(dest), "CreateFolder": "False"})

    [record] = spool_records(spool)     # the step stops at the first file that fails
    assert record["Status"] == "FAILED"
    assert record["SourceFilename"] == "a.csv"
    assert record["SourceSize"] == (src / "a.csv").stat().st_size
    assert record["DestSize"] is None
    assert "No such file or directory" in record["Error"]


def test_a_copy_that_arrives_a_different_size_fails(folders, spool_records, monkeypatch):
    """Stands in for a transfer cut short: the copy writes only part of the file."""
    src, dest, spool = folders

    def truncating_copy(source, target):
        with open(source, "rb") as f, open(target, "wb") as out:
            out.write(f.read()[:5])

    monkeypatch.setattr("engine.handlers.file_handler.shutil.copy2", truncating_copy)

    with pytest.raises(IOError, match="Size mismatch"):
        run_handler(spool, {"Source": str(src / "a.csv"), "Dest": str(dest)})

    [record] = spool_records(spool)
    assert record["Status"] == "FAILED"
    assert (record["SourceSize"], record["DestSize"]) == ((src / "a.csv").stat().st_size, 5)
    assert "Size mismatch" in record["Error"]


def test_checksum_option_records_the_files_sha256(folders, spool_records):
    src, dest, spool = folders

    run_handler(spool, {"Source": str(src / "a.csv"), "Dest": str(dest), "Checksum": "True"})

    [record] = spool_records(spool)
    assert record["Checksum"] == hashlib.sha256(b"id,val\n1,alpha").hexdigest()


def test_checksum_option_fails_a_copy_whose_content_changed(folders, spool_records, monkeypatch):
    """Same size, different content: only a checksum can catch this."""
    src, dest, spool = folders

    def corrupting_copy(source, target):
        with open(source, "rb") as f, open(target, "wb") as out:
            out.write(f.read().replace(b"alpha", b"ALPHA"))

    monkeypatch.setattr("engine.handlers.file_handler.shutil.copy2", corrupting_copy)

    with pytest.raises(IOError, match="Checksum mismatch"):
        run_handler(spool, {"Source": str(src / "a.csv"), "Dest": str(dest), "Checksum": "True"})

    [record] = spool_records(spool)
    assert record["Status"] == "FAILED"
    assert "Checksum mismatch" in record["Error"]


def test_folders_matching_the_pattern_are_skipped(folders, spool_records):
    src, dest, spool = folders
    (src / "old.csv").mkdir()

    run_handler(spool, {"Source": str(src / "*.csv"), "Dest": str(dest)})

    assert names(dest) == ["a.csv", "b.csv"]


def test_missing_source_or_destination_is_a_clear_error(folders):
    src, dest, spool = folders

    with pytest.raises(ValueError, match="source"):
        run_handler(spool, {"Dest": str(dest)})
    with pytest.raises(ValueError, match="destination"):
        run_handler(spool, {"Source": str(src / "*.csv")})
