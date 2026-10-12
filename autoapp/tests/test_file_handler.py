"""
File handler: real files in a temp folder, the real handler, real spool output.
"""
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


def test_success_is_recorded_in_the_spool(folders, spool_records):
    src, dest, spool = folders

    run_handler(spool, {"Source": str(src / "*.csv"), "Dest": str(dest)})

    [record] = spool_records(spool)
    assert record["Status"] == "SUCCESS"
    assert record["StepID"] == 201
    assert record["OpType"] == "COPY_FILES"
    assert sorted(op["Dest"] for op in record["Details"]["ops"]) == [str(dest / "a.csv"), str(dest / "b.csv")]


def test_failure_is_recorded_in_the_spool(folders, spool_records):
    src, dest, spool = folders

    with pytest.raises(FileNotFoundError):
        run_handler(spool, {"Source": str(src / "*.csv"), "Dest": str(dest), "CreateFolder": "False"})

    audit, operation = spool_records(spool)
    assert audit["IsAudit"] is True
    assert audit["Action"] == "STEP_EXECUTION_FAILURE"
    assert operation["Status"] == "FAILED"
    assert "error_message" in operation["Details"]


def test_missing_source_or_destination_is_a_clear_error(folders):
    src, dest, spool = folders

    with pytest.raises(ValueError, match="source"):
        run_handler(spool, {"Dest": str(dest)})
    with pytest.raises(ValueError, match="destination"):
        run_handler(spool, {"Source": str(src / "*.csv")})
