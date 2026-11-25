"""Synthetic teacher GUI fixtures and opt-in live publish test."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))


def load_teacher(folder):
    from streamlit.testing.v1 import AppTest

    folder = Path(folder)
    (folder/'data').mkdir()
    (folder/'drafts').mkdir()
    lesson = {'冊': '合成測試冊', '課': '合成測試課', '對話1':'這是第一個例子。',
              '對話1生詞':['甲']}
    if os.getenv('VOCAB_E2E_MULTIPLE'):
        lesson['對話1生詞'].append('乙')
    (folder/'data'/'DANGDAI_ALL.json').write_text(json.dumps([lesson], ensure_ascii=False), encoding='utf-8')
    from core import unique_words, lesson_key
    rows = unique_words(lesson, ['對話1'])
    rows[0].update(pinyin='jiǎ', meanings={'en':'alpha', 'vi':'a', 'id':'alfa'},
                   sentence='這是＿＿個例子。', accepted='第一、首')
    if len(rows)>1:
        rows[1].update(pinyin='yǐ',meanings={'en':'beta','vi':'b','id':'beta'},
                       sentence='請選擇第＿＿項。',accepted='第二')
    draft = {'lesson_key':lesson_key(lesson),'rows':rows,'parts':['對話1'],
             'meta':{'id':os.environ.get('VOCAB_E2E_COURSE','IT_LOCAL'),'version':'v1','title':'合成測試教材'}}
    (folder/'drafts'/'B01_L01_v1.json').write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
    os.environ['VOCAB_LOCAL_DATA_DIR'] = str(folder)
    return AppTest.from_file(str(ROOT/'app.py'), default_timeout=60).run()


def button(at, label):
    return next(b for b in at.button if b.label == label)


def check(at):
    assert not at.exception, [str(item.value) for item in at.exception]
    assert not at.error, [str(item.value) for item in at.error]


def verify_retry_boundary():
    from teacher_backend import coordinated_publish
    from unittest.mock import Mock

    backend = Mock()
    public = Mock(side_effect=RuntimeError('GitHub response lost'))
    acknowledged = Mock()
    backend.register_course.side_effect = RuntimeError('Supabase declined')
    try:
        coordinated_publish(backend, {}, public, registered=acknowledged)
    except RuntimeError:
        pass
    else:
        raise AssertionError('Backend failure was suppressed')
    public.assert_not_called()
    acknowledged.assert_not_called()
    backend.register_course.side_effect = None
    try:
        coordinated_publish(backend, {}, public, registered=acknowledged)
    except RuntimeError:
        pass
    else:
        raise AssertionError('Publishing failure was suppressed')
    acknowledged.assert_called_once()
    public.assert_called_once()
    print('Publish failure checkpoint and retry boundary passed')


def run_local():
    verify_retry_boundary()
    with tempfile.TemporaryDirectory() as folder:
        at = load_teacher(folder)
        check(at)
        assert any('練習' in c.value for c in at.caption)
        assert any(s.value.startswith('課程檢核通過') for s in at.success)
        assert button(at,'只登錄私人課程至 Supabase')
        assert button(at,'建立學生')
        from preview import preview_html
        output = preview_html({'id':'IT_LOCAL'},ROOT/'student')
        assert 'window.VOCAB_PREVIEW=' in output and '<script src="app.js' not in output
        print('Teacher GUI editor, validation, preview and management controls passed')


def run_cloud():
    with tempfile.TemporaryDirectory() as folder:
        at = load_teacher(folder)
        check(at)
        for key, field in (('sb_projectUrl','VOCAB_E2E_URL'),('sb_publishableKey','VOCAB_E2E_KEY'),
                           ('sb_branch','VOCAB_E2E_BRANCH')):
            at.text_input(key=key).set_value(os.environ[field])
        button(at,'儲存 Supabase 與分支設定').click().run()
        check(at)
        config=json.loads((Path(folder)/'teacher_supabase_settings.json').read_text(encoding='utf-8'))
        assert set(config)=={'projectUrl','publishableKey','cliPath','branch'}
        for suffix in ('', '2'):
            next(t for t in at.text_input if t.label=='匿名學生代碼').set_value(os.environ['VOCAB_E2E_CODE'+suffix])
            next(t for t in at.text_input if t.label=='學生 PIN').set_value(os.environ['VOCAB_E2E_PIN'+suffix])
            button(at,'建立學生').click().run()
            check(at)
            assert any(x.value.startswith('已建立學生') for x in at.success)
        label='其他可接受答案（選填）'
        next(t for t in at.text_area if t.label==label).set_value('第一、先修詞')
        button(at,'套用本題其他答案').click().run()
        check(at)
        if os.getenv('VOCAB_E2E_MULTIPLE'):
            at.selectbox(key='alias_word_1_1').select('乙').run()
            next(t for t in at.text_area if t.label==label).set_value('')
            button(at,'套用本題其他答案').click().run()
            check(at)
        button(at,'儲存整課修改').click().run()
        check(at)
        at.checkbox(key='publish_confirm').check()
        for version in ('v1','v2','v2'):
            at.text_input(key='course_version').set_value(version)
            button(at,'登錄 Supabase 並提交 GitHub').click().run()
            check(at)
            assert any('GitHub 開發分支已提交' in x.value for x in at.success)
        next(t for t in at.text_input if t.label.startswith('已登錄版本')).set_value(os.environ['VOCAB_E2E_COURSE'])
        button(at,'查詢 Supabase 課程版本').click().run()
        check(at)
        assert set(at.dataframe[-1].value['version'])=={'v1','v2'}
        from teacher_backend import TeacherBackend, value
        course=value(os.environ['VOCAB_E2E_COURSE'])
        documents=TeacherBackend(os.environ['VOCAB_E2E_URL']).query(
            f"select version, document->'words' as words from vocab_private.courses where id=({course} #>> '{{}}')")
        assert len(documents)==2
        for row in documents:
            assert row['words'][0]['accepted']==['第一','先修詞']
            if os.getenv('VOCAB_E2E_MULTIPLE'):
                assert row['words'][1]['accepted']==[]
        button(at,'測試連線與讀取課程清單').click().run()
        check(at)
        lesson_file=os.environ['VOCAB_E2E_COURSE']+'__v1.json'
        at.button(key='visibility_'+lesson_file).click().run()
        check(at)
        assert lesson_file in at.session_state['github_check']['hidden']
        at.button(key='visibility_'+lesson_file).click().run()
        check(at)
        assert lesson_file not in at.session_state['github_check']['hidden']
        print('Live Streamlit settings, two students, two immutable publications, private aliases and cleared alternatives, safe retry and visibility passed')


def run_status():
    with tempfile.TemporaryDirectory() as folder:
        at=load_teacher(folder)
        at.text_input(key='sb_projectUrl').set_value(os.environ['VOCAB_E2E_URL'])
        next(t for t in at.text_input if t.label.startswith('依課程 ID')).set_value(os.environ['VOCAB_E2E_COURSE'])
        button(at,'查閱最近 200 筆工作階段').click().run()
        check(at)
        rows={r['student_code']:r for r in at.session_state['research_rows']}
        first=rows[os.environ['VOCAB_E2E_CODE']]
        second=rows[os.environ['VOCAB_E2E_CODE2']]
        assert first['status']=='completed' and int(first['incorrect_answers'])==(2 if os.getenv('VOCAB_E2E_MULTIPLE') else 1)
        assert int(first['event_count'])>1
        assert second['status']=='in_progress' and int(second['event_count'])==1
        from teacher_backend import TeacherBackend, value
        from core import stable_word_id
        course=value(os.environ['VOCAB_E2E_COURSE'])
        events=TeacherBackend(os.environ['VOCAB_E2E_URL']).query(
            f"select * from vocab_private.research_events where course_id=({course} #>> '{{}}') order by server_time")
        codes=(os.environ['VOCAB_E2E_CODE'],os.environ['VOCAB_E2E_CODE2'])
        one,two=([event for event in events if event['student_code']==code] for code in codes)
        assert len(one)==int(first['event_count']) and len(two)==int(second['event_count'])==1
        assert len({e['event_id'] for e in events})==len(events)
        assert len({e['session_id'] for e in events})==2
        assert {e['version'] for e in events}=={'v1'}
        assert sum(e['action']=='session_start' for e in one)==1
        assert sum(e['action']=='session_complete' for e in one)==1
        card=[e for e in one if e['action']=='card_flip']
        assert len(card)==1 and card[0]['word_id']==stable_word_id('甲')
        answers=[e for e in one if e['action']=='answer']
        assert {e['word_id'] for e in answers}=={stable_word_id(w) for w in ('甲乙' if os.getenv('VOCAB_E2E_MULTIPLE') else '甲')}
        for stage,wrong_input in [('cloze','錯誤')]+([('match','beta')] if os.getenv('VOCAB_E2E_MULTIPLE') else []):
            attempts=[e for e in answers if e['stage']==stage and e['word_id']==stable_word_id('甲')]
            failed,succeeded=sorted(attempts,key=lambda row:int(row['attempt']))
            assert (failed['correct_server'],succeeded['correct_server'])==(False,True)
            assert failed['selected']==wrong_input
            assert (failed['extra_json']['firstAttempt'],succeeded['extra_json']['firstAttempt'])==(True,False)
            assert [int(e['attempt']) for e in (failed,succeeded)]==[1,2]
            assert [e['extra_json']['wordErrorCount'] for e in (failed,succeeded)]==[1,1]
            if stage=='cloze':
                assert succeeded['selected']=='  先修詞。  '
                assert succeeded['extra_json']['isTargetWord'] is False
                assert succeeded['extra_json']['actualWordId'] is None
                assert failed['extra_json']['submissionId']!=succeeded['extra_json']['submissionId']
        if os.getenv('VOCAB_E2E_MULTIPLE'):
            targets=[e for e in answers if e['stage']=='cloze' and e['word_id']==stable_word_id('乙')]
            assert len(targets)==2
            assert all(e['correct_server'] and e['selected']=='  乙。  '
                       and e['extra_json']['isTargetWord'] is True
                       and e['extra_json']['actualWordId']==stable_word_id('乙') for e in targets)
        assert sum(e['correct_server'] is False for e in one)==int(first['incorrect_answers'])
        print('Live teacher GUI reports completed and incomplete students, with exact cloud event IDs, attempts, errors and isolated sessions')


if __name__ == '__main__':
    (run_cloud if '--cloud' in sys.argv else run_status if '--status' in sys.argv else run_local)()
