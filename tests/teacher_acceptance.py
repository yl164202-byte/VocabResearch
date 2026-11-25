"""Acceptance tests through Streamlit's widget runtime using isolated course fixtures."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from teacher_gui import ROOT, button, check
from streamlit.testing.v1 import AppTest


class TeacherAcceptance(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        os.environ['VOCAB_LOCAL_DATA_DIR'] = temporary.name
        self.addCleanup(os.environ.pop, 'VOCAB_LOCAL_DATA_DIR', None)
        (self.root/'data').mkdir()
        (self.root/'drafts').mkdir()
        lessons = []
        for volume, lesson, word in [('第一冊','第一課','甲'),('第一冊','第二課','乙'),('第二冊','第一課','丙')]:
            lessons.append({'冊':volume,'課':lesson,'對話1':f'這是{word}的例子。','對話1生詞':[word]})
        (self.root/'data/DANGDAI_ALL.json').write_text(json.dumps(lessons,ensure_ascii=False),encoding='utf-8')
        for i, (lesson, word) in enumerate(zip(lessons, '甲乙丙')):
            bundle, number=((1,1),(1,2),(2,1))[i]
            key=f'B{bundle:02d}_L{number:02d}'
            from core import unique_words, lesson_key
            rows=unique_words(lesson,['對話1'])
            rows[0].update(pinyin=('jiǎ','yǐ','bǐng')[i],meanings={'en':'english-'+word,'vi':'vietnamese-'+word,'id':'indonesian-'+word},
                           sentence='這是＿＿的例子。',accepted='替代答案')
            draft={'lesson_key':lesson_key(lesson),'rows':rows,'parts':['對話1'],
                   'meta':{'id':key,'version':'v1','title':lesson['課']}}
            (self.root/'drafts'/f'{key}_v1.json').write_text(json.dumps(draft,ensure_ascii=False),encoding='utf-8')
        self.gui=self.open()
        self.grid_delta={}

    def open(self, query=None):
        at=AppTest.from_file(str(ROOT/'app.py'),default_timeout=15)
        if query:
            at.query_params.update(query)
        at.run()
        check(at)
        return at

    def send_grid_state(self):
        # AppTest does not expose a data editor setter. Send its real frontend WidgetState protocol.
        state=self.gui._tree.get_widget_states()
        entry=state.widgets.add()
        entry.id=self.gui.dataframe[0].proto.id
        entry.string_value=json.dumps({'edited_rows':{'0':self.grid_delta},'added_rows':[],'deleted_rows':[]})
        self.gui._run(state)

    def edit_grid(self, **changes):
        self.grid_delta.update(changes)
        self.send_grid_state()
        self.assertFalse(self.gui.exception)

    def save(self):
        button(self.gui,'儲存整課修改').click()
        if self.grid_delta:
            self.send_grid_state()
        else:
            self.gui.run()
        check(self.gui)

    def test_01_starts_with_real_teacher_controls(self):
        self.assertIn('教師端',self.gui.title[0].value)
        self.assertTrue(button(self.gui,'加入補充生詞'))
        self.assertTrue(button(self.gui,'查閱最近 200 筆工作階段'))

    def test_02_can_switch_book_and_lesson(self):
        self.gui.selectbox(key='selected_lesson_0').select('第二課').run()
        check(self.gui)
        self.assertEqual(self.gui.session_state['rows'][0]['word'],'乙')
        self.gui.selectbox(key='selected_book').select('第二冊').run()
        check(self.gui)
        self.assertEqual(self.gui.session_state['rows'][0]['word'],'丙')

    def test_03_grid_loads_pinyin_and_three_languages(self):
        cells=self.gui.dataframe[0].value.iloc[0]
        self.assertEqual([cells[c] for c in ('生詞','拼音','英文','越南文','印尼文')],
                         ['甲','jiǎ','english-甲','vietnamese-甲','indonesian-甲'])

    def test_04_supplements_survive_save_and_fresh_session(self):
        self.gui.text_area(key='add_extra_input').set_value('補充、補充')
        button(self.gui,'加入補充生詞').click().run()
        self.assertFalse(self.gui.exception)
        # A fresh supplemental entry can be saved before its fields pass publication validation.
        button(self.gui,'儲存整課修改').click().run()
        self.assertFalse(self.gui.exception)
        restarted=AppTest.from_file(str(ROOT/'app.py')).run()
        self.assertFalse(restarted.exception)
        rows=restarted.session_state['rows']
        self.assertEqual([row['word'] for row in rows],['甲','補充'])
        self.assertEqual(rows[-1]['category'],'supplemental')

    def test_05_edit_meanings_prompt_and_alias(self):
        self.edit_grid(**{'拼音':'jiǎ!', '英文':'edited', '越南文':'đã sửa','印尼文':'diperbarui',
                          '填空句':'請填入__。','其他答案':'替代、另外'})
        self.save()
        row=json.loads((self.root/'drafts/B01_L01_v1.json').read_text(encoding='utf-8'))['rows'][0]
        self.assertEqual(row['meanings'],{'en':'edited','vi':'đã sửa','id':'diperbarui'})
        self.assertEqual((row['pinyin'],row['sentence'],row['accepted']),('jiǎ!','請填入＿＿。','替代、另外'))

    def test_06_exclude_and_restore_word(self):
        self.edit_grid(**{'納入':False})
        self.assertFalse(self.gui.session_state['rows'][0]['included'])
        self.assertEqual(len(self.gui.get('iframe')),0)
        self.edit_grid(**{'納入':True})
        self.assertTrue(self.gui.session_state['rows'][0]['included'])
        self.assertEqual(len(self.gui.get('iframe')),1)

    def test_07_reopen_saved_version_and_restore_preview(self):
        self.edit_grid(**{'英文':'new card','填空句':'這句＿＿要存檔。','其他答案':'新選項'})
        self.gui.text_input(key='course_version').set_value('v2')
        self.send_grid_state()
        self.save()
        self.gui.selectbox(key='draft_pick_1_1').select('B01_L01_v1.json').run()
        button(self.gui,'載入這課的本機草稿').click().run()
        check(self.gui)
        self.assertEqual(self.gui.text_input(key='course_version').value,'v1')
        self.gui.selectbox(key='draft_pick_1_1').select('B01_L01_v2.json').run()
        button(self.gui,'載入這課的本機草稿').click().run()
        restarted=self.open(self.gui.query_params)
        self.assertEqual(restarted.text_input(key='course_version').value,'v2')
        html=restarted.get('iframe')[0].proto.srcdoc
        self.assertIn('new card',html[:8500])
        self.assertIn('這句＿＿要存檔。',html)
        self.assertIn('新選項',html)
        if os.getenv('VOCAB_PREVIEW_HTML'):
            Path(os.environ['VOCAB_PREVIEW_HTML']).write_text(html,encoding='utf-8')

    def test_08_settings_survive_new_gui_session(self):
        self.gui.text_input(key='sb_projectUrl').set_value('https://fixture.supabase.co')
        self.gui.text_input(key='sb_publishableKey').set_value('sb_publishable_fixture')
        self.gui.text_input(key='sb_branch').set_value('codex/acceptance')
        button(self.gui,'儲存 Supabase 與分支設定').click().run()
        check(self.gui)
        reopened=self.open()
        self.assertEqual(reopened.text_input(key='sb_projectUrl').value,'https://fixture.supabase.co')
        self.assertEqual(reopened.text_input(key='sb_branch').value,'codex/acceptance')

    def test_10_cannot_overwrite_another_lessons_draft(self):
        first=self.root/'drafts/B01_L01_v1.json'
        before=first.read_bytes()
        self.gui.selectbox(key='selected_lesson_0').select('第二課').run()
        self.gui.text_input(key='course_id').set_value('B01_L01')
        button(self.gui,'儲存整課修改').click().run()
        self.assertTrue(any('其他課次' in e.value for e in self.gui.error))
        self.assertEqual(first.read_bytes(),before)

    def test_09_publish_feedback_and_retry_from_gui(self):
        self.gui.session_state['github_auth']='fixture-token'
        self.gui.text_input(key='sb_projectUrl').set_value('https://fixture.supabase.co')
        self.gui.text_input(key='sb_publishableKey').set_value('sb_publishable_fixture')
        self.gui.checkbox(key='publish_confirm').check()
        with patch('teacher_backend.TeacherBackend.register_course',side_effect=[RuntimeError('synthetic db failure'),None,None]) as register, \
             patch('github_publish.publish',side_effect=[RuntimeError('synthetic GitHub failure'),('file.json',{'files':['file.json']})]) as push:
            button(self.gui,'登錄 Supabase 並提交 GitHub').click().run()
            self.assertIn('本次未送出 GitHub',self.gui.error[-1].value)
            push.assert_not_called()
            button(self.gui,'登錄 Supabase 並提交 GitHub').click().run()
            self.assertIn('GitHub 尚未確認',self.gui.error[-1].value)
            button(self.gui,'登錄 Supabase 並提交 GitHub').click().run()
            check(self.gui)
            self.assertEqual((register.call_count,push.call_count),(3,2))
            self.assertTrue(any('GitHub 開發分支已提交' in x.value for x in self.gui.success))

    def test_11_research_table_clears_when_target_changes(self):
        self.gui.text_input(key='sb_projectUrl').set_value('https://fixture.supabase.co')
        with patch('teacher_backend.TeacherBackend.practice_status',return_value=[{'student_code':'TEST','status':'completed'}]):
            button(self.gui,'查閱最近 200 筆工作階段').click().run()
            check(self.gui)
            self.assertEqual(self.gui.dataframe[-1].value.iloc[0]['student_code'],'TEST')
            self.gui.text_input(key='sb_projectUrl').set_value('https://another.supabase.co').run()
            self.assertNotIn('research_rows',self.gui.session_state)

    def test_12_edit_other_accepted_answers_and_restore_draft(self):
        label='其他可接受答案（選填）'

        def edit(at, value):
            next(t for t in at.text_area if t.label==label).set_value(value)
            button(at,'套用本題其他答案').click().run()
            check(at)

        edit(self.gui,'舊課詞\n任意手輸')
        self.assertEqual(self.gui.dataframe[0].value.iloc[0]['其他答案'],'舊課詞、任意手輸')
        self.save()
        reopened=self.open(self.gui.query_params)
        self.assertEqual(next(t.value for t in reopened.text_area if t.label==label),'舊課詞\n任意手輸')
        edit(reopened,'舊課詞、已修改')
        button(reopened,'儲存整課修改').click().run()
        reopened=self.open(reopened.query_params)
        self.assertEqual(reopened.dataframe[0].value.iloc[0]['其他答案'],'舊課詞、已修改')
        edit(reopened,'')
        button(reopened,'儲存整課修改').click().run()
        reopened=self.open(reopened.query_params)
        self.assertEqual(reopened.dataframe[0].value.iloc[0]['其他答案'],'')
        row=reopened.session_state['rows'][0]
        self.assertEqual(row['word'],'甲')
        self.assertEqual(row['sentence'],'這是＿＿的例子。')


if __name__=='__main__':
    unittest.main(verbosity=2)
