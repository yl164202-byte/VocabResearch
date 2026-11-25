import base64
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import bcrypt

URL = re.compile(r'https://([a-z0-9-]+)\.supabase\.co/?')
PUBLISHABLE = re.compile(r'sb_publishable_[A-Za-z0-9_-]+')
ID = re.compile(r'[A-Za-z0-9_.-]{1,90}')


def public_config(url, key):
    match = URL.fullmatch(url.strip())
    if not match or not PUBLISHABLE.fullmatch(key.strip()):
        raise ValueError('請輸入 Supabase Project URL 和 publishable key')
    return {'projectUrl': f'https://{match[1]}.supabase.co', 'publishableKey': key.strip()}


def value(data):
    encoded = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
    return f"convert_from(decode('{encoded}','base64'),'UTF8')::jsonb"


class TeacherBackend:
    def __init__(self, url, cli=None):
        match = URL.fullmatch(url.strip())
        if not match:
            raise ValueError('Supabase Project URL 格式錯誤')
        self.ref = match[1]
        self.cli = cli or os.getenv('SUPABASE_CLI') or 'supabase'

    def query(self, sql, *, read_only=True):
        with tempfile.TemporaryDirectory(prefix='vocab-teacher-') as directory:
            file = Path(directory) / 'teacher.sql'
            file.write_text(sql, encoding='utf-8')
            command = [self.cli, 'db', 'query', f'--remote={self.ref}', '--file', str(file),
                       '--output', 'json', '--read-only' if read_only else '--yes']
            try:
                result = subprocess.run(command, capture_output=True, encoding='utf-8', timeout=45)
            except (OSError, subprocess.TimeoutExpired):
                raise RuntimeError('無法執行 Supabase CLI 或連線逾時，請檢查 CLI 路徑及網路') from None
        if result.returncode:
            raw = result.stdout + result.stderr
            if re.search('LoginRequired|Access token not provided|Unauthorized', raw, re.I):
                raise RuntimeError('Supabase CLI 尚未登入或權限不足，請以教師帳號登入')
            if 'course_version_conflict' in raw:
                raise RuntimeError('Supabase 已有不同內容的同名版本，請提高版本號')
            if 'students_pkey' in raw or '23505' in raw:
                raise RuntimeError('學生代碼已存在，原有 PIN 仍有效')
            raise RuntimeError('Supabase 管理查詢未完成。請確認專案權限與資料庫遷移後重試')
        try:
            payload = json.loads(result.stdout)
            return payload['rows'] if isinstance(payload, dict) else payload
        except (ValueError, KeyError, TypeError):
            raise RuntimeError('Supabase CLI 未回傳可核對的結果，請使用 CLI v3') from None

    def register_course(self, document):
        for field in ('id', 'version'):
            if not ID.fullmatch(str(document.get(field) or '')):
                raise ValueError('課程 ID 或版本格式錯誤')
        words = document.get('words') or []
        ids = [str(w.get('id') or '') for w in words]
        if not ids or any(not ID.fullmatch(x) for x in ids) or len(ids) != len(set(ids)):
            raise ValueError('生詞 ID 格式錯誤或重複')
        encoded = value(document)
        # Pin the transaction to one course version. Existing versions are immutable.
        rows=self.query(f"""do $teacher$
        declare doc jsonb := {encoded}; prior jsonb;
        begin
          perform pg_advisory_xact_lock(hashtextextended(jsonb_build_array(doc->>'id',doc->>'version')::text,0));
          select document into prior from vocab_private.courses where id=doc->>'id' and version=doc->>'version';
          if found and prior is distinct from doc then raise exception 'course_version_conflict'; end if;
          if not found then perform vocab_private.register_course(doc); end if;
        end $teacher$;
        select document = {encoded} as registered from vocab_private.courses
          where id=({encoded})->>'id' and version=({encoded})->>'version' and active;""", read_only=False)
        if not rows or rows[0].get('registered') is not True:
            raise RuntimeError('課程未獲 Supabase 確認或已停用')

    def register_student(self, code, pin):
        if not re.fullmatch(r'[A-Za-z0-9_-]{3,32}', code) or not 8 <= len(pin) or len(pin.encode()) > 72:
            raise ValueError('學生代碼須為 3–32 位英數／底線／連字號，PIN 至少 8 字元且最多 72 位元組')
        hashed = bcrypt.hashpw(pin.encode(), bcrypt.gensalt(rounds=10, prefix=b'2a')).decode()
        doc = value({'code': code, 'hash': hashed})
        rows=self.query(f"""insert into vocab_private.students(code,pin_hash)
          select x->>'code',x->>'hash' from (select {doc} x) v;
          select true as registered;""", read_only=False)
        if not rows or rows[0].get('registered') is not True:
            raise RuntimeError('Supabase 未確認學生建立結果')

    def course_versions(self, course=''):
        doc = value(course.strip())
        return self.query(f"""select id,version,active,document->>'title' as title,
          jsonb_array_length(document->'words') as word_count
          from vocab_private.courses where ({doc} #>> '{{}}') in ('',id)
          order by id,version limit 200;""")

    def practice_status(self, course=''):
        doc = value(course.strip())
        return self.query(f"""select student_code,course_id,course_version,practice_date,started_at,completed_at,
          case when completed_at is null then 'in_progress' else 'completed' end as status,
          (select count(*) from vocab_private.events e where e.session_id=d.session_id) as event_count,
          (select count(*) from vocab_private.events e where e.session_id=d.session_id and e.correct_server is false) as incorrect_answers
          from vocab_private.daily d where ({doc} #>> '{{}}') in ('',course_id)
          order by practice_date desc, started_at desc limit 200;""")


def coordinated_publish(backend, private, publish_public, *, registered=lambda: None):
    backend.register_course(private)
    registered()
    return publish_public()
