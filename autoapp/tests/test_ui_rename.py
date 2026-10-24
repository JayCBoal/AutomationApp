"""The rename warning in a real browser: what it says, the tickbox that moves the working folder."""
import pytest

from core.models import Job, JobRun

from tests.test_ui_job_edit import edit, job, open_job   # noqa: F401  (the DEV-LOAD fixture and helpers)


@pytest.fixture
def history_and_folder(db, job, tmp_path):
    loaded = db.query(Job).filter(Job.JobKey == "DEV-LOAD").one()
    db.add(JobRun(RunID="r1", JobKey="DEV-LOAD", Job_MasterObject_id=loaded.MasterObject_id,
                  SchedulerInstanceID="r1", Status="SUCCESS"))
    db.commit()
    (tmp_path / "work" / "DEV-LOAD").mkdir(parents=True)
    (tmp_path / "work" / "DEV-LOAD" / "kept.csv").write_text("id\n1")
    return tmp_path / "work"


def press_save(page):
    page.locator("#submit-button").click()
    page.locator("#rename-go").wait_for(state="visible")


def test_a_job_with_history_and_a_folder_gets_the_warning_with_a_move_tickbox(page, history_and_folder):
    open_job(page)
    edit(page)
    page.locator("#job-key").fill("DEV-LOAD-DAILY")

    press_save(page)

    text = page.locator("dialog.rename-warning").inner_text()
    assert "Job History keeps the old key 'DEV-LOAD' on the 1 past run" in text
    assert "scheduler definition" in text and "Move the working folder with it" in text


def test_ticking_the_box_moves_the_folder_and_leaving_it_does_not(page, history_and_folder):
    open_job(page)
    edit(page)
    page.locator("#job-key").fill("DEV-LOAD-DAILY")
    press_save(page)
    page.locator("#rename-move").check()

    with page.expect_response(lambda r: "/api/v1/jobs" in r.url and r.request.method == "PUT"):
        page.locator("#rename-go").click()
    page.wait_for_selector("#save-notice")

    assert (history_and_folder / "DEV-LOAD-DAILY" / "kept.csv").exists()
    assert not (history_and_folder / "DEV-LOAD").exists()


def test_cancelling_the_warning_changes_nothing(page, db, history_and_folder):
    open_job(page)
    edit(page)
    page.locator("#job-key").fill("DEV-LOAD-DAILY")
    press_save(page)

    page.locator("#rename-cancel").click()

    db.expire_all()
    assert db.query(Job).filter(Job.JobKey == "DEV-LOAD").count() == 1
    assert (history_and_folder / "DEV-LOAD" / "kept.csv").exists()
