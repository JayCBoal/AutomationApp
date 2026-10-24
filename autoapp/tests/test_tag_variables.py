"""
Variables from tags: what a job, an application, an entity or an endpoint gets
from the tags it carries, and what happens when its tags disagree.
"""
import pytest

from core.models import SettingValue, Variable
from engine.scope_engine import ScopeResolutionEngine
from engine import tag_vars


@pytest.fixture
def context(db, tmp_path):
    def _context(job):
        db.flush()
        engine = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id="I1",
                                       global_config={"WORKING_ROOT": str(tmp_path / "work")})
        engine.build_context()
        return engine
    return _context


# --- A job's tags ------------------------------------------------------------------------------

def test_a_job_gets_its_tags_variables(seed, context):
    job = seed.job("DEV-LOAD")
    seed.attach(seed.tag("Finance", Ledger="GL01"), job)

    assert context(job).interpolate("${Ledger}") == "GL01"


def test_a_tag_inherits_its_parents_variables_and_overrides_them(seed, context):
    job = seed.job("DEV-LOAD")
    finance = seed.tag("Finance", Ledger="GL01", Region="EU")
    reporting = seed.tag("Reporting", parent=finance, Region="US")
    seed.attach(reporting, job)

    engine = context(job)

    assert engine.interpolate("${Ledger}-${Region}") == "GL01-US"


def test_nesting_goes_as_deep_as_wanted(seed, context):
    job = seed.job("DEV-LOAD")
    top = seed.tag("A", Level="a", Top="yes")
    middle = seed.tag("B", parent=top, Level="b")
    bottom = seed.tag("C", parent=middle)
    seed.attach(bottom, job)

    assert context(job).interpolate("${Level} ${Top}") == "b yes"


def test_the_jobs_own_variable_beats_its_tags(seed, context):
    job = seed.job("DEV-LOAD", Ledger="MINE")
    seed.attach(seed.tag("Finance", Ledger="GL01"), job)

    assert context(job).interpolate("${Ledger}") == "MINE"


# --- Conflicts ---------------------------------------------------------------------------------

def test_two_tags_that_disagree_make_the_variable_an_error_to_use(seed, context):
    job = seed.job("DEV-LOAD")
    seed.attach(seed.tag("Finance", Server="fin01"), job)
    seed.attach(seed.tag("Ops", Server="ops01"), job)

    engine = context(job)

    with pytest.raises(ValueError) as error:
        engine.interpolate("//${Server}/share")
    assert "Variable 'Server' is given different values by tags Finance and Ops" in str(error.value)
    assert "fin01" not in str(error.value)            # values are not shown: either might be a secret


def test_a_conflict_on_a_variable_the_job_does_not_use_does_no_harm(seed, context):
    job = seed.job("DEV-LOAD")
    seed.attach(seed.tag("Finance", Server="fin01", Ledger="GL01"), job)
    seed.attach(seed.tag("Ops", Server="ops01"), job)

    assert context(job).interpolate("${Ledger}") == "GL01"


def test_the_same_value_from_two_tags_is_not_a_conflict(seed, context):
    job = seed.job("DEV-LOAD")
    seed.attach(seed.tag("Finance", Server="shared01"), job)
    seed.attach(seed.tag("Ops", Server="shared01"), job)

    assert context(job).interpolate("${Server}") == "shared01"


def test_one_parent_reached_through_two_tags_is_not_a_conflict(seed, context):
    job = seed.job("DEV-LOAD")
    finance = seed.tag("Finance", Ledger="GL01")
    seed.attach(seed.tag("Reporting", parent=finance), job)
    seed.attach(seed.tag("Payroll", parent=finance), job)

    assert context(job).interpolate("${Ledger}") == "GL01"


def test_a_child_that_overrides_its_parent_can_conflict_with_a_sibling(seed, context):
    job = seed.job("DEV-LOAD")
    finance = seed.tag("Finance", Ledger="GL01")
    seed.attach(seed.tag("Reporting", parent=finance, Ledger="GL02"), job)
    seed.attach(seed.tag("Payroll", parent=finance), job)

    with pytest.raises(ValueError) as error:
        context(job).interpolate("${Ledger}")
    assert "Finance / Payroll (from Finance) and Finance / Reporting" in str(error.value) \
        or "Finance / Reporting and Finance / Payroll (from Finance)" in str(error.value)


def test_the_jobs_own_variable_settles_a_conflict(seed, context):
    job = seed.job("DEV-LOAD", Server="mine01")
    seed.attach(seed.tag("Finance", Server="fin01"), job)
    seed.attach(seed.tag("Ops", Server="ops01"), job)

    assert context(job).interpolate("${Server}") == "mine01"


def test_a_conflict_hides_a_lower_levels_value_rather_than_falling_back_to_it(seed, context, tmp_path):
    """Falling back would quietly use a value neither tag meant."""
    app = seed.application("BILLING_APP", Root=str(tmp_path), Server="app01")
    endpoint = seed.endpoint("BILLING_INBOX", "${Server}", application=app)
    job = seed.job("DEV-LOAD")
    seed.attach(seed.tag("Finance", Server="fin01"), job)
    seed.attach(seed.tag("Ops", Server="ops01"), job)

    with pytest.raises(ValueError, match="different values by tags Finance and Ops"):
        context(job).interpolate(endpoint.Path, endpoint=endpoint)


# --- Tags on applications, entities and endpoints --------------------------------------------

