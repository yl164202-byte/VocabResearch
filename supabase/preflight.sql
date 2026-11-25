-- Run in the target project's SQL Editor. All statements are read-only.
select current_database() as database_name, current_user as sql_role,
       to_regnamespace('vocab_private') as vocab_schema,
       to_regprocedure('public.vocab_request(jsonb)') as vocab_rpc;

select e.extname, n.nspname as extension_schema
from pg_catalog.pg_extension e
join pg_catalog.pg_namespace n on n.oid = e.extnamespace
where e.extname = 'pgcrypto';

select c.relname as relation, c.relrowsecurity as rls,
       pg_catalog.has_table_privilege('anon', c.oid, 'SELECT,INSERT,UPDATE,DELETE') as anon_table_access,
       pg_catalog.has_table_privilege('authenticated', c.oid, 'SELECT,INSERT,UPDATE,DELETE') as authenticated_table_access
from pg_catalog.pg_class c
join pg_catalog.pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'vocab_private' and c.relkind in ('r','v')
order by c.relname;

select tablename, policyname, roles, cmd
from pg_catalog.pg_policies
where schemaname = 'vocab_private'
order by tablename, policyname;

select r.role_name, pg_catalog.has_schema_privilege(r.role_name, n.oid, 'USAGE') as private_schema_access
from (values ('anon'), ('authenticated')) r(role_name)
cross join pg_catalog.pg_namespace n
where n.nspname = 'vocab_private';

select r.role_name, pg_catalog.has_function_privilege(r.role_name, p.oid, 'EXECUTE') as rpc_execute,
       p.prosecdef as security_definer, p.proconfig as function_settings
from (values ('anon'), ('authenticated')) r(role_name)
cross join pg_catalog.pg_proc p
join pg_catalog.pg_namespace n on n.oid = p.pronamespace
where p.oid = to_regprocedure('public.vocab_request(jsonb)') and n.nspname = 'public';
