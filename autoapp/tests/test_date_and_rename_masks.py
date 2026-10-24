"""
Date masks (${DATE:yyyyMMdd}) and rename masks (${FILE:STEM}_...${FILE:EXT}).
"""
from datetime import datetime

import pytest

from core.date_mask import format_date
from core.rename_mask import check_mask, new_name, new_names
from core.scope_engine import ScopeResolutionEngine

# Tuesday 6 October 2026, 14:05:09.042, and an early-morning time for the 12-hour clock
AFTERNOON = datetime(2026, 10, 6, 14, 5, 9, 42000)
EARLY = datetime(2026, 1, 2, 0, 7, 3)


# --- Date masks -----------------------------------------------------------------------------

@pytest.mark.parametrize("mask, expected", [
    ("yyyyMMdd", "20261006"),
    ("yyyy-MM-dd", "2026-10-06"),
    ("yyyyMMdd_HHmmss", "20261006_140509"),
    ("yy", "26"),
    ("dd/MM/yyyy HH:mm", "06/10/2026 14:05"),
    ("d-M-yy", "6-10-26"),
    ("MMMM d, yyyy", "October 6, 2026"),
    ("ddd dd MMM", "Tue 06 Oct"),
    ("dddd", "Tuesday"),
    ("H.m.s", "14.5.9"),
    ("hh:mm tt", "02:05 PM"),
    ("h tt", "2 PM"),
    ("HHmmssfff", "140509042"),
])
def test_masks_use_the_dot_net_letters(mask, expected):
    assert format_date(mask, AFTERNOON) == expected


def test_capital_m_is_the_month_and_small_m_is_the_minute():
    """The reason the letters are case-sensitive at all."""
    assert format_date("MM", AFTERNOON) == "10"
    assert format_date("mm", AFTERNOON) == "05"
    assert format_date("MMmm", AFTERNOON) == "1005"


def test_midnight_on_the_twelve_hour_clock_is_twelve():
    assert format_date("hh:mm tt", EARLY) == "12:07 AM"
    assert format_date("HH:mm", EARLY) == "00:07"


def test_text_in_single_quotes_is_copied_as_it_is():
    assert format_date("yyyyMMdd'T'HHmm", AFTERNOON) == "20261006T1405"
    assert format_date("'day' d 'of month' M", AFTERNOON) == "day 6 of month 10"


@pytest.mark.parametrize("mask, culprit", [("YYYYMMDD", "Y"), ("yyyyMMDD", "D"), ("yyyy-MM-dd Thh", "T"),
                                           ("date", "a"), ("yyyy.MM.dd z", "z")])
def test_a_letter_that_is_not_a_mask_letter_is_refused_not_guessed_at(mask, culprit):
    with pytest.raises(ValueError) as error:
        format_date(mask, AFTERNOON)

    assert f"'{culprit}' in the date mask '{mask}' is not understood" in str(error.value)
    assert "MM for the month" in str(error.value) and "mm for the minute" in str(error.value)


def test_an_empty_mask_and_an_unclosed_quote_are_refused():
    with pytest.raises(ValueError, match="needs a mask"):
        format_date("", AFTERNOON)
    with pytest.raises(ValueError, match="never closed"):
        format_date("yyyy'T", AFTERNOON)


# --- Date placeholders in a job -------------------------------------------------------------------

@pytest.fixture
def engine(db, seed, tmp_path):
    job = seed.job("DEV-LOAD", Stamp="${DATE:yyyyMMdd}", Bad="${DATE:YYYY}")
    engine = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id="I1",
                                   global_config={"WORKING_ROOT": str(tmp_path)})
    engine.build_context()
    engine.started = AFTERNOON
    return engine


def test_a_date_placeholder_is_replaced_by_the_runs_start_time_in_that_format(engine):
    assert engine.interpolate("archive/${DATE:yyyy}/${DATE:MM}/extract_${DATE:yyyyMMdd_HHmm}.csv") == (
        "archive/2026/10/extract_20261006_1405.csv")


