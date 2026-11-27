import unittest
from unittest.mock import AsyncMock

from database import record_legacy_schema_baseline


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


if __name__ == "__main__":
    unittest.main()
