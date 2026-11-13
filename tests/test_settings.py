import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import storage


class StatusBarSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patches = patch.multiple(storage, _LOG_DIR=str(self.root), _DB_CONN=None)
        patches.start()
        self.addCleanup(patches.stop)

    def test_defaults_to_all_fields_and_persists_selection_across_connections(self):
        self.assertEqual(storage.get_status_bar_fields(), storage.STATUS_BAR_FIELDS)
        self.assertEqual(storage.set_status_bar_fields(["quota_reset", "work_hours"]), ("work_hours", "quota_reset"))
        self.assertEqual(storage.get_status_bar_fields(), ("work_hours", "quota_reset"))
        self.assertTrue((self.root / storage._LOCAL_SETTINGS_DB_FILENAME).is_file())

    def test_empty_selection_is_preserved_and_all_fields_can_be_restored(self):
        self.assertEqual(storage.set_status_bar_fields([]), ())
        self.assertEqual(storage.get_status_bar_fields(), ())
        storage.set_status_bar_fields(storage.STATUS_BAR_FIELDS)
        self.assertEqual(storage.get_status_bar_fields(), storage.STATUS_BAR_FIELDS)

    def test_unknown_fields_are_rejected_without_changing_saved_selection(self):
        storage.set_status_bar_fields(["tokens"])
        with self.assertRaises(ValueError):
            storage.set_status_bar_fields(["work_hours", "unknown"])
        self.assertEqual(storage.get_status_bar_fields(), ("tokens",))

    def test_settings_use_only_local_database_and_preserve_other_preferences(self):
        with (
            patch.object(storage, "get_connection", side_effect=AssertionError("unexpected activity database access")),
            patch.object(storage, "sync_to_icloud", side_effect=AssertionError("unexpected iCloud sync")),
        ):
            storage.set_token_display_range(20, 80)
            storage.set_status_bar_fields(["tokens"])
            self.assertEqual(storage.get_status_bar_fields(), ("tokens",))
            self.assertEqual(storage.get_token_display_range(), (20, 80))
        self.assertIsNone(storage._DB_CONN)


if __name__ == "__main__":
    unittest.main()
