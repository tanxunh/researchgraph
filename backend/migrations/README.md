# Database migrations

From the configured repository root, before starting application writers:

```sh
docker compose build
docker compose run --rm backend python -m scripts.migrate_all
docker compose up -d
```

The runner applies the existing evidence-version, async-job, and job-created-at
migrations in order. It creates a fresh schema or upgrades a compatible schema;
repeat execution is supported. Failure stops the command. MySQL is the runtime
database; SQLite is used only by isolated tests. The SQL file in this directory is
a schema reference, not an instruction to bulk-run historical migrations.

Back up MySQL and raw sources together and stop writers before upgrades. Preserve
credentials and project/volume identity for an existing installation. Migrations
use advisory locks and inspect existing DDL, but do not replace a consistent backup.
No destructive downgrade is provided. See [deployment](../../docs/deployment.md).
