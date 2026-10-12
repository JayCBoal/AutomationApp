"""
Scope engine: which value a ${...} placeholder resolves to.

Each test seeds a few real rows into a throwaway database, builds the context
for a job, and checks the interpolated text.
"""
import re

import pytest

from engine.scope_engine import ScopeResolutionEngine


def engine_for(db, job, instance_id="INST_001"):
    engine = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id=instance_id)
    engine.build_context()
    return engine


def test_process_variable_resolves_for_its_job(db, seed):
    proc = seed.process(WorkingFolder="/data/working")
    job = seed.job(proc)

    assert engine_for(db, job).interpolate("${WorkingFolder}/in") == "/data/working/in"


def test_job_variable_overrides_process_variable(db, seed):
    proc = seed.process(Region="PROCESS_VALUE")
    job = seed.job(proc, Region="JOB_VALUE")

    assert engine_for(db, job).interpolate("${Region}") == "JOB_VALUE"


def test_explicit_scope_reaches_past_the_override(db, seed):
    proc = seed.process(Region="PROCESS_VALUE")
    job = seed.job(proc, Region="JOB_VALUE")
    engine = engine_for(db, job)

    assert engine.interpolate("${PROC.Region}") == "PROCESS_VALUE"
    assert engine.interpolate("${JOB.Region}") == "JOB_VALUE"


def test_variables_of_other_jobs_and_processes_do_not_leak(db, seed):
    proc = seed.process("DEV-PROC-A")
    job = seed.job(proc, "JOB_A")
    other_proc = seed.process("DEV-PROC-B", Secret="B_PROCESS")
    seed.job(other_proc, "JOB_B", Other="B_JOB")
    seed.job(proc, "JOB_A2", Sibling="A2_JOB")

    context = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id="X").build_context()

    assert "Secret" not in context
    assert "Other" not in context
    assert "Sibling" not in context


def test_sys_macros(db, seed):
    job = seed.job(seed.process())
    engine = engine_for(db, job, instance_id="INST_42")

    assert engine.interpolate("run_${SYS:INSTANCE_ID}") == "run_INST_42"
    assert re.fullmatch(r"\d{8}", engine.interpolate("${SYS:YYYYMMDD}"))


def test_named_entity_and_application_lookup(db, seed):
    seed.entity("JAYCO", TaxID="12-3456789")
    seed.application("LEGAL_APP", Owner="legal-team")
    job = seed.job(seed.process())
    engine = engine_for(db, job)

    assert engine.interpolate("${ENTITY:JAYCO.TaxID}") == "12-3456789"
    assert engine.interpolate("${APP:LEGAL_APP.Owner}") == "legal-team"


def test_several_placeholders_in_one_string(db, seed):
    proc = seed.process(Folder="/data", Prefix="Legal")
    job = seed.job(proc, Ext="csv")

    assert engine_for(db, job).interpolate("${Folder}/${Prefix}_batch.${Ext}") == "/data/Legal_batch.csv"


def test_text_without_placeholders_is_unchanged(db, seed):
    engine = engine_for(db, seed.job(seed.process()))

    assert engine.interpolate("/plain/path.csv") == "/plain/path.csv"
    assert engine.interpolate(None) is None


def test_unknown_job_raises(db, seed):
    engine = ScopeResolutionEngine(db=db, job_id=9999, instance_id="X")

    with pytest.raises(ValueError, match="9999"):
        engine.build_context()


def test_variable_containing_another_variable_is_fully_resolved(db, seed):
    proc = seed.process(Root="/data", WorkingFolder="${Root}/working")
    job = seed.job(proc, Target="${WorkingFolder}/${SYS:INSTANCE_ID}")

    assert engine_for(db, job, "INST_7").interpolate("${Target}/out.csv") == "/data/working/INST_7/out.csv"


def test_unresolved_placeholder_raises_and_names_it(db, seed):
    engine = engine_for(db, seed.job(seed.process(Known="x")))

    with pytest.raises(ValueError, match=r"\$\{NoSuchVariable\}"):
        engine.interpolate("${Known}/${NoSuchVariable}/in")


def test_unresolved_placeholder_inside_a_variable_raises(db, seed):
    engine = engine_for(db, seed.job(seed.process(WorkingFolder="${Missing}/working")))

    with pytest.raises(ValueError, match=r"\$\{Missing\}"):
        engine.interpolate("${WorkingFolder}")


def test_circular_variable_reference_raises(db, seed):
    engine = engine_for(db, seed.job(seed.process(A="${B}", B="${A}")))

    with pytest.raises(ValueError, match="circular"):
        engine.interpolate("${A}")


def test_working_folder_is_working_root_plus_process_name(db, seed, tmp_path):
    job = seed.job(seed.process("DEV-LEGAL-PROC"))
    engine = ScopeResolutionEngine(
        db=db, job_id=job.MasterObject_id, instance_id="X", global_config={"WORKING_ROOT": str(tmp_path)}
    )
    engine.build_context()

    assert engine.working_folder == str(tmp_path / "DEV-LEGAL-PROC")
    assert engine.interpolate("${SYS:WORKING_FOLDER}/in") == str(tmp_path / "DEV-LEGAL-PROC" / "in")


def test_working_folder_is_undefined_without_a_working_root(db, seed, monkeypatch):
    monkeypatch.delenv("AUTOAPP_WORKING_ROOT", raising=False)
    engine = engine_for(db, seed.job(seed.process()))

    assert engine.working_folder is None


def test_app_and_entity_scopes_come_from_the_endpoint(db, seed):
    legal_app = seed.application("LEGAL_APP", Root="/apps/legal")
    jayco = seed.entity("JAYCO", ClientCode="JC01")
    app_endpoint = seed.endpoint("LEGAL_OUT", "${APP.Root}/outbox", application=legal_app)
    site_endpoint = seed.endpoint("JAYCO_IN", "/inbound/${ENTITY.ClientCode}", site=seed.site("JAYCO_SFTP", jayco))
    engine = engine_for(db, seed.job(seed.process()))

    assert engine.interpolate(app_endpoint.Path, endpoint=app_endpoint) == "/apps/legal/outbox"
    assert engine.interpolate(site_endpoint.Path, endpoint=site_endpoint) == "/inbound/JC01"


def test_app_scope_is_empty_outside_an_endpoint_and_does_not_leak_between_them(db, seed):
    legal_app = seed.application("LEGAL_APP", Root="/apps/legal")
    billing_app = seed.application("BILLING_APP", Root="/apps/billing")
    legal = seed.endpoint("LEGAL_OUT", "${APP.Root}/out", application=legal_app)
    billing = seed.endpoint("BILLING_IN", "${APP.Root}/in", application=billing_app)
    engine = engine_for(db, seed.job(seed.process()))

    assert engine.interpolate(legal.Path, endpoint=legal) == "/apps/legal/out"
    assert engine.interpolate(billing.Path, endpoint=billing) == "/apps/billing/in"
    with pytest.raises(ValueError, match=r"\$\{APP\.Root\}"):
        engine.interpolate("${APP.Root}/anything")
