import unittest
from unittest.mock import AsyncMock, MagicMock

from database import apply_global_blacklist_audit_migration, record_legacy_schema_baseline


class SchemaMigrationBaselineTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_migration_registry_and_records_baseline(self):
        connection = AsyncMock()

        await record_legacy_schema_baseline(connection)

        self.assertEqual(connection.execute.await_count, 2)
        create_sql = connection.execute.await_args_list[0].args[0]
        self.assertIn("CREATE TABLE IF NOT EXISTS schema_migrations", create_sql)
        insert_call = connection.execute.await_args_list[1]
        self.assertIn("ON CONFLICT (version) DO NOTHING", insert_call.args[0])
        self.assertEqual(insert_call.args[1], "0001_legacy_schema_baseline")


class GlobalBlacklistAuditMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_audit_table_and_records_ordered_migration(self):
        connection = MagicMock()
        connection.execute = AsyncMock()
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=False)
        connection.transaction.return_value = transaction

        await apply_global_blacklist_audit_migration(connection)

        sql = connection.execute.await_args_list[0].args[0]
        self.assertIn("CREATE TABLE IF NOT EXISTS global_blacklist_audit", sql)
        self.assertIn("CHECK (action IN ('add', 'update', 'remove'))", sql)
        insert = connection.execute.await_args_list[1]
        self.assertIn("ON CONFLICT (version) DO NOTHING", insert.args[0])
        self.assertEqual(insert.args[1], "0002_global_blacklist_audit")


if __name__ == "__main__":
    unittest.main()