def test_every_date_placeholder_in_a_run_shows_the_same_moment(db, seed):
    job = seed.job("DEV-LOAD")
    engine = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id="I1")
    engine.build_context()

    first = engine.interpolate("${DATE:HHmmssfff}")
    second = engine.interpolate("${DATE:HHmmssfff}")

    assert first == second


def test_a_date_placeholder_inside_a_variable_is_resolved(engine):
    assert engine.interpolate("in_${Stamp}") == "in_20261006"


def test_a_bad_date_mask_is_an_error(engine):
    with pytest.raises(ValueError, match="'Y' in the date mask 'YYYY' is not understood"):
        engine.interpolate("archive/${Bad}")


def test_the_older_fixed_date_placeholder_still_works(db, seed):
    job = seed.job("DEV-LOAD")
    engine = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id="I1")
    engine.build_context()

    assert engine.interpolate("${SYS:YYYYMMDD}") == engine.interpolate("${DATE:yyyyMMdd}")


# --- Rename masks ---------------------------------------------------------------------------------

@pytest.mark.parametrize("mask, filename, expected", [
    ("${FILE:NAME}", "Legal_Batch_1.csv", "Legal_Batch_1.csv"),
    ("${FILE:STEM}_20261006${FILE:EXT}", "Legal_Batch_1.csv", "Legal_Batch_1_20261006.csv"),
    ("${FILE:STEM}.txt", "Legal_Batch_1.csv", "Legal_Batch_1.txt"),
    ("processed_${FILE:NAME}", "a.csv", "processed_a.csv"),
    ("${FILE:NAME}.done", "a.csv", "a.csv.done"),
    ("${FILE:STEM}${FILE:EXT}", "archive.tar.gz", "archive.tar.gz"),      # the extension is the last part only
    ("${FILE:STEM}|${FILE:EXT}|", "README", "README||"),                  # no extension: empty
])
def test_a_mask_builds_the_new_name_from_parts_of_the_old(mask, filename, expected):
    assert new_name(mask, filename) == expected


def test_an_unknown_file_placeholder_is_refused_and_says_which_exist():
    with pytest.raises(ValueError) as error:
        check_mask("${FILE:BASENAME}.csv")

    assert "${FILE:BASENAME} is not a file placeholder" in str(error.value)
    assert "${FILE:NAME}, ${FILE:STEM}, ${FILE:EXT}" in str(error.value)


def test_file_placeholders_are_case_sensitive():
    with pytest.raises(ValueError, match="is not a file placeholder"):
        check_mask("${FILE:name}")


@pytest.mark.parametrize("mask", ["sub/${FILE:NAME}", "..", "   ", "${FILE:EXT}"])
def test_a_mask_whose_result_is_not_a_filename_is_refused(mask):
    with pytest.raises(ValueError, match="is not a filename"):
        new_name(mask, "README")


def test_each_file_gets_its_own_new_name():
    assert new_names("${FILE:STEM}_new${FILE:EXT}", ["a.csv", "b.csv"]) == {"a.csv": "a_new.csv", "b.csv": "b_new.csv"}


def test_a_mask_that_gives_two_files_the_same_name_is_refused():
    with pytest.raises(ValueError) as error:
        new_names("daily${FILE:EXT}", ["a.csv", "b.csv"])

    assert "gives 'a.csv' and 'b.csv' the same name, 'daily.csv'" in str(error.value)
    assert "${FILE:STEM}" in str(error.value)


def test_one_file_may_be_given_a_fixed_name():
    assert new_names("daily.csv", ["a.csv"]) == {"a.csv": "daily.csv"}


# --- The copy step with a rename mask, run for real -------------------------------------------

