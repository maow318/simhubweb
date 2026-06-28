import os
import tempfile
import unittest


os.environ.setdefault("SECRET_KEY", "test-secret-key-for-simhub-keeper-web-0001")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "test-data-key-for-simhub-keeper-web-0001")
os.environ["DATABASE"] = ":memory:"

from app.main import (  # noqa: E402
    app,
    get_db,
    hash_password,
    init_db,
    insert_card,
    normalize_dto,
    parse_lpa_payload,
    run_due_reminders,
)


class SimhubWebTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.config["DATABASE"] = os.path.join(self.tmp.name, "simhub-test.sqlite")
        app.config["TESTING"] = True
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


if __name__ == "__main__":
    unittest.main()
