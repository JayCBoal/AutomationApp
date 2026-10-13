"""
Names are case-sensitive: 'DEV-LOAD' and 'dev-load' are two different names,
on every database. (Schedulers such as RunMyJobs treat names this way, and so
does the code that resolves variables.) Searching, by contrast, ignores case.
"""
import pytest
from sqlalchemy.exc import IntegrityError


def test_job_keys_that_differ_only_by_case_are_different_jobs(seed, endpoints, run_runner, tmp_path):
    seed.step(seed.job("DEV-LOAD"), 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="upper")
    seed.step(seed.job("dev-load"), 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="lower")

    result = run_runner("dev-load")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "work" / "dev-load" / "lower").is_dir()
    assert not (tmp_path / "work" / "DEV-LOAD").exists()


def test_a_job_key_in_the_wrong_case_is_not_found(seed, endpoints, run_runner):
    seed.step(seed.job("DEV-LOAD"), 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")

    result = run_runner("dev-load")

    assert result.returncode == 1
    assert "No job with JobKey 'dev-load' exists." in result.stderr


def test_an_endpoint_name_in_the_wrong_case_is_not_found(seed, endpoints, run_runner):
    seed.step(seed.job("DEV-LOAD"), 1, SourceEndpoint="legal_extracts", Dest="incoming")

    result = run_runner("DEV-LOAD")

    assert result.returncode == 1
    assert "Endpoint 'legal_extracts', which is not registered" in result.stderr


def test_variable_names_that_differ_only_by_case_are_different_variables(seed, endpoints, run_runner, tmp_path):
    job = seed.job("DEV-LOAD", Folder="upper", folder="lower")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="${Folder}_${folder}")

    result = run_runner("DEV-LOAD")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "work" / "DEV-LOAD" / "upper_lower").is_dir()


def test_the_same_name_twice_is_still_refused(db, seed):
    seed.job("DEV-LOAD")

    with pytest.raises(IntegrityError):
        seed.job("DEV-LOAD")
    db.rollback()


def test_searching_the_operations_log_still_ignores_case(seed, endpoints, run_runner, load_spool, client, db):
    seed.step(seed.job("DEV-LOAD"), 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    run_runner("DEV-LOAD")
    load_spool()

    def found(**criteria):
        return len(client.get("/api/v1/operations", params=criteria).json())

    assert found(job_key="dev-lo") == found(job_key="DEV-LO") == 2
    assert found(filename="LEGAL_batch") == 2
    assert found(endpoint="legal_EXTRACTS") == 2