def names(folder):
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_each_file_is_renamed_on_its_way_to_an_endpoint(seed, endpoints, run_runner, tmp_path, spool_records):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True",
              RenameMask="${FILE:STEM}_${DATE:yyyyMMdd}${FILE:EXT}")

    result = run_runner("DEV-LOAD")

    today = datetime.now().strftime("%Y%m%d")
    assert result.returncode == 0, result.stderr
    assert names(tmp_path / "app_inbox") == [f"Legal_Batch_1_{today}.csv", f"Legal_Batch_2_{today}.csv"]
    delivered = [r for r in spool_records(tmp_path / "spool") if r.get("StepOrder") == 2]
    assert [(r["SourceFilename"], r["DestFilename"]) for r in delivered] == [
        ("Legal_Batch_1.csv", f"Legal_Batch_1_{today}.csv"), ("Legal_Batch_2.csv", f"Legal_Batch_2_{today}.csv")]
    # the job log says what each file was called and what it became
    assert f"Legal_Batch_1.csv'\n\tto '{tmp_path}/app_inbox/Legal_Batch_1_{today}.csv'" in result.stdout
    # and it shows the mask as written and as resolved, with the per-file parts still to come
    assert "RenameMask: ${FILE:STEM}_${DATE:yyyyMMdd}${FILE:EXT}  (resolved: ${FILE:STEM}_" + today + "${FILE:EXT})" in result.stdout


def test_a_rename_into_a_working_folder_whose_name_has_a_full_stop(seed, endpoints, run_runner, tmp_path):
    """With a mask, Dest is always a folder, even if its name looks like a filename."""
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="archive.v2", RenameMask="kept_${FILE:NAME}")

    assert run_runner("DEV-LOAD").returncode == 0
    assert names(tmp_path / "work" / "DEV-LOAD" / "archive.v2") == ["kept_Legal_Batch_1.csv", "kept_Legal_Batch_2.csv"]


def test_a_trace_follows_files_through_a_rename_mask(seed, endpoints, run_runner, load_spool, client, db):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming", RenameMask="in_${FILE:NAME}")
    seed.step(job, 2, Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", RenameMask="${FILE:STEM}.done")
    run_runner("DEV-LOAD")
    load_spool()
    db.commit()

    [delivered] = client.get("/api/v1/operations", params={"dest_filename": "in_Legal_Batch_1.done"}).json()
    trace = client.get(f"/api/v1/operations/{delivered['id']}/trace").json()

    assert [(hop["source"]["filename"], hop["dest"]["filename"]) for hop in trace["hops"]] == [
        ("Legal_Batch_1.csv", "in_Legal_Batch_1.csv"), ("in_Legal_Batch_1.csv", "in_Legal_Batch_1.done")]


def test_a_mask_that_would_give_two_files_one_name_stops_the_step_before_anything_is_copied(
        seed, endpoints, run_runner, tmp_path, spool_records):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming", RenameMask="daily.csv")

    result = run_runner("DEV-LOAD")

    assert result.returncode == 1
    assert "gives 'Legal_Batch_1.csv' and 'Legal_Batch_2.csv' the same name, 'daily.csv'" in result.stderr
    assert names(tmp_path / "work" / "DEV-LOAD" / "incoming") == []
    assert [r["Record"] for r in spool_records(tmp_path / "spool")] == ["RUN_START", "RUN_END"]


def test_a_mistake_in_a_mask_is_found_before_the_job_starts(seed, endpoints, run_runner, tmp_path):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX",
              RenameMask="${FILE:BASENAME}_${DATE:yyyyMMdd}")
    seed.step(job, 3, title="Archive", Source="incoming/*.csv", Dest="archive/${DATE:YYYYMMDD}")

    result = run_runner("DEV-LOAD")

    assert result.returncode == 1
    assert "2 problems were found before the job started" in result.stderr
    assert "Step 2 ('Deliver'): ${FILE:BASENAME} is not a file placeholder" in result.stderr
    assert "Step 3 ('Archive'): 'Y' in the date mask 'YYYYMMDD' is not understood" in result.stderr
    assert names(tmp_path / "work" / "DEV-LOAD") == []                  # step 1 never ran


def test_a_file_placeholder_anywhere_but_a_rename_mask_is_an_unresolved_placeholder(seed, endpoints, run_runner, tmp_path):
    """Dest is a folder, resolved once before the job starts, when there is no file to speak of."""
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming/${FILE:STEM}")

    result = run_runner("DEV-LOAD")

    assert result.returncode == 1
    assert "Unresolved placeholder(s)" in result.stderr and "${FILE:STEM}" in result.stderr
    assert names(tmp_path / "work" / "DEV-LOAD") == []
