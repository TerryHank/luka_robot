"""Explicit face/voice associations preserve the existing speaker UUID namespace."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import numpy as np

from person_follow.identity import IdentityStore


def samples(axis=0):
    result = []
    for offset in (-0.08, 0.0, 0.08):
        vector = np.zeros(128, dtype=np.float32)
        vector[axis] = 1.0
        vector[2] = offset
        result.append(vector)
    return result


class IdentityLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.face_path = Path(self.tmp.name) / "faces.sqlite3"
        # Spaces and # require proper file-URI quoting on both Windows and Linux.
        self.voice_path = Path(self.tmp.name) / "voice #profiles.sqlite3"
        with closing(sqlite3.connect(self.voice_path)) as db, db:
            # Deliberately no vectors/owner fields: linking needs metadata only.
            db.execute("CREATE TABLE profiles(id TEXT PRIMARY KEY,name TEXT,ready INTEGER)")
            db.executemany("INSERT INTO profiles VALUES(?,?,?)",
                           [("voice-a", "主人", 1), ("voice-b", "家人", 1),
                            ("pending", "尚未录完", 0)])
        self.store = IdentityStore(self.face_path, voice_db_path=self.voice_path)
        self.addCleanup(self.store.close)
        self.a = self.store.add_profile("主人", samples())["id"]
        self.b = self.store.add_profile("家人", samples(1))["id"]

    def profile(self, ident):
        return next(p for p in self.store.list_profiles() if p["id"] == ident)

    def voice_sql(self, sql, args=()):
        with closing(sqlite3.connect(self.voice_path)) as db, db:
            db.execute(sql, args)

    def assert_no_identity(self, profile, state):
        self.assertEqual(profile["voice_link"]["state"], state)
        self.assertNotIn("person_id", profile)
        self.assertNotIn("profile_id", profile["voice_link"])
        self.assertNotIn("name", profile["voice_link"])

    def test_same_names_do_not_link_implicitly_or_change_old_shape(self):
        for p in self.store.list_profiles():
            self.assertEqual(set(p), {"id", "name", "created_at", "sample_count"})

    def test_explicit_link_persists_exact_voice_uuid(self):
        result = self.store.bind_voice_profile(self.a, "voice-a")
        self.assertEqual(result["state"], "linked")
        self.assertEqual(result["profile_id"], "voice-a")
        reopened = IdentityStore(self.face_path, voice_db_path=self.voice_path)
        self.addCleanup(reopened.close)
        p = next(p for p in reopened.list_profiles() if p["id"] == self.a)
        self.assertEqual(p["person_id"], "voice-a")
        self.assertEqual(p["id"], self.a)
        self.assertEqual(p["voice_link"]["name"], "主人")
        self.assertEqual(p["sample_count"], 3)

    def test_metadata_read_does_not_change_voice_database(self):
        before = self.voice_path.read_bytes()
        with patch("person_follow.identity.sqlite3.connect", wraps=sqlite3.connect) as connect:
            self.store.bind_voice_profile(self.a, "voice-a")
            self.store.list_profiles()
        for call in connect.call_args_list:
            self.assertTrue(call.args[0].endswith("?mode=ro"))
            self.assertTrue(call.kwargs["uri"])
            self.assertEqual(call.kwargs["timeout"], 0.05)
        self.assertEqual(before, self.voice_path.read_bytes())

    def test_idempotent_bind_retains_timestamp_and_conflicts_never_overwrite(self):
        first = self.store.bind_voice_profile(self.a, "voice-a")
        self.assertEqual(first, self.store.bind_voice_profile(self.a, "voice-a"))
        with self.assertRaisesRegex(ValueError, "different voice"):
            self.store.bind_voice_profile(self.a, "voice-b")
        with self.assertRaisesRegex(ValueError, "another face"):
            self.store.bind_voice_profile(self.b, "voice-a")
        self.assertEqual(self.profile(self.a)["person_id"], "voice-a")
        self.assertNotIn("voice_link", self.profile(self.b))

    def test_two_people_keep_separate_ids_even_when_display_names_change(self):
        self.store.bind_voice_profile(self.a, "voice-a")
        self.store.bind_voice_profile(self.b, "voice-b")
        self.voice_sql("UPDATE profiles SET name='主人' WHERE id='voice-b'")
        self.assertEqual(self.profile(self.a)["person_id"], "voice-a")
        self.assertEqual(self.profile(self.b)["person_id"], "voice-b")

    def test_delete_face_cascades_only_its_link_and_releases_voice_slot(self):
        self.store.bind_voice_profile(self.a, "voice-a")
        self.store.bind_voice_profile(self.b, "voice-b")
        self.assertTrue(self.store.delete_profile(self.a))
        rows = self.store._db.execute("SELECT face_profile_id FROM face_voice_links").fetchall()
        self.assertEqual(rows, [(self.b,)])
        replacement = self.store.add_profile("主人", samples())["id"]
        self.store.bind_voice_profile(replacement, "voice-a")
        self.assertEqual(self.profile(replacement)["person_id"], "voice-a")

    def test_delete_voice_invalidates_and_same_name_new_uuid_never_inherits(self):
        self.store.bind_voice_profile(self.a, "voice-a")
        self.voice_sql("DELETE FROM profiles WHERE id='voice-a'")
        self.assert_no_identity(self.profile(self.a), "missing")
        self.voice_sql("INSERT INTO profiles VALUES('new-voice-a','主人',1)")
        self.assert_no_identity(self.profile(self.a), "missing")
        with self.assertRaisesRegex(ValueError, "different voice"):
            self.store.bind_voice_profile(self.a, "new-voice-a")

    def test_unlink_allows_explicit_rebind_without_removing_face_or_voice(self):
        self.store.bind_voice_profile(self.a, "voice-a")
        before = self.voice_path.read_bytes()
        self.assertTrue(self.store.unlink_voice_profile(self.a))
        self.assertFalse(self.store.unlink_voice_profile(self.a))
        self.assertNotIn("voice_link", self.profile(self.a))
        self.assertEqual(self.profile(self.a)["sample_count"], 3)
        self.store.bind_voice_profile(self.a, "voice-b")
        self.assertEqual(self.profile(self.a)["person_id"], "voice-b")
        self.assertEqual(before, self.voice_path.read_bytes())

    def test_unready_and_missing_profiles_rejected_without_binding(self):
        for voice in ("pending", "absent"):
            with self.assertRaisesRegex(ValueError, "not fully enrolled"):
                self.store.bind_voice_profile(self.a, voice)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.store.bind_voice_profile("missing-face", "voice-a")
        self.assertNotIn("voice_link", self.profile(self.a))

    def test_ready_retracted_invalidates_existing_link(self):
        self.store.bind_voice_profile(self.a, "voice-a")
        self.voice_sql("UPDATE profiles SET ready=0 WHERE id='voice-a'")
        self.assert_no_identity(self.profile(self.a), "missing")

    def test_unavailable_database_fails_closed_without_creating_or_removing_link(self):
        self.store.bind_voice_profile(self.a, "voice-a")
        saved = self.voice_path.with_name("voice-backup.sqlite3")
        self.voice_path.rename(saved)
        self.assert_no_identity(self.profile(self.a), "unavailable")
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.store.bind_voice_profile(self.b, "voice-b")
        self.assertFalse(self.voice_path.exists())
        saved.rename(self.voice_path)
        self.assertEqual(self.profile(self.a)["person_id"], "voice-a")

    def test_exclusive_voice_lock_is_unavailable_then_recovers(self):
        self.store.bind_voice_profile(self.a, "voice-a")
        lock = sqlite3.connect(self.voice_path)
        try:
            lock.execute("BEGIN EXCLUSIVE")
            self.assert_no_identity(self.profile(self.a), "unavailable")
        finally:
            lock.rollback()
            lock.close()
        self.assertEqual(self.profile(self.a)["person_id"], "voice-a")

    def test_wrong_schema_is_unavailable_not_missing(self):
        self.store.bind_voice_profile(self.a, "voice-a")
        self.voice_sql("ALTER TABLE profiles RENAME TO old_profiles")
        self.assert_no_identity(self.profile(self.a), "unavailable")

    def test_invalid_ids_rejected_before_any_binding(self):
        for value in (None, 0, "", "x" * 129):
            with self.assertRaises(ValueError):
                self.store.bind_voice_profile(value, "voice-a")
            with self.assertRaises(ValueError):
                self.store.bind_voice_profile(self.a, value)
        self.assertNotIn("voice_link", self.profile(self.a))


if __name__ == "__main__":
    unittest.main()
