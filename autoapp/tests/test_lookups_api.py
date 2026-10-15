"""GET /api/v1/lookups: the names pages offer in their drop-downs."""
ROUTE = "/api/v1/lookups"


def test_every_kind_of_name_is_listed_in_order_with_a_label_to_tell_entries_apart(client, db, seed, run_runner, load_spool):
    bank = seed.entity("ACME_BANK")
    legal = seed.application("legal_app")
    seed.application("BILLING_APP").Description = "Client billing"
    seed.endpoint("PAYMENTS", "/inbound", "PAY_*.csv", application=legal, site=seed.site("ACME_SFTP", bank))
    seed.endpoint("EXTRACTS", "/out", "*.csv", application=legal)
    seed.job("DEV-B").Description = "Second job"
    job = seed.job("dev-a")
    seed.step(job, 1, Source="in/*.csv", Dest="out", AllowNoFiles="True")
    run_runner("dev-a", "1", "--scheduler", "RMJ_FINANCE")
    run_runner("dev-a", "2", "--scheduler", "CTM_PROD")
    run_runner("dev-a", "3", "--scheduler", "CTM_PROD")
    run_runner("dev-a", "4")
    load_spool()
    db.commit()

    lookups = client.get(ROUTE).json()

    values = lambda kind: [entry["value"] for entry in lookups[kind]]
    labels = lambda kind: {entry["value"]: entry["label"] for entry in lookups[kind]}
    assert sorted(lookups) == ["applications", "endpoints", "entities", "jobs", "schedulers", "sites", "tags"]
    assert values("endpoints") == ["EXTRACTS", "PAYMENTS"]
    assert labels("endpoints")["EXTRACTS"] == "legal_app  \u2014  /out/*.csv"
    assert labels("endpoints")["PAYMENTS"] == "legal_app \u00b7 ACME_BANK \u00b7 ACME_SFTP  \u2014  /inbound/PAY_*.csv"
    assert values("applications") == ["BILLING_APP", "legal_app"]              # in order whatever their case
    assert labels("applications")["BILLING_APP"] == "Client billing"
    assert values("entities") == ["ACME_BANK"]
    assert values("sites") == ["ACME_SFTP"] and "ACME_BANK" in labels("sites")["ACME_SFTP"]
    assert values("jobs") == ["dev-a", "DEV-B"] and labels("jobs")["DEV-B"] == "Second job"
    assert values("schedulers") == ["CTM_PROD", "RMJ_FINANCE"]                # each once; runs with none left out


def test_an_empty_database_gives_empty_lists(client):
    assert client.get(ROUTE).json() == {
        "endpoints": [], "applications": [], "entities": [], "sites": [], "jobs": [], "schedulers": [], "tags": []}
