# Supabase migration baseline

Project: GZB / VocabResearch (`pznehaenpfadyjdqgpyh`).

On 2026-11-25 (Asia/Taipei), a read-only Dashboard query confirmed RPC
`public.vocab_request(jsonb)` reported app version `0.3.11`, protocol
`supabase-v1`, and that the five private tables had RLS enabled.
The remote `supabase_migrations.schema_migrations` table did not exist.
The local baseline is `migrations/202611250001_vocab.sql`, applied through
SQL Editor. The existing seven cloud integration tests passed.

## Reusable workflow

With the official Supabase CLI v3 authenticated, run:

```powershell
./supabase/project-check.ps1 -Action Audit
./supabase/project-check.ps1 -Action SyntheticTest
```

Use `-Cli` to provide the path to the official executable when it is not on PATH.
Audit is read-only. SyntheticTest runs only the checked-in synthetic SQL file.
Neither action applies migrations.

## Reconcile the missing history

Before recording the baseline, compare the local migration with the remote
`vocab_private` schema and `public.vocab_request(jsonb)` definition,
including constraints, function bodies and grants. Review any drift.
After verifying equivalence, register the existing baseline without
executing its SQL again:

```powershell
supabase migration repair 202611250001 --status applied --remote=pznehaenpfadyjdqgpyh --yes
supabase migration list --remote=pznehaenpfadyjdqgpyh
```

Confirm the version appears in both columns. Use a new incremental migration
for future changes. Keep credentials in CLI credential storage or the
authorized process environment.
