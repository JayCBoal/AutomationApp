"""GET /api/v1/endpoints: the registered endpoints, as the job editor lists them."""
ROUTE = "/api/v1/endpoints"


def test_endpoints_are_listed_in_name_order_with_who_owns_them(client, db, seed):
    bank = seed.entity("ACME_BANK")
    seed.endpoint("legal_extracts", "${APP.Root}/outbox", "${FilePattern}", application=seed.application("LEGAL_APP"))
    seed.endpoint("ACME_PAYMENTS", "/inbound", "PAY_*.csv", application=seed.application("PAYMENTS_APP"),
                  site=seed.site("ACME_SFTP", bank))
    seed.endpoint("BARE", "/data/in")
    db.commit()

    response = client.get(ROUTE)

    assert response.status_code == 200
    assert [e["name"] for e in response.json()] == ["ACME_PAYMENTS", "BARE", "legal_extracts"]      # whatever their case
    payments, bare, legal = response.json()
    assert payments == {"name": "ACME_PAYMENTS", "application": "PAYMENTS_APP", "site": "ACME_SFTP",
                        "entity": "ACME_BANK", "path": "/inbound", "filename_pattern": "PAY_*.csv", "description": None}
    assert (legal["application"], legal["site"], legal["entity"]) == ("LEGAL_APP", None, None)
    assert (legal["path"], legal["filename_pattern"]) == ("${APP.Root}/outbox", "${FilePattern}")     # as registered
    assert (bare["application"], bare["site"]) == (None, None)


def test_endpoints_can_be_narrowed_by_part_of_the_name(client, db, seed):
    for name in ("LEGAL_EXTRACTS", "BILLING_INBOX", "BILLING_OUTBOX"):
        seed.endpoint(name, "/x")
    db.commit()

    names = lambda **criteria: [e["name"] for e in client.get(ROUTE, params=criteria).json()]

    assert names(name="billing") == ["BILLING_INBOX", "BILLING_OUTBOX"]
    assert names(name="BOX") == ["BILLING_INBOX", "BILLING_OUTBOX"]
    assert names(name="nothing") == []
    assert names(limit=1) == ["BILLING_INBOX"]


def test_no_endpoints_gives_an_empty_list(client):
    assert client.get(ROUTE).json() == []
