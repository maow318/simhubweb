import csv
import io
import os
import tempfile
import time
import unittest
import urllib.parse
from unittest import mock


os.environ.setdefault("SECRET_KEY", "test-secret-key-for-simhub-keeper-web-0001")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "test-data-key-for-simhub-keeper-web-0001")
os.environ["DATABASE"] = ":memory:"

from app.main import (  # noqa: E402
    LOGIN_MAX_FAILS,
    LOGIN_WINDOW,
    app,
    client_ip,
    clear_login_fails,
    get_db,
    hash_password,
    init_db,
    login_lock_remaining,
    insert_card,
    normalize_dto,
    parse_lpa_payload,
    record_login_fail,
    run_due_reminders,
)


class SimhubWebTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.config["DATABASE"] = os.path.join(self.tmp.name, "simhub-test.sqlite")
        app.config["TESTING"] = True
        app.config["SETUP_TOKEN"] = ""
        app.config["SIMHUB_PRODUCTION"] = False
        app.config["TRUST_PROXY"] = False
        app.config["GIFFGAFF_CLIENT_ID"] = ""
        app.config["GIFFGAFF_CLIENT_SECRET"] = ""
        app.config["GIFFGAFF_REDIRECT_URI"] = "giffgaff://auth/callback/"
        with app.app_context():
            init_db()
            get_db().execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                ("admin", hash_password("password123")),
            )
            get_db().commit()
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["csrf_token"] = "test-csrf-token"

    def tearDown(self):
        self.tmp.cleanup()

    def api_post(self, path, payload):
        return self.client.post(
            path,
            json=payload,
            headers={"X-CSRF-Token": "test-csrf-token"},
        )

    def api_delete(self, path):
        return self.client.delete(path, headers={"X-CSRF-Token": "test-csrf-token"})

    def assert_api_ok(self, response, status=200):
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        body = response.get_json()
        self.assertTrue(body["success"], body)
        return body["data"]

    def assert_api_error(self, response, code, status=400):
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        body = response.get_json()
        self.assertFalse(body["success"], body)
        self.assertEqual(body["code"], code)
        return body

    def test_countries_expose_all_backgrounds(self):
        data = self.assert_api_ok(self.client.get("/api/countries"))
        backgrounds = [item for item in data if item.get("bgAsset")]
        self.assertEqual(len(data), 252)
        self.assertEqual(len(backgrounds), 198)
        self.assertTrue(all(item["bgFile"].endswith(".jpg") for item in backgrounds))
        self.assertFalse(any(item["bgFile"].endswith(".png") for item in backgrounds))
        singapore = next(item for item in data if item["code"] == "SG")
        self.assertEqual(singapore["bgAsset"], "CardBackgroundSingaporeLighttrail")
        self.assertTrue(singapore["bgUrl"].endswith("CardBackgroundSingaporeLighttrail.jpg"))

    def test_normalize_dto_fills_country_flag_and_background(self):
        dto = normalize_dto({"carrier": "Singtel", "countryCode": "sg"})
        self.assertEqual(dto["countryCode"], "SG")
        self.assertEqual(dto["countryName"], "新加坡")
        self.assertEqual(dto["flag"], "🇸🇬")
        self.assertEqual(dto["cardBackgroundAssetName"], "CardBackgroundSingaporeLighttrail")

    def test_lpa_parser_accepts_encoded_qr_payload(self):
        result = parse_lpa_payload(
            "https://example.test/install?carddata=LPA%3A1%24rsp.example.com%24MATCHING-ID%24CONFIRM"
        )
        self.assertEqual(result["smdpAddress"], "rsp.example.com")
        self.assertEqual(result["activationCode"], "MATCHING-ID")
        self.assertEqual(result["confirmationCode"], "CONFIRM")
        self.assertTrue(result["complete"])

    def test_card_crud_and_batch_actions_are_structured(self):
        created = self.assert_api_ok(
            self.api_post(
                "/api/cards",
                {"carrier": "Test SIM", "countryCode": "US", "expiryDate": "2030-01-01"},
            ),
            status=201,
        )
        card_id = created["id"]

        tagged = self.assert_api_ok(
            self.api_post(
                "/api/cards/batch-update",
                {"action": "addTags", "ids": [card_id], "tags": ["bank", "backup"]},
            )
        )
        self.assertEqual(tagged["updated"], 1)
        card = self.assert_api_ok(self.client.get(f"/api/cards/{card_id}"))
        self.assertEqual(card["tags"], ["bank", "backup"])

        self.assert_api_error(
            self.api_post("/api/cards/batch-update", {"action": "rename", "ids": [card_id]}),
            "BAD_ACTION",
        )

        deleted = self.assert_api_ok(
            self.api_post("/api/cards/batch-update", {"action": "delete", "ids": [card_id]})
        )
        self.assertEqual(deleted["deleted"], 1)

    def test_csv_export_neutralizes_formula_cells(self):
        self.assert_api_ok(
            self.api_post(
                "/api/cards",
                {
                    "carrier": "=cmd|'/c calc'!A1",
                    "plan": "+SUM(1,1)",
                    "category": "@category",
                    "countryCode": "US",
                    "price": "-1+2",
                    "currentBalance": " =BALANCE",
                    "tags": ["=tag", "safe"],
                    "smdpAddress": "@smdp.example",
                    "activationCode": "+ACT",
                    "eid": "-EID",
                },
            ),
            status=201,
        )

        response = self.client.get("/export.csv")
        self.assertEqual(response.status_code, 200)
        rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
        exported = dict(zip(rows[0], rows[1]))

        self.assertEqual(exported["carrier"], "'=cmd|'/c calc'!A1")
        self.assertEqual(exported["plan"], "'+SUM(1,1)")
        self.assertEqual(exported["category"], "'@category")
        self.assertEqual(exported["price"], "'-1+2")
        self.assertEqual(exported["currentBalance"], "'=BALANCE")
        self.assertEqual(exported["tags"], "'=tag, safe")
        self.assertEqual(exported["smdpAddress"], "'@smdp.example")
        self.assertEqual(exported["activationCode"], "'+ACT")
        self.assertEqual(exported["eid"], "'-EID")

    def test_giffgaff_oauth_start_builds_pkce_login_url(self):
        app.config["GIFFGAFF_CLIENT_ID"] = "client-id"
        app.config["GIFFGAFF_CLIENT_SECRET"] = "client-secret"
        data = self.assert_api_ok(self.api_post("/api/giffgaff/oauth/start", {}))

        entry = urllib.parse.urlparse(data["entryUrl"])
        entry_qs = dict(urllib.parse.parse_qsl(entry.query))
        auth = urllib.parse.urlparse(entry_qs["redirect"])
        auth_qs = dict(urllib.parse.parse_qsl(auth.query))

        self.assertEqual(entry.netloc, "www.giffgaff.com")
        self.assertEqual(auth.netloc, "id.giffgaff.com")
        self.assertEqual(auth_qs["client_id"], "client-id")
        self.assertEqual(auth_qs["redirect_uri"], "giffgaff://auth/callback/")
        self.assertEqual(auth_qs["code_challenge_method"], "S256")
        self.assertTrue(auth_qs["code_challenge"])
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["giffgaff_oauth"]["state"], data["state"])
            self.assertTrue(sess["giffgaff_oauth"]["codeVerifier"])

    def test_giffgaff_apply_esim_returns_lpa_from_reference_flow(self):
        calls = []

        def fake_graphql(access_token, query, variables=None):
            calls.append((access_token, query, variables or {}))
            if "reserveESim" in query:
                self.assertEqual(variables["input"]["memberId"], "member-1")
                self.assertEqual(variables["input"]["userIntent"], "SWITCH")
                return {
                    "reserveESim": {
                        "id": "reservation-1",
                        "status": "RESERVED",
                        "esim": {"ssn": "reserved-ssn", "activationCode": "ACT-1"},
                    }
                }
            if "SwapSim" in query:
                self.assertEqual(variables["activationCode"], "ACT-1")
                self.assertEqual(variables["mfaSignature"], "sig-1")
                self.assertEqual(variables["mfaRef"], "ref-1")
                return {"swapSim": {"old": {"ssn": "old-ssn"}, "new": {"ssn": "new-ssn", "activationCode": "ACT-2"}}}
            if "getESims" in query:
                self.assertEqual(variables["deliveryStatus"], "DOWNLOADABLE")
                return {"eSims": [{"ssn": "new-ssn"}]}
            if "eSimDownloadToken" in query:
                self.assertEqual(variables["ssn"], "new-ssn")
                return {
                    "eSimDownloadToken": {
                        "id": "token-1",
                        "host": "rsp.giffgaff.example",
                        "matchingId": "MATCH-1",
                        "lpaString": "LPA:1$rsp.giffgaff.example$MATCH-1",
                    }
                }
            raise AssertionError(query)

        with mock.patch("app.main.giffgaff_graphql", side_effect=fake_graphql):
            data = self.assert_api_ok(
                self.api_post(
                    "/api/giffgaff/esim/apply",
                    {
                        "accessToken": "token-1",
                        "memberId": "member-1",
                        "mfaSignature": "sig-1",
                        "mfaRef": "ref-1",
                    },
                )
            )

        self.assertEqual(data["lpa"], "LPA:1$rsp.giffgaff.example$MATCH-1")
        self.assertEqual(data["parsed"]["smdpAddress"], "rsp.giffgaff.example")
        self.assertEqual(data["parsed"]["activationCode"], "MATCH-1")
        self.assertEqual(data["downloadToken"]["matchingId"], "MATCH-1")
        self.assertEqual(len(calls), 4)

    def test_import_preview_detects_duplicates_and_unknown_fields(self):
        first = self.assert_api_ok(
            self.api_post(
                "/api/cards",
                {
                    "carrier": "Existing",
                    "phoneNumber": "+15551234567",
                    "countryCode": "US",
                    "expiryDate": "2030-01-01",
                },
            ),
            status=201,
        )
        preview = self.assert_api_ok(
            self.api_post(
                "/api/import",
                {
                    "cards": [
                        {
                            "id": first["id"],
                            "carrier": "Duplicate ID",
                            "phoneNumber": "+15550000000",
                            "unknownFutureField": "ignored",
                        },
                        {
                            "carrier": "Duplicate phone",
                            "phoneNumber": "+15551234567",
                        },
                        {
                            "carrier": "Fresh",
                            "countryCode": "AE",
                            "phoneNumber": "+15557654321",
                            "smdpAddress": "rsp.example.com",
                            "activationCode": "ABC",
                        },
                        {
                            "carrier": "Duplicate within import",
                            "phoneNumber": "+15557654321",
                        },
                    ]
                },
            )
        )
        self.assertEqual(preview["summary"]["ready"], 1)
        self.assertEqual(preview["summary"]["duplicates"]["id"], 1)
        self.assertEqual(preview["summary"]["duplicates"]["phoneNumber"], 2)
        self.assertIn("unknownFutureField", preview["fields"]["unknown"])
        fresh = next(row for row in preview["rows"] if row["carrier"] == "Fresh")
        self.assertEqual(fresh["country"], "阿联酋")
        self.assertTrue(fresh["hasLPA"])

    def test_reminder_scan_is_safe_without_channels(self):
        with app.app_context():
            init_db()
            insert_card(
                normalize_dto(
                    {
                        "carrier": "Quiet SIM",
                        "countryCode": "JP",
                        "expiryDate": "2030-01-01",
                    }
                )
            )
            get_db().commit()
            stats = run_due_reminders()
        self.assertEqual(stats["scanned"], 1)
        self.assertEqual(stats["matched"], 0)
        self.assertEqual(stats["sent"], 0)
        self.assertEqual(stats["failed"], 0)

    def test_setup_token_blocks_admin_creation_until_matched(self):
        app.config["SETUP_TOKEN"] = "setup-secret"
        with app.app_context():
            init_db()
            get_db().execute("DELETE FROM users")
            get_db().commit()
        with self.client.session_transaction() as sess:
            sess["csrf_token"] = "setup-csrf"

        bad = self.client.post(
            "/setup",
            data={
                "csrf_token": "setup-csrf",
                "setup_token": "wrong",
                "username": "admin",
                "password": "password123",
                "confirm": "password123",
            },
        )
        self.assertEqual(bad.status_code, 200)
        self.assertIn("SETUP_TOKEN", bad.get_data(as_text=True))
        with app.app_context():
            self.assertEqual(get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

        good = self.client.post(
            "/setup",
            data={
                "csrf_token": "setup-csrf",
                "setup_token": "setup-secret",
                "username": "admin",
                "password": "password123",
                "confirm": "password123",
            },
        )
        self.assertEqual(good.status_code, 302)
        with app.app_context():
            self.assertEqual(get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)

    def test_setup_without_token_keeps_local_first_run_flow(self):
        app.config["SETUP_TOKEN"] = ""
        with app.app_context():
            init_db()
            get_db().execute("DELETE FROM users")
            get_db().commit()
        with self.client.session_transaction() as sess:
            sess["csrf_token"] = "setup-csrf"

        response = self.client.post(
            "/setup",
            data={
                "csrf_token": "setup-csrf",
                "username": "admin",
                "password": "password123",
                "confirm": "password123",
            },
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)

    def test_client_ip_uses_forwarded_for_only_when_trusted(self):
        app.config["TRUST_PROXY"] = True
        with app.test_request_context(
            "/login",
            headers={"X-Forwarded-For": "198.51.100.24"},
            environ_base={"REMOTE_ADDR": "172.18.0.10"},
        ):
            self.assertEqual(client_ip(), "198.51.100.24")

        app.config["TRUST_PROXY"] = False
        with app.test_request_context(
            "/login",
            headers={"X-Forwarded-For": "198.51.100.24"},
            environ_base={"REMOTE_ADDR": "172.18.0.10"},
        ):
            self.assertEqual(client_ip(), "172.18.0.10")

    def test_login_rate_limit_locks_and_expires_from_database(self):
        ip = "203.0.113.50"
        with app.app_context():
            init_db()
            clear_login_fails(ip)
            for _ in range(LOGIN_MAX_FAILS):
                record_login_fail(ip)
            self.assertGreater(login_lock_remaining(ip), 0)

            get_db().execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))
            old_ts = time.time() - LOGIN_WINDOW - 5
            for _ in range(LOGIN_MAX_FAILS):
                get_db().execute("INSERT INTO login_attempts (ip, ts) VALUES (?, ?)", (ip, old_ts))
            get_db().commit()
            self.assertEqual(login_lock_remaining(ip), 0)
            self.assertEqual(
                get_db().execute("SELECT COUNT(*) FROM login_attempts WHERE ip = ?", (ip,)).fetchone()[0],
                0,
            )

    def test_successful_login_clears_persisted_failures(self):
        ip = "203.0.113.77"
        with app.app_context():
            init_db()
            clear_login_fails(ip)
            record_login_fail(ip)
            record_login_fail(ip)
            self.assertEqual(
                get_db().execute("SELECT COUNT(*) FROM login_attempts WHERE ip = ?", (ip,)).fetchone()[0],
                2,
            )
        with self.client.session_transaction() as sess:
            sess.pop("user_id", None)
            sess["csrf_token"] = "login-csrf"

        response = self.client.post(
            "/login",
            data={"csrf_token": "login-csrf", "username": "admin", "password": "password123"},
            environ_overrides={"REMOTE_ADDR": ip},
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(
                get_db().execute("SELECT COUNT(*) FROM login_attempts WHERE ip = ?", (ip,)).fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
