-- Run once after the migration and after checking preflight.sql.
-- A failed assertion rolls back the synthetic test data.
begin;
create temporary table vocab_test_results (check_name text, passed boolean) on commit preserve rows;

do $test$
declare
  code1 text := 'IT_' || replace(gen_random_uuid()::text,'-','');
  code2 text := 'IT_' || replace(gen_random_uuid()::text,'-','');
  course text := 'IT_' || gen_random_uuid()::text;
  pin1 text := gen_random_uuid()::text;
  pin2 text := gen_random_uuid()::text;
  sid text := gen_random_uuid()::text;
  submission text := gen_random_uuid()::text;
  d text := ((statement_timestamp() at time zone 'Asia/Taipei')::date)::text;
  packet jsonb;
  identity jsonb;
  base jsonb;
  start_event jsonb;
  match_event jsonb;
  cloze_event jsonb;
  match_pass jsonb;
  cloze_pass jsonb;
  done jsonb;
  result jsonb;
begin
  code1 := left(code1,32);
  code2 := left(code2,32);
  if (select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace
      where n.nspname='vocab_private' and c.relkind='r' and c.relrowsecurity) <> 5
    or has_schema_privilege('anon','vocab_private','USAGE')
    or has_schema_privilege('authenticated','vocab_private','USAGE')
    or not has_function_privilege('anon','public.vocab_request(jsonb)','EXECUTE')
    or has_function_privilege('authenticated','public.vocab_request(jsonb)','EXECUTE') then
    raise exception 'RLS or RPC ACL check failed';
  end if;
  insert into vocab_test_results values ('RLS and RPC grants',true);
  perform vocab_private.register_student(code1,pin1);
  perform vocab_private.register_student(code2,pin2);
  insert into vocab_test_results values ('Two synthetic students',true);
  for i in 1..2 loop
    perform vocab_private.register_course(jsonb_build_object('id',course,'version','v'||i,
      'words','[{"id":"W1","word":"甲","meanings":{"en":"alpha","vi":"a","id":"alfa"},"accepted":["第一"]}]'::jsonb));
  end loop;
  identity := jsonb_build_object('protocol','supabase-v1','requestId','cloud-test','studentCode',code1,'pin',pin1,
    'courseId',course,'courseVersion','v1','practiceDate',d,'sessionId',sid);
  packet := identity || '{"operation":"daily_start"}';
  result := public.vocab_request(packet);
  if result->>'created' is distinct from 'true' or result->>'sessionId' is distinct from sid then
    raise exception 'Daily start failed: %',result;
  end if;
  result := public.vocab_request(packet || jsonb_build_object('courseVersion','v2','sessionId',gen_random_uuid()));
  if result->>'created' is distinct from 'false' or result->>'courseVersion' is distinct from 'v1'
    or result->>'sessionId' is distinct from '' then raise exception 'Cross-version slot failed: %',result; end if;
  insert into vocab_test_results values ('Daily start and cross-version lock',true);

  base := identity - array['protocol','requestId','pin'] || '{"study":"vocab","mode":"practice","round":1}';
  start_event := base || jsonb_build_object('eventId',gen_random_uuid(),'stage','card','action','session_start');
  match_event := base || jsonb_build_object('eventId',gen_random_uuid(),'stage','match','action','answer','wordId','W1',
    'selectedWordId','W1','questionType','meaning_match','selected','alpha','meaningLanguage','en');
  match_pass := base || jsonb_build_object('eventId',gen_random_uuid(),'stage','match','action','stage_pass');
  cloze_event := base || jsonb_build_object('eventId',gen_random_uuid(),'stage','cloze','action','answer','wordId','W1',
    'questionType','context_cloze','selected','第一。','submissionId',submission);
  cloze_pass := base || jsonb_build_object('eventId',gen_random_uuid(),'stage','cloze','action','stage_pass','submissionId',submission);
  done := base || jsonb_build_object('eventId',gen_random_uuid(),'stage','cloze','action','session_complete','submissionId',submission);
  packet := identity || '{"operation":"events"}';
  result := public.vocab_request(packet || jsonb_build_object('events',jsonb_build_array(start_event,match_event,match_pass)));
  if result->>'ok' is distinct from 'true' or jsonb_array_length(result->'eventIds') <> 3 then
    raise exception 'Batch failed: %',result; end if;
  result := public.vocab_request(packet || jsonb_build_object('events',jsonb_build_array(start_event)));
  if result->>'ok' is distinct from 'true' or (select count(*) from vocab_private.events where session_id=sid) <> 3 then
    raise exception 'Duplicate replay failed'; end if;
  insert into vocab_test_results values ('Batch and event deduplication',true);

  result := public.vocab_request(packet || jsonb_build_object('events',jsonb_build_array(
    cloze_event || jsonb_build_object('submissionId',gen_random_uuid()),cloze_pass,done)));
  if result->>'error' is distinct from 'daily_completion_not_verified' or
    (select count(*) from vocab_private.events where session_id=sid) <> 3 or
    exists (select 1 from vocab_private.daily where session_id=sid and completed_at is not null) then
    raise exception 'Invalid completion did not roll back'; end if;
  insert into vocab_test_results values ('Invalid completion rolls back the batch',true);

  result := public.vocab_request(packet || jsonb_build_object('events',jsonb_build_array(cloze_event,cloze_pass,done)));
  if result->'completedSessions' is distinct from jsonb_build_array(sid) then raise exception 'Completion failed: %',result; end if;
  result := public.vocab_request(identity || '{"operation":"daily_start","courseVersion":"v2"}');
  if result->>'status' is distinct from 'completed' then raise exception 'Completion lock failed'; end if;
  insert into vocab_test_results values ('Verified completion locks all versions',true);

  result := public.vocab_request(identity || jsonb_build_object('operation','daily_status','studentCode',code2,'pin',pin2));
  if result->>'status' is distinct from 'not_started' or result->>'sessionId' is distinct from '' then
    raise exception 'Student status isolation failed'; end if;
  result := public.vocab_request(packet || jsonb_build_object('studentCode',code2,'pin',pin2,'events',jsonb_build_array(done)));
  if result->>'error' is distinct from 'daily_session_mismatch' then raise exception 'Student event isolation failed'; end if;
  insert into vocab_test_results values ('Students cannot access each other through RPC',true);
end
$test$;

commit;
select * from vocab_test_results order by check_name;
