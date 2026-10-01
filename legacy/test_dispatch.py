import unittest

import oracledb
from app import (
    get_oracle_connection,
    execute_dispatch,
    admin_mark_maintenance,
)


class TestSuccessfulRun(unittest.TestCase):
    """Test Case 1: a valid transaction should update records
    correctly across Oracle (Dispatches, Ambulances, EmergencyCalls,
    AuditLog) - and, by extension, the same MongoDB/Neo4j reads the
    GUI performs before this step succeed too, since they use the
    same underlying data."""

    def setUp(self):
        self.conn = get_oracle_connection()
        self.cursor = self.conn.cursor()

        # Create a fresh call to dispatch, rather than reusing one
        # that might already be DISPATCHED/CANCELLED from earlier
        # manual testing.
        self.cursor.execute("SELECT MAX(call_id) + 1 FROM EmergencyCalls")
        self.new_call_id = self.cursor.fetchone()[0]
        self.cursor.execute(
            """
            INSERT INTO EmergencyCalls (call_id, patient_id, dispatcher_id, triage_id, location)
            VALUES (:id, 1, 1, 1, 'Abdoun, Amman')
            """,
            id=self.new_call_id,
        )
        self.conn.commit()

        # Find a genuinely available ambulance rather than hardcoding one.
        self.cursor.execute("SELECT ambulance_id FROM Ambulances WHERE status = 'AVAILABLE'")
        row = self.cursor.fetchone()
        self.assertIsNotNone(row, "Test setup requires at least one AVAILABLE ambulance to exist.")
        self.ambulance_id = row[0]

        self.cursor.execute("SELECT paramedic_id FROM Paramedics")
        self.paramedic_id = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT hospital_id FROM TraumaCenters")
        self.hospital_id = self.cursor.fetchone()[0]

    def tearDown(self):
        self.conn.close()

    def test_dispatch_updates_all_four_tables_correctly(self):
        new_dispatch_id = execute_dispatch(
            self.new_call_id, self.ambulance_id, self.paramedic_id, self.hospital_id
        )
        self.assertIsInstance(new_dispatch_id, int)

        # Dispatches: the new row exists and links to the right call.
        self.cursor.execute("SELECT call_id FROM Dispatches WHERE dispatch_id = :id", id=new_dispatch_id)
        self.assertEqual(self.cursor.fetchone()[0], self.new_call_id)

        # Ambulances: status flipped to ENROUTE.
        self.cursor.execute("SELECT status FROM Ambulances WHERE ambulance_id = :id", id=self.ambulance_id)
        self.assertEqual(self.cursor.fetchone()[0], "ENROUTE")

        # EmergencyCalls: status flipped to DISPATCHED.
        self.cursor.execute("SELECT status FROM EmergencyCalls WHERE call_id = :id", id=self.new_call_id)
        self.assertEqual(self.cursor.fetchone()[0], "DISPATCHED")

        # AuditLog: the package's internal log_action wrote an entry.
        self.cursor.execute(
            "SELECT action FROM AuditLog WHERE dispatch_id = :id", id=new_dispatch_id
        )
        self.assertEqual(self.cursor.fetchone()[0], "DISPATCH_CREATED")


class TestInvalidInput(unittest.TestCase):
    """Test Case 2: bad/out-of-range data should be rejected with a
    clear error, not silently accepted or left ambiguous."""

    def test_nonexistent_ambulance_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            execute_dispatch(call_id=1, ambulance_id=999999, paramedic_id=1, hospital_id=1)
        self.assertIn("does not exist", str(ctx.exception))

    def test_nonexistent_call_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            execute_dispatch(call_id=999999, ambulance_id=1, paramedic_id=1, hospital_id=1)
        self.assertIn("does not exist", str(ctx.exception))


class TestErrorAndRollback(unittest.TestCase):
    """Test Case 3: simulate a failure mid-transaction
    (trg_block_maintenance_dispatch rejecting a maintenance
    ambulance) and confirm nothing partial was written - true
    atomicity, not just an error message."""

    def setUp(self):
        self.conn = get_oracle_connection()
        self.cursor = self.conn.cursor()
        self.cursor.execute("SELECT ambulance_id FROM Ambulances")
        self.ambulance_id = self.cursor.fetchone()[0]
        admin_mark_maintenance(self.ambulance_id)

    def tearDown(self):
        # Reset the ambulance so this test doesn't permanently affect
        # later manual testing.
        self.cursor.execute(
            "UPDATE Ambulances SET status = 'AVAILABLE' WHERE ambulance_id = :id", id=self.ambulance_id
        )
        self.conn.commit()
        self.conn.close()

    def test_dispatch_to_maintenance_ambulance_is_blocked_and_atomic(self):
        self.cursor.execute("SELECT COUNT(*) FROM Dispatches")
        dispatch_count_before = self.cursor.fetchone()[0]

        with self.assertRaises(oracledb.DatabaseError) as ctx:
            execute_dispatch(call_id=1, ambulance_id=self.ambulance_id, paramedic_id=1, hospital_id=1)
        self.assertIn("ORA-20001", str(ctx.exception))

        # The real proof of rollback: no half-written row was left behind.
        self.cursor.execute("SELECT COUNT(*) FROM Dispatches")
        dispatch_count_after = self.cursor.fetchone()[0]
        self.assertEqual(dispatch_count_before, dispatch_count_after,
                          "A dispatch row was created despite the trigger rejecting the transaction.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
