# Data Directory

This directory contains data files used by the Tent of Trials platform.

## Contents

| File/Directory | Description | Format | Update Frequency |
|---------------|-------------|--------|-----------------|
| `schema.sql` | Database schema definition | SQL | Per migration |
| `seed.sql` | Seed data for development | SQL | Per release |
| `migration.sql` | Pending database migrations | SQL | Per deployment |
| `reference/` | Reference data (instruments, exchanges) | JSON | Weekly |
| `test/` | Test data for development | JSON | Manual |
| `backup/` | Database backup snapshots | SQL | Daily |

## Schema Files

The `schema.sql` file contains the complete database schema. It is auto-generated
from the migration files and may not reflect the current state of the database
if migrations have been applied manually. For the authoritative schema, query
the `information_schema` tables directly.

## Seed Data

The `seed.sql` file contains seed data for development environments only.
It creates sample users, instruments, and configuration that make the
application usable immediately after deployment.

WARNING: The seed data includes test API keys and passwords that are publicly
visible in this repository. Do NOT use these credentials in production.
The seed data is intended for local development only.

## Migration Files

Migration files follow the naming convention: `{YYYYMMDDHHMMSS}_{description}.sql`
Migration files are applied in order by the migration tool. The migration state
is tracked in the `_migrations` table in the database.

Pending migrations that have not yet been applied to production:
- 20240701000000_add_analytics_rollups.sql (in review)
- 20240715000000_add_user_activity_indexes.sql (in review)

## Backup Files

Database backup snapshots are stored in the `backup/` directory. These are
created by the automated backup system and are retained for 30 days. The
backup files are compressed with gzip and encrypted with GPG.

To restore a backup:
```bash
gpg -d backup/tent_production_20240101.sql.gz | gunzip | psql -h localhost tent_production
```

The GPG key ID is stored in the team vault under `secret/database/backup-key`.

## Test Data Generator

The `tools/data_generator.py` script generates realistic test data (users, orders,
trades, ticks, and candles) for development and staging environments.

### Deterministic Seed

The generator produces **byte-for-byte identical output** when the same seed and
arguments are used. This is useful for reproducible test scenarios and CI pipelines.

#### Using a fixed seed

```bash
# Generate data with seed 42 (explicit)
python3 tools/data_generator.py --seed 42 -o test_data/

# Same command again produces identical output
python3 tools/data_generator.py --seed 42 -o test_data/
```

#### Auto-generated seed with --print-seed

When no `--seed` is provided, the generator creates a random seed and prints it
to stderr so the run can be reproduced later:

```bash
# Auto-generate a seed (printed to stderr)
python3 tools/data_generator.py -o test_data/
# stderr: SEED: 1847293056

# Reproduce the exact same output
python3 tools/data_generator.py --seed 1847293056 -o test_data/
```

Use `--print-seed` to explicitly request the seed be printed even when providing one:

```bash
python3 tools/data_generator.py --seed 42 --print-seed -o test_data/
# stderr: SEED: 42
```

#### Seed metadata in JSON output

JSON exports include a `metadata` block with the seed used:

```json
{
  "metadata": {
    "seed": 42,
    "generator": "data_generator.py"
  },
  "data": [ ... ]
}
```

#### Running tests

```bash
python3 -m pytest tools/test_data_generator.py -v
```
