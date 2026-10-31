# ADR 0001: Multi-tenant isolation via Postgres Row Level Security, not just `WHERE tenant_id`

## Status

Accepted (M1).

## Context

Every table except `tenants` carries a `tenant_id`. The obvious approach is
"every repository function takes `tenant_id` and filters by it." That works
right up until one query forgets the filter — and a forgotten filter in a
multi-tenant system means one customer's data leaking to another. That's not
hypothetical: production incidents like this are exactly what motivated this
project (see the portfolio's origin story — debugging cross-tenant leaks and
duplicate executions in a real multi-tenant agent orchestrator).

The goal here was to make that class of bug **structurally impossible**, not
just "unlikely if everyone remembers to filter."

## Decision

Enable Postgres Row Level Security on every tenant-scoped table, with
`FORCE ROW LEVEL SECURITY`, and have the application connect as a dedicated
least-privilege role (`app_runtime`) that is neither `SUPERUSER` nor
`BYPASSRLS`:

```sql
ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE tickets FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON tickets
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
```

Two Postgres roles exist:

- **admin / owner** (Railway's auto-injected `DATABASE_URL`, or the
  `postgres` superuser locally/in CI) — used *only* for Alembic migrations
  and demo-data seeding. It owns the tables and bypasses RLS, by design.
- **`app_runtime`** — created and password-synced by the migrations, used
  for every request-time query. `NOSUPERUSER NOBYPASSRLS`.

Every request opens a transaction and calls `SELECT set_config('app.tenant_id', :tid, true)`
before doing anything else (`app/db/session.py::tenant_scoped_session`). The
`is_local = true` argument gives it the same transaction-scoped lifetime as
`SET LOCAL`, so it can never leak into a later request that reuses a pooled
connection.

## Why `FORCE`, and why a separate role

Postgres exempts the **table owner** from RLS unless the table is `FORCE`d.
But even `FORCE` does not stop a **superuser** or a role with the
**`BYPASSRLS`** attribute — those always bypass RLS, regardless of `FORCE`.
Table ownership alone, without those two attributes, is *not* exempt under
`FORCE`. That's the whole reason `app_runtime` exists as a role distinct from
whatever admin connection Railway/CI hands us: if the app connected using the
same superuser role migrations use, `FORCE ROW LEVEL SECURITY` would be
decorative.

This was verified manually, not assumed — see "Bugs this surfaced" below and
`backend/tests/integration/test_tenant_isolation.py` for the automated
version, including an adversarial case: a session scoped to tenant A that
explicitly queries `WHERE tenant_id = <tenant B's id>` still gets zero rows,
because the database enforces the policy independently of what the
application's `WHERE` clause says.

## What "forgot to scope the tenant" actually does

`current_setting('app.tenant_id', true)` suppresses Postgres's "unrecognized
configuration parameter" error when the GUC was never set. What it returns
then depends on the connection's history:

- **Connection that never had `app.tenant_id` set:** `NULL`. The policy
  becomes `tenant_id = NULL`, which matches nothing — zero rows, no error.
- **Connection where an earlier transaction already used `set_config`:** the
  GUC reads back as `''` (empty string). Casting `''::uuid` fails with
  `invalid_text_representation`, so the query errors out.

Either way a code path that forgets to open a `tenant_scoped_session` can
never read or write another tenant's rows. It fails *closed*, but not
consistently *loud*: this section originally claimed the second behaviour for
every connection, which the M2 tests showed to be wrong (a fresh connection
returns an empty result instead). Fail closed is the guarantee; don't rely on
an exception to notice a missing scope.

## Bugs this surfaced while building it (kept here because they're the actual lesson)

1. **`str(sqlalchemy.engine.URL)` masks the password as `***` by default.**
   `Settings.app_database_url` originally built the app_runtime connection
   string with `str(url.set(...))` — which produced a syntactically valid
   DSN that would authenticate with the literal password `***`. Fixed by
   using `url.render_as_string(hide_password=False)`. This is a safety
   default in SQLAlchemy (so logging a URL doesn't leak credentials) that
   silently breaks anything that tries to *use* the masked string to connect.

2. **Postgres doesn't accept a bind parameter in `SET LOCAL`.** The first
   version used `SET LOCAL app.tenant_id = :tid`, which asyncpg's
   extended-query protocol tries to prepare — and Postgres rejects
   (`syntax error at or near "$1"`), because `SET` isn't a regular function
   call. Fixed by using `SELECT set_config('app.tenant_id', :tid, true)`
   instead, which *is* a normal function and accepts parameters normally.

3. **`ALTER DEFAULT PRIVILEGES` blocks `DROP ROLE` until explicitly undone.**
   The migration's `downgrade()` revoked direct table grants but not the
   default-privileges entry created by `ALTER DEFAULT PRIVILEGES ... GRANT
   ... TO app_runtime`, so `DROP ROLE app_runtime` failed with
   `DependentObjectsStillExistError`. Fixed by adding the matching `ALTER
   DEFAULT PRIVILEGES ... REVOKE ...` before the drop.

4. **Alembic's autogenerated `downgrade()` drops tables but not the enum
   types it created for them.** A `downgrade` → `upgrade` cycle failed on
   `CREATE TYPE system_status` with "already exists" because the six
   Postgres enum types outlived the tables that used them. Fixed by adding
   explicit `DROP TYPE IF EXISTS ...` statements at the end of the initial
   migration's `downgrade()`.

All four were caught by actually running the full
`upgrade → downgrade → upgrade` cycle and a real cross-tenant query — not by
reading the code and assuming it was correct.

## Consequences

- Every new tenant-scoped table must be added to `TENANT_SCOPED_TABLES` in
  `app/db/models.py` and covered by the RLS migration pattern, or it's
  unprotected. This is a manual step, not automatic — worth a code review
  checklist item.
- The app can never use the admin/owner connection for request-time queries,
  even for "just this one read." `get_admin_db()` is deliberately named and
  documented as seed/admin-only for that reason.
- Local dev, CI, and Railway all need `APP_DB_PASSWORD` set consistently
  with what the migration uses to create/sync the role — see
  `backend/.env.example`.
