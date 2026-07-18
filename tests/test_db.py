import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db


class DbTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "test.db"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_init_db_is_idempotent(self):
        conn1 = db.init_db(self.path)
        conn1.close()
        conn2 = db.init_db(self.path)
        conn2.close()

    def test_seed_if_empty_only_seeds_once(self):
        conn = db.init_db(self.path)
        db.seed_if_empty(conn)
        count_after_first = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        db.seed_if_empty(conn)
        count_after_second = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        self.assertEqual(count_after_first, count_after_second)
        self.assertEqual(count_after_first, len(db.SEED_USERS))
        conn.close()

    def test_seed_creates_rh_role(self):
        conn = db.init_db(self.path)
        db.seed_if_empty(conn)
        row = conn.execute("SELECT * FROM users WHERE role='RH'").fetchone()
        self.assertIsNotNone(row)
        conn.close()

    def test_password_hash_roundtrip(self):
        password_hash, salt = db.hash_password("correct-horse")
        self.assertTrue(db.verify_password("correct-horse", salt, password_hash))
        self.assertFalse(db.verify_password("wrong-password", salt, password_hash))

    def test_password_hash_uses_random_salt(self):
        hash1, salt1 = db.hash_password("same-password")
        hash2, salt2 = db.hash_password("same-password")
        self.assertNotEqual(salt1, salt2)
        self.assertNotEqual(hash1, hash2)


if __name__ == "__main__":
    unittest.main()