def test_an_applications_tags_reach_wherever_its_variables_do(seed, context):
    app = seed.application("BILLING_APP")
    seed.attach(seed.tag("Shared_Drive", Root="/mnt/shared"), app)
    endpoint = seed.endpoint("BILLING_INBOX", "${APP.Root}/inbox", application=app)
    job = seed.job("DEV-LOAD")

    engine = context(job)

    assert engine.interpolate(endpoint.Path, endpoint=endpoint) == "/mnt/shared/inbox"
    assert engine.interpolate("${APP:BILLING_APP.Root}") == "/mnt/shared"
    with pytest.raises(ValueError):
        engine.interpolate("${Root}")                    # outside the endpoint, the application is not in reach


def test_an_applications_own_variable_beats_its_tags(seed, context):
    app = seed.application("BILLING_APP", Root="/data/billing")
    seed.attach(seed.tag("Shared_Drive", Root="/mnt/shared"), app)
    endpoint = seed.endpoint("BILLING_INBOX", "${APP.Root}/inbox", application=app)

    assert context(seed.job("DEV-LOAD")).interpolate(endpoint.Path, endpoint=endpoint) == "/data/billing/inbox"


def test_an_entitys_tags_reach_its_sites_endpoints(seed, context):
    bank = seed.entity("ACME_BANK")
    seed.attach(seed.tag("Partner", Inbound="/inbound"), bank)
    endpoint = seed.endpoint("ACME_PAYMENTS", "${ENTITY.Inbound}/payments", site=seed.site("ACME_SFTP", bank))

    assert context(seed.job("DEV-LOAD")).interpolate(endpoint.Path, endpoint=endpoint) == "/inbound/payments"


def test_an_endpoints_tags_feed_its_path(seed, context):
    endpoint = seed.endpoint("BILLING_INBOX", "${Drive}/inbox")
    seed.attach(seed.tag("Shared_Drive", Drive="/mnt/shared"), endpoint)

    assert context(seed.job("DEV-LOAD")).interpolate(endpoint.Path, endpoint=endpoint) == "/mnt/shared/inbox"


def test_two_tags_on_an_application_that_disagree_are_a_conflict_there(seed, context):
    app = seed.application("BILLING_APP")
    seed.attach(seed.tag("Drive_A", Root="/a"), app)
    seed.attach(seed.tag("Drive_B", Root="/b"), app)
    endpoint = seed.endpoint("BILLING_INBOX", "${APP.Root}/inbox", application=app)

    with pytest.raises(ValueError, match="different values by tags Drive_A and Drive_B"):
        context(seed.job("DEV-LOAD")).interpolate(endpoint.Path, endpoint=endpoint)


def test_the_jobs_tags_beat_the_endpoints_application_by_default(seed, context):
    app = seed.application("BILLING_APP", Folder="from_app")
    endpoint = seed.endpoint("BILLING_INBOX", "/data/${Folder}", application=app)
    job = seed.job("DEV-LOAD")
    seed.attach(seed.tag("Override", Folder="from_tag"), job)

    assert context(job).interpolate(endpoint.Path, endpoint=endpoint) == "/data/from_tag"


# --- Precedence is a setting -------------------------------------------------------------------

def test_the_precedence_can_be_changed(db, seed, context):
    app = seed.application("BILLING_APP", Folder="from_app")
    endpoint = seed.endpoint("BILLING_INBOX", "/data/${Folder}", application=app)
    job = seed.job("DEV-LOAD", Folder="from_job")
    db.add(SettingValue(SettingKey="VariablePrecedence", SettingValue="SYS,ENTITY,TAG,JOB,ENDPOINT,APP"))

    assert context(job).interpolate(endpoint.Path, endpoint=endpoint) == "/data/from_app"


# --- Naming a tag explicitly -------------------------------------------------------------------

def test_a_job_can_name_one_of_its_tags_or_their_parents(seed, context):
    job = seed.job("DEV-LOAD")
    finance = seed.tag("Finance", Ledger="GL01")
    seed.attach(seed.tag("Reporting", parent=finance, Ledger="GL02"), job)

    engine = context(job)

    assert engine.interpolate("${TAG:Finance/Reporting.Ledger}") == "GL02"
    assert engine.interpolate("${TAG:Finance.Ledger}") == "GL01"


def test_naming_a_tag_explicitly_picks_one_side_of_a_conflict(seed, context):
    job = seed.job("DEV-LOAD")
    seed.attach(seed.tag("Finance", Server="fin01"), job)
    seed.attach(seed.tag("Ops", Server="ops01"), job)

    assert context(job).interpolate("${TAG:Ops.Server}") == "ops01"


def test_a_job_cannot_name_a_tag_it_does_not_carry(seed, context):
    job = seed.job("DEV-LOAD")
    seed.tag("Finance", Ledger="GL01")

    with pytest.raises(ValueError, match="names tag 'Finance', which is not one of this job's tags"):
        context(job).interpolate("${TAG:Finance.Ledger}")


# --- Paths -------------------------------------------------------------------------------------

def test_tags_with_the_same_name_under_different_parents_are_different_tags(db, seed):
    test_env = seed.tag("TEST", parent=seed.tag("Environment"))
    test_purpose = seed.tag("TEST", parent=seed.tag("Purpose"))

    assert tag_vars.tag_path(test_env) == "Environment/TEST"
    assert tag_vars.find_by_path(db, "Purpose/TEST").MasterObject_id == test_purpose.MasterObject_id
    assert tag_vars.find_by_path(db, "Purpose / TEST").MasterObject_id == test_purpose.MasterObject_id
    assert tag_vars.find_by_path(db, "TEST") is None
