"""
Step parameter resolution: where a file step is allowed to read and write.

Rule under test: a raw path must be inside the job's working folder; anything
else must be a registered Endpoint, referenced by name.
"""
import pytest

from engine.handlers.file_handler import FileOpHandler
from engine.scope_engine import ScopeResolutionEngine
from engine.step_params import resolve_step


@pytest.fixture
def job(seed):
    return seed.job("DEV-LOAD")


@pytest.fixture
def working_folder(tmp_path):
    return tmp_path / "work" / "DEV-LOAD"


@pytest.fixture
def resolve(db, job, tmp_path):
    def _resolve(step, working_root=tmp_path / "work"):
        config = {"WORKING_ROOT": str(working_root)} if working_root else {}
        engine = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id="I1", global_config=config)
        engine.build_context()
        return resolve_step(step, FileOpHandler, engine, db)
    return _resolve


# --- raw paths ---------------------------------------------------------------

def test_relative_raw_path_is_taken_relative_to_the_working_folder(seed, job, resolve, working_folder):
    step = seed.step(job, 1, Source="incoming/*.csv", Dest="staged")

    resolved = resolve(step)

    assert resolved.params == {"Source": str(working_folder / "incoming" / "*.csv"),
                               "Dest": str(working_folder / "staged")}
    assert resolved.source_endpoint_id is None
    assert resolved.dest_endpoint_id is None


def test_absolute_raw_path_inside_the_working_folder_is_allowed(seed, job, resolve, working_folder):
    step = seed.step(job, 1, Source="${SYS:WORKING_FOLDER}/incoming/*.csv", Dest="staged")

    assert resolve(step).params["Source"] == str(working_folder / "incoming" / "*.csv")


def test_absolute_raw_path_outside_the_working_folder_is_rejected(seed, job, resolve):
    step = seed.step(job, 1, Source="/etc/*.conf", Dest="staged")

    with pytest.raises(ValueError, match="outside the job's working folder.*SourceEndpoint"):
        resolve(step)


def test_dot_dot_cannot_escape_the_working_folder(seed, job, resolve):
    step = seed.step(job, 1, Source="incoming/*.csv", Dest="../../elsewhere")

    with pytest.raises(ValueError, match="outside the job's working folder.*DestEndpoint"):
        resolve(step)


def test_sibling_folder_with_a_similar_name_is_outside(seed, job, resolve, working_folder):
    step = seed.step(job, 1, Source=str(working_folder) + "-OTHER/*.csv", Dest="staged")

    with pytest.raises(ValueError, match="outside the job's working folder"):
        resolve(step)


def test_raw_path_needs_a_working_folder_to_be_configured(seed, job, resolve, monkeypatch):
    monkeypatch.delenv("AUTOAPP_WORKING_ROOT", raising=False)
    step = seed.step(job, 1, Source="incoming/*.csv", Dest="staged")

    with pytest.raises(ValueError, match="no working folder is configured"):
        resolve(step, working_root=None)


# --- endpoints ---------------------------------------------------------------

def test_source_endpoint_resolves_to_its_path_and_filename_pattern(seed, job, resolve, working_folder):
    app = seed.application("LEGAL_APP")
    endpoint = seed.endpoint("LEGAL_EXTRACTS", "/apps/legal/outbox", "Legal_*.csv", application=app)
    step = seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")

    resolved = resolve(step)

    assert resolved.params == {"Source": "/apps/legal/outbox/Legal_*.csv",
                               "Dest": str(working_folder / "incoming")}
    assert resolved.source_endpoint_id == endpoint.id
    assert resolved.dest_endpoint_id is None


def test_dest_endpoint_resolves_to_its_path(seed, job, resolve):
    endpoint = seed.endpoint("BILLING_INBOX", "/apps/billing/inbox", "*.csv",
                             application=seed.application("BILLING_APP"))
    step = seed.step(job, 1, Source="staged/*.csv", DestEndpoint="BILLING_INBOX")

    resolved = resolve(step)

    assert resolved.params["Dest"] == "/apps/billing/inbox"
    assert resolved.dest_endpoint_id == endpoint.id
    assert resolved.source_endpoint_id is None


def test_each_endpoint_resolves_in_its_own_application_context(seed, job, resolve):
    seed.endpoint("LEGAL_EXTRACTS", "${APP.Root}/outbox", "*.csv",
                  application=seed.application("LEGAL_APP", Root="/apps/legal"))
    seed.endpoint("BILLING_INBOX", "${APP.Root}/inbox",
                  application=seed.application("BILLING_APP", Root="/apps/billing"))
    step = seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", DestEndpoint="BILLING_INBOX")

    resolved = resolve(step)

    assert resolved.params == {"Source": "/apps/legal/outbox/*.csv", "Dest": "/apps/billing/inbox"}


def test_endpoint_pattern_can_use_job_variables_and_macros(seed, job, resolve):
    seed.set_vars(job, Prefix="Legal")
    seed.endpoint("LEGAL_EXTRACTS", "/apps/legal/outbox", "${Prefix}_${SYS:INSTANCE_ID}_*.csv")
    step = seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")

    assert resolve(step).params["Source"] == "/apps/legal/outbox/Legal_I1_*.csv"


def test_unregistered_endpoint_is_rejected(seed, job, resolve):
    step = seed.step(job, 1, SourceEndpoint="NO_SUCH_ENDPOINT", Dest="incoming")

    with pytest.raises(ValueError, match="NO_SUCH_ENDPOINT.*not registered"):
        resolve(step)


def test_setting_both_a_raw_path_and_an_endpoint_is_rejected(seed, job, resolve):
    seed.endpoint("LEGAL_EXTRACTS", "/apps/legal/outbox")
    step = seed.step(job, 1, Source="incoming/*.csv", SourceEndpoint="LEGAL_EXTRACTS", Dest="staged")

    with pytest.raises(ValueError, match="either 'Source' or 'SourceEndpoint'"):
        resolve(step)


def test_endpoint_on_a_remote_site_is_rejected_for_a_local_file_step(seed, job, resolve):
    site = seed.site("JAYCO_SFTP", seed.entity("JAYCO"))
    seed.endpoint("JAYCO_DROP", "/inbound", site=site)
    step = seed.step(job, 1, Source="staged/*.csv", DestEndpoint="JAYCO_DROP")

    with pytest.raises(ValueError, match="JAYCO_SFTP.*only reach local paths"):
        resolve(step)


# --- other parameters and error context ---------------------------------------

def test_non_path_parameters_are_interpolated_and_passed_through(seed, job, resolve):
    seed.set_vars(job, MoveFlag="True")
    step = seed.step(job, 1, Source="a/*.csv", Dest="b", Move="${MoveFlag}", CreateFolder="False")

    resolved = resolve(step)

    assert resolved.params["Move"] == "True"
    assert resolved.params["CreateFolder"] == "False"


def test_errors_name_the_step(seed, job, resolve):
    step = seed.step(job, 3, title="Deliver files", Source="/etc/passwd", Dest="staged")

    with pytest.raises(ValueError, match=r"Step 3 \('Deliver files'\)"):
        resolve(step)
