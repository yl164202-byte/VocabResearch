import os,json,datetime,re
from pathlib import Path
import streamlit as st
from core import load_book,lesson_key,unique_words,sentence_candidates,validate_and_build,make_public_export,TEXT_PARTS,normalize_blank,valid_blank,APP_VERSION,BACKEND_PROTOCOL
from github_publish import publish, status as github_status, set_visibility, update_student_site, SITE, BRANCH, branch_path
import credential_store
from teacher_backend import TeacherBackend, public_config, coordinated_publish

ROOT=Path(__file__).absolute().parent
LOCAL=Path(os.getenv('VOCAB_LOCAL_DATA_DIR') or (ROOT.parent if (ROOT.parent/'data').is_dir() else ROOT))
DATA=LOCAL/'data'/'DANGDAI_ALL.json'
DRAFTS=LOCAL/'drafts'; DRAFTS.mkdir(exist_ok=True)
STUDENT_ASSETS={ROOT/path:path for path in ('student/index.html','student/app.js','student/style.css','index.html')}
st.set_page_config(page_title='華語生詞教材產生器｜教師端',layout='wide',page_icon='📚')
st.markdown('''<style>
.block-container{padding-top:1.7rem;max-width:1400px}.stTextArea textarea{font-size:15px;line-height:1.6}
small,.small{color:#667085}.stAlert{border-radius:10px}
</style>''',unsafe_allow_html=True)
st.title('華語生詞記憶研究｜教師端 GUI')
st.caption(f'v{APP_VERSION} / {BACKEND_PROTOCOL}｜Supabase 教師管理與每日練習')

@st.cache_data
def cached_data():return load_book(DATA)

SETTINGS=LOCAL/'teacher_supabase_settings.json'
try:
    saved_settings=json.loads(SETTINGS.read_text(encoding='utf-8'))
except (OSError,ValueError):
    saved_settings={}
for field,default in (('projectUrl',''),('publishableKey',''),('cliPath',''),('branch',BRANCH)):
    st.session_state.setdefault('sb_'+field,saved_settings.get(field,default))

def reset_github_status():
    st.session_state.pop('github_check',None)

with st.sidebar:
    st.subheader('Supabase 與發布設定')
    st.text_input('Supabase Project URL',key='sb_projectUrl')
    st.text_input('Supabase publishable key',key='sb_publishableKey')
    st.text_input('Supabase CLI 路徑（選填）',key='sb_cliPath')
    st.text_input('GitHub 開發分支',key='sb_branch',on_change=reset_github_status)
    st.caption('管理查詢使用此電腦上已登入的 Supabase CLI 教師帳號。')
    if st.button('儲存 Supabase 與分支設定'):
        try:
            config=public_config(st.session_state.sb_projectUrl,st.session_state.sb_publishableKey)
            branch_path(st.session_state.sb_branch)
            tmp=SETTINGS.with_suffix('.tmp')
            tmp.write_text(json.dumps({**config,'cliPath':st.session_state.sb_cliPath,
                'branch':st.session_state.sb_branch},ensure_ascii=False),encoding='utf-8')
            tmp.replace(SETTINGS)
            st.success('已儲存本機設定')
        except (ValueError,OSError) as ex:
            st.error(str(ex))
    st.subheader('教材來源')
    uploaded=st.file_uploader('改用其他同結構的 JSON（選填）',type=['json'])
    st.caption('預設已內建教材；可先執行 convert_dangdai.py 批次預填原文填空句與詞庫資料。')
    st.divider()
    st.subheader('發布資訊')
    st.code('yl164202-byte/VocabResearch',language=None)
    st.caption('請在第四頁設定 GitHub Token；不需要 Git 指令。')
    st.markdown('[開啟學生端網站]('+SITE+')')
    st.warning('目前學生端及 Supabase 尚未完成正式延宕測驗安全鎖定。此版本僅供教材編輯與試行，不可直接正式收案。',icon='⚠️')
try:
    items=json.loads(uploaded.getvalue().decode('utf-8-sig')) if uploaded is not None else cached_data()
    if not isinstance(items,list) or any(not isinstance(x,dict) or '冊' not in x or '課' not in x for x in items):raise ValueError('JSON 應為含「冊」「課」的課次物件陣列')
except Exception as ex:st.error('教材匯入失敗：'+str(ex));st.stop()

books=list(dict.fromkeys(str(x['冊']) for x in items))
# 將目前選課保留於網頁網址參數：瀏覽器 Reload 後仍能回到同一冊、同一課。
# 只保存冊課選擇，不把教師編輯中的生詞、答案或個資寫進網址。
def _book_changed():
    st.query_params['book']=st.session_state['selected_book']
    # 切換冊別時清掉舊課次，避免不同冊沿用同名或同索引課次。
    if 'lesson' in st.query_params:del st.query_params['lesson']

def _lesson_changed(widget_key):
    st.query_params['book']=st.session_state['selected_book']
    st.query_params['lesson']=st.session_state[widget_key]

book_from_url=st.query_params.get('book','')
book_index=books.index(book_from_url) if book_from_url in books else 0
c1,c2=st.columns(2)
with c1:
    book=st.selectbox('選擇冊別',books,index=book_index,key='selected_book',on_change=_book_changed)
lessons=[x for x in items if str(x['冊'])==book]
lesson_names=[x['課'] for x in lessons]
lesson_from_url=st.query_params.get('lesson','')
lesson_index=lesson_names.index(lesson_from_url) if lesson_from_url in lesson_names else 0
lesson_widget_key='selected_lesson_'+str(books.index(book))
with c2:
    lesson_name=st.selectbox('選擇課次',lesson_names,index=lesson_index,key=lesson_widget_key,on_change=_lesson_changed,args=(lesson_widget_key,))
lesson=next(x for x in lessons if x['課']==lesson_name)
key=lesson_key(lesson)
key_hash=re.sub(r'[^0-9A-Za-z]','_',f'{books.index(book)+1}_{lessons.index(lesson)+1}')
def default_id():return f'B{books.index(book)+1:02d}_L{lessons.index(lesson)+1:02d}'
if st.session_state.get('active_lesson')!=key:
    st.session_state['active_lesson']=key
    st.session_state['table_revision']=st.session_state.get('table_revision',0)+1
    st.session_state['parts']=[p for p in TEXT_PARTS if lesson.get(p)]
    st.session_state['rows']=unique_words(lesson,st.session_state['parts'])
    for row in st.session_state['rows']:
        if not isinstance(row.get('meanings'),dict):row['meanings']={}
        for lang in ('en','vi','id'):row['meanings'].setdefault(lang,'')
    st.session_state['extra_words']=''
    st.session_state['edit_word']=st.session_state['rows'][0]['word'] if st.session_state['rows'] else ''
    st.session_state['course_id']=default_id()
    st.session_state['course_title']=f'{book} {lesson_name}'
    st.session_state['course_version']='v1'
    st.session_state['practice_open']=''
    st.session_state['delayed_open']=''
    st.session_state['delayed_close']=''
    # 優先使用批次轉換的教師草稿；不會把教材 JSON 當成已確認的詞義。
    auto_draft=DRAFTS/(default_id()+'_v1.json')
    if auto_draft.exists():
        try:
            saved=json.loads(auto_draft.read_text(encoding='utf-8'))
            if saved.get('lesson_key')==key:
                st.session_state['rows']=saved.get('rows',st.session_state['rows'])
                st.session_state['parts']=saved.get('parts',st.session_state['parts'])
                for field, statekey in [('id','course_id'),('title','course_title'),('version','course_version'),('practiceOpenAt','practice_open'),('delayedOpenAt','delayed_open'),('delayedCloseAt','delayed_close')]:
                    st.session_state[statekey]=saved.get('meta',{}).get(field,st.session_state[statekey])
                for row in st.session_state['rows']:
                    if not isinstance(row.get('meanings'),dict):row['meanings']={}
                    for lang in ('en','vi','id'):row['meanings'].setdefault(lang,'')
        except (ValueError,OSError,TypeError) as ex:
            st.warning('草稿讀取失敗，已改載教材生詞表：'+str(ex))

tab_text,tab_words,tab_review,tab_publish,tab_research=st.tabs(['① 課文與生詞','② 詞義／填空題編輯','③ 檢核及預覽','④ 匯出與 GitHub 發布','⑤ 學生與研究紀錄'])
with tab_text:
    available=[p for p in TEXT_PARTS if lesson.get(p)]
    st.info('生詞僅取自本課 JSON 的「對話1生詞、對話2生詞、文章1生詞、文章2生詞」；不使用課文斷詞；第二頁可取消納入練習。')
    for p in available:
        with st.expander(f'{p}｜{len(lesson.get(p+"生詞",[]) or [])} 個教材生詞',expanded=(p==available[0])):
            st.text(lesson.get(p,''))
    st.markdown('#### 教材生詞表與補充')
    st.caption('已預先轉換的草稿將於切換課次時自動載入。缺少詞義、無合適原句者仍需教師補充。')
    textbook=[x for x in st.session_state['rows'] if x['category']=='textbook']
    supplemental=[x for x in st.session_state['rows'] if x['category']=='supplemental']
    st.success(f'已自動納入本課教材生詞表 {len(textbook)} 詞；教師補充 {len(supplemental)} 詞，共 {len(st.session_state["rows"])} 詞。')
    with st.expander('檢視教材生詞（僅供核對，不必勾選）',expanded=False):
        st.write('、'.join(x['word'] for x in textbook) or '（這課沒有教材生詞）')
        for x in textbook:
            if '、' in x.get('sources',''):
                st.caption(f'「{x["word"]}」同時出現在：{x["sources"]}；已自動合併。')
    if supplemental:
        st.markdown('**已加入的補充生詞**')
        st.write('、'.join(x['word'] for x in supplemental))
    new_extra=st.text_area('直接加入補充生詞（用空白、頓號、逗號或換行分隔）',placeholder='例如：日本 英國 法國 中國 越南',height=80,key='add_extra_input')
    if st.button('加入補充生詞',type='primary'):
        new_words=[t.strip() for t in re.split(r'[\s、,，;；]+',new_extra) if t.strip()]
        existing={x['word'] for x in st.session_state['rows']}
        added=0
        for w in new_words:
            if w not in existing:
                st.session_state['rows'].append({'word':w,'pinyin':'','meaning':'','meanings':{'en':'','vi':'','id':''},'sentence':'','accepted':'','category':'supplemental','sources':'教師補充'})
                existing.add(w);added+=1
        if added: st.session_state['table_revision']=st.session_state.get('table_revision',0)+1
        st.success(f'已加入 {added} 個補充生詞；重複輸入 {len(new_words)-added} 個已略過。')

def row_issues(row):
    issues=[]
    if not str(row.get('pinyin') or '').strip(): issues.append('拼音空白')
    for lang,label in [('en','英文'),('vi','越文'),('id','印尼文')]:
        if not str((row.get('meanings') or {}).get(lang) or '').strip(): issues.append(label+'空白')
    sent=normalize_blank(row.get('sentence'))
    if not valid_blank(sent): issues.append('填空格式')
    if row.get('word') and row['word'] in sent: issues.append('答案仍在句中')
    return '、'.join(issues) or '欄位齊全'

def table_record(row):
    return {'納入':row.get('included',True),'生詞':row['word'],'拼音':str(row.get('pinyin') or ''),
            '英文':str((row.get('meanings') or {}).get('en') or ''),
            '越南文':str((row.get('meanings') or {}).get('vi') or ''),
            '印尼文':str((row.get('meanings') or {}).get('id') or ''),
            '填空句':str(row.get('sentence') or ''),'其他答案':str(row.get('accepted') or ''),
            '來源':'補充' if row.get('category')=='supplemental' else row.get('sources','教材'),
            '檢查':row_issues(row)}

def save_current_draft():
    meta={'id':st.session_state.get('course_id',default_id()),'version':st.session_state.get('course_version','v1'),'title':st.session_state.get('course_title',''),'practiceOpenAt':None,'delayedOpenAt':None,'delayedCloseAt':None}
    name=re.sub(r'[^A-Za-z0-9_.-]','_',meta['id']+'_'+meta['version'])+'.json'
    target=DRAFTS/name
    payload={'lesson_key':key,'rows':st.session_state['rows'],'meta':meta,'parts':st.session_state['parts']}
    temp=target.with_suffix('.json.tmp')
    temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    if target.exists():
        import shutil
        shutil.copy2(target,target.with_suffix('.json.review.bak'))
    temp.replace(target)
    return name

with tab_words:
    selected_rows=st.session_state['rows']
    st.markdown('#### 整課生詞與填空題審閱')
    st.caption('已匯入的資料自動套用。重新載入頁面時，勾選狀態以本課已儲存草稿為準，不會強制全選。直接雙擊儲存格修改，完成後請按「儲存整課修改」。')
    st.info('填空句：請用兩個全形底線 ＿＿（標準格式）；連續兩個以上半形底線 __、___ 或混合底線也會自動統一。每題只允許一處空格。例：＿＿，你是陳月美小姐嗎？（答案：請問）。單一底線、兩處空格、破折號不會通過檢核。')
    if not selected_rows: st.warning('本課尚無生詞，請先於第一頁加入補充生詞。')
    else:
        if st.button('批次補齊空白填空句（保留已有句子）',key='fill_all_'+key_hash):
            from convert_dangdai import best_candidate
            count=0
            for row in selected_rows:
                if not str(row.get('sentence') or '').strip():
                    candidate=best_candidate(sentence_candidates(lesson,row['word'],st.session_state['parts']),row['word'])
                    if candidate: row['sentence']=candidate;count+=1
            st.session_state['table_revision']=st.session_state.get('table_revision',0)+1
            st.success(f'已補入 {count} 個候選句；既有句子不變。')
        a,b=st.columns(2)
        with a: all_on=st.button('全選',key='all_on_'+key_hash)
        with b: all_off=st.button('全不選',key='all_off_'+key_hash)
        if all_on or all_off:
            for r in selected_rows:r['included']=all_on
            st.session_state['table_revision']+=1
        missing=sum(r.get('included',True) and row_issues(r)!='欄位齊全' for r in selected_rows)
        st.write(f'共 {len(selected_rows)} 詞｜納入 {sum(r.get("included",True) for r in selected_rows)} 詞｜{missing} 詞有空白或格式問題')
        only=st.checkbox('只顯示空白或格式待修正項目',key='filter_'+key_hash)
        # Keep the input snapshot stable for each editor instance. Replacing it on every rerun
        # can cause Streamlit to lose cell edits. Changing filter or rows starts a new snapshot.
        signature=(key,st.session_state.get('table_revision',0),only)
        if st.session_state.get('table_signature')!=signature:
            st.session_state['table_signature']=signature
            st.session_state['table_generation']=st.session_state.get('table_generation',0)+1
            st.session_state['table_snapshot']=[table_record(r) for r in selected_rows if not only or (r.get('included',True) and row_issues(r)!='欄位齊全')]
        records=st.session_state['table_snapshot']
        if records:
            edited=st.data_editor(records,key='whole_editor_'+str(st.session_state['table_generation']),hide_index=True,num_rows='fixed',use_container_width=True,height=min(900,75+36*len(records)),disabled=['生詞','來源','檢查'],column_config={
                '納入':st.column_config.CheckboxColumn('納入練習',default=True),
                '生詞':st.column_config.TextColumn('生詞',width='small'),
                '拼音':st.column_config.TextColumn('拼音',width='small'),
                '英文':st.column_config.TextColumn('英文',width='medium'),
                '越南文':st.column_config.TextColumn('越南文',width='medium'),
                '印尼文':st.column_config.TextColumn('印尼文',width='medium'),
                '填空句':st.column_config.TextColumn('填空句（＿＿）',width='large'),
                '其他答案':st.column_config.TextColumn('認可的其他答案（同課生詞可填，使用頓號分隔）',width='small'),
                '來源':st.column_config.TextColumn('來源',width='small'),
                '檢查':st.column_config.TextColumn('初始檢查',width='medium')})
            by_word={r['word']:r for r in selected_rows}
            for entry in edited:
                row=by_word[entry['生詞']]
                row['included']=bool(entry.get('納入',True))
                row['pinyin']=entry.get('拼音') or ''
                row.setdefault('meanings',{})
                for lang,col in [('en','英文'),('vi','越南文'),('id','印尼文')]:row['meanings'][lang]=entry.get(col) or ''
                row['sentence']=normalize_blank(entry.get('填空句'))
                row['accepted']=entry.get('其他答案') or ''
        else: st.success('目前沒有空白或格式問題。')
        if st.button('儲存整課修改',type='primary',key='save_whole_'+key_hash):
            try: st.success('已儲存：'+save_current_draft())
            except OSError as ex: st.error('儲存失敗：'+str(ex))
        st.caption('修改後請按儲存，再切換課次。初始檢查欄會在重新整理表格時更新。')
        if st.button('重新整理檢查狀態',key='refresh_'+key_hash):
            st.session_state['table_revision']=st.session_state.get('table_revision',0)+1
            st.rerun()
        with st.expander('原課文候選句（查閱用）'):
            w=st.selectbox('查閱生詞',[r['word'] for r in selected_rows],key='candidate_lookup_'+key_hash)
            candidates=sentence_candidates(lesson,w,st.session_state['parts'])
            if candidates: st.write('\n'.join('• '+c for c in candidates))
            else:st.caption('沒有可直接擷取的候選句，可於上方表格自行編寫。')

with tab_review:
    st.markdown('#### 課程與研究設定')
    m1,m2=st.columns(2)
    with m1:
        meta_id=st.text_input('課程 ID',key='course_id');title=st.text_input('課程名稱',key='course_title')
        ver=st.text_input('版本（已發布版本不可覆蓋）',key='course_version')
    with m2:
        st.caption('Supabase 與 GitHub 發布分支由左側設定。練習與測驗日期不在教材中設定。')
        st.caption('正式延宕測驗尚未啟用；現階段只提供練習與不計次的預覽。')

# Build in all reruns; editing is held in current session state rows.
meta={'id':st.session_state.get('course_id',default_id()),'version':st.session_state.get('course_version','v1'),'title':st.session_state.get('course_title',''),'practiceOpenAt':None,'delayedOpenAt':None,'delayedCloseAt':None}
problems,public,private=validate_and_build(book,lesson,st.session_state['rows'],meta)
with tab_review:
    if problems:
        st.error(f'尚有 {len(problems)} 項需確認：')
        st.write('\n'.join('• '+x+'\n' for x in problems[:60]))
    else:st.success(f'課程檢核通過：共 {len(public["words"])} 個生詞，可以匯出教材。')
    st.markdown('#### 學生端實作預覽（不送出研究事件）')
    _,preview_course,_=validate_and_build(book,lesson,st.session_state['rows'],meta,preview=True)
    if preview_course['words'] and preview_course['availableLanguages']:
        if problems: st.warning('以下為待修正教材預覽，尚未通過發布檢核。')
        import streamlit.components.v1 as components
        from preview import preview_html
        components.html(preview_html(preview_course,ROOT/'student'),height=1000,scrolling=True)
        st.caption('語音辨識能否使用取決於瀏覽器與 iframe 麥克風權限；必要時於正式學生頁測試。')
    else: st.info('至少納入一個生詞，且完成任一語言全課詞義後，即可操作預覽。')
with tab_publish:
    st.markdown('#### 下載與發布')
    if problems:
        st.warning('請先到「② 詞義／填空題編輯」完成必填欄位，再返回此頁。')
    else:
        st.info('學生端公開 ZIP 與 Supabase 私人登錄資料分開下載。公開教材包含教學用生詞。私人可接受答案由 Supabase 判分。')
        open_zip,lesson_file,ix=make_public_export(public,private,{'files':[]},STUDENT_ASSETS)
        st.download_button('下載學生端公開發布 ZIP（不含 Supabase 私人登錄檔）',data=open_zip,file_name=f'{public["id"]}_{public["version"]}_public.zip',mime='application/zip',use_container_width=True)
        st.caption('第一次測試建議使用未發布的課程 ID／版本，例如 TEST_B01_L01 / v1，以及匿名測試學生。手動發布既有網站時須合併索引，不可覆蓋。')
        st.download_button('只下載該課 JSON',json.dumps(public,ensure_ascii=False,indent=2),file_name=lesson_file,mime='application/json')
        st.download_button('下載 Supabase 私人登錄資料 JSON',json.dumps(private,ensure_ascii=False,indent=2),file_name=f'{public["id"]}_{public["version"]}_SUPABASE_PRIVATE.json',mime='application/json')
        if st.button('只登錄私人課程至 Supabase'):
            try:
                TeacherBackend(st.session_state.sb_projectUrl,st.session_state.sb_cliPath).register_course(private)
                st.success('Supabase 已確認課程與答案鍵登錄。')
            except (ValueError,RuntimeError) as ex:st.error(str(ex))
        st.divider()
    st.divider()
    st.markdown('#### GitHub 一鍵發布')
    st.caption('GitHub 儲存庫為 yl164202-byte/VocabResearch，提交目標使用左側開發分支。請勿將 Token 貼到聊天、CSV 或教材。')
    st.markdown('[建立 Fine-grained Token](https://github.com/settings/personal-access-tokens/new) ｜ [開啟 GitHub Pages 設定](https://github.com/yl164202-byte/VocabResearch/settings/pages) ｜ [開啟學生端網站]('+SITE+')')
    if 'github_auth' not in st.session_state:
        try: st.session_state['github_auth']=os.getenv('GITHUB_TOKEN','').strip() or credential_store.load()
        except Exception:
            st.session_state['github_auth']=''
            st.warning('無法讀取本機加密憑證，請重新設定。')
    with st.expander('GitHub Token 設定（首次使用或更換憑證）',expanded=not bool(st.session_state['github_auth'])):
        st.caption('在 GitHub 選擇正確的 Resource owner，只授權 VocabResearch，Contents 設為 Read and write。Metadata 會自動提供讀取權限。')
        def apply_token():
            new=st.session_state.get('github_token_entry','').strip()
            if not new:
                st.session_state['github_notice']=('error','請先輸入 Token。');return
            st.session_state['github_auth']=new
            st.session_state.pop('github_check',None)
            st.session_state['github_token_entry']=''
            try:
                if st.session_state.get('remember_github'):
                    credential_store.save(new)
                    msg='已使用 Windows DPAPI 加密儲存 Token，僅本機 Windows 使用者可解密。'
                else:
                    credential_store.clear()
                    msg='已設定本次使用的 Token，不寫入磁碟。'
                st.session_state['github_notice']=('success',msg)
            except Exception:
                st.session_state['github_notice']=('warning','Token 已供本次使用，但無法更新本機加密儲存；下次可能須重新輸入。')
        def forget_token():
            st.session_state['github_auth']='';st.session_state['github_token_entry']='';st.session_state.pop('github_check',None)
            try:
                credential_store.clear();st.session_state['github_notice']=('success','已清除本機及本次憑證。若仍設有 GITHUB_TOKEN 環境變數，重新啟動時仍可能載入。')
            except OSError:st.session_state['github_notice']=('warning','本次憑證已清除，但無法刪除磁碟上的加密憑證。')
        st.text_input('GitHub Token',type='password',key='github_token_entry',placeholder='貼上 GitHub 產生的 Token')
        st.checkbox('在此 Windows 帳號加密保存 Token（下次免輸入）',value=True,key='remember_github',disabled=os.name!='nt')
        g1,g2=st.columns(2)
        if st.button('使用此電腦現有的 GitHub 登入'):
            candidate=credential_store.load_github_login()
            if candidate:
                st.session_state['github_auth']=candidate
                st.session_state.pop('github_check',None)
                st.success('已讀取本機 GitHub 登入，請測試儲存庫權限。')
            else:
                st.error('本機沒有可供此儲存庫使用的 GitHub 登入。')
        g1.button('套用 Token',on_click=apply_token)
        g2.button('清除本機 Token',on_click=forget_token)
        if st.session_state.get('github_notice'):
            level,msg=st.session_state['github_notice'];getattr(st,level)(msg)
    token=st.session_state['github_auth']
    st.write('憑證狀態：'+('已設定（不顯示內容）' if token else '未設定'))
    if st.button('測試連線與讀取課程清單',disabled=not bool(token)):
        try:
            with st.spinner('檢查 GitHub 連線…'):st.session_state['github_check']=github_status(token,st.session_state.sb_branch)
        except Exception as ex:
            st.session_state.pop('github_check',None);st.error(str(ex))
    info=st.session_state.get('github_check')
    if info:
        st.success('GitHub 已連線：'+info['login']+'｜'+('開發分支已存在' if info['initialized'] else '開發分支尚未建立')+'｜已發布 '+str(len(info['files']))+' 課')
        st.caption('連線測試可確認帳號與讀取權；Token 的實際 Contents 寫入權及分支限制以發布結果為準。')
        if info['files']:
            with st.expander('已發布課程版本'):st.write(info['files'])
        if not info.get('has_pages'):st.info('GitHub Pages 尚未啟用；首次發布成功後，請到 Pages 設定選 main / (root)。')
    # Visibility applies only to the public course picker; private Supabase rows remain unchanged.
    if info and info.get('files'):
        st.markdown('#### 已發布課程版本管理')
        st.caption('只控制學生網站的課程選單顯示／隱藏。隱藏不會刪除教材、研究紀錄，也不等於停用 Supabase 後端；持有舊連結或舊頁面的學生仍可能存取教材。')
        hidden=set(info.get('hidden',[]))
        with st.expander('展開管理所有已發布版本',expanded=False):
            for file_name in info['files']:
                show=file_name not in hidden
                col1,col2=st.columns([4,1])
                with col1:
                    st.write(('🟢 顯示' if show else '⚪ 隱藏')+'｜'+file_name.replace('__',' / ').removesuffix('.json'))
                with col2:
                    label='隱藏' if show else '顯示'
                    if st.button(label,key='visibility_'+file_name):
                        try:
                            with st.spinner('正在更新 GitHub 課程索引…'):
                                changed=set_visibility(token,file_name,visible=not show,branch=st.session_state.sb_branch)
                            info['hidden']=changed['hidden']
                            st.session_state['github_check']=info
                            st.session_state['visibility_notice']=('success',file_name+(' 已重新顯示。' if not show else ' 已從新版學生選單隱藏。'))
                            st.rerun()
                        except Exception as ex:
                            st.error('切換失敗：'+str(ex)+'；請重新按「測試連線與讀取課程清單」後再試。')
        if st.session_state.get('visibility_notice'):
            level,message=st.session_state.pop('visibility_notice')
            getattr(st,level)(message)
        st.caption('首次啟用版本隱藏功能，請先按下面的按鈕更新學生端共用程式；此操作只提交至開發分支。')
        if st.button('只更新學生端共用網頁程式（不發布課程）',key='only_update_site'):
            try:
                with st.spinner('正在更新學生端網站程式…'):
                    result=update_student_site(token,STUDENT_ASSETS,public_config(st.session_state.sb_projectUrl,st.session_state.sb_publishableKey),st.session_state.sb_branch)
                if result['changed']:st.success('已更新學生端：'+', '.join(result['files']))
                else:st.info('學生端程式已是最新，無須更新。')
            except Exception as ex:
                st.error('網站程式更新失敗：'+str(ex))
    if not problems:
        st.write('本次發布：**'+public['id']+' / '+public['version']+'**｜'+str(len(public['words']))+' 個生詞')
        if info and lesson_file in info['files']:st.info('相同內容可安全重試。修改教材內容請提高版本號。')
        confirmed=st.checkbox('我確認教材可公開（含公開練習生詞及例句）；不含私人資料，並了解正式延宕測驗尚未開放',key='publish_confirm')
        if st.button('登錄 Supabase 並提交 GitHub',disabled=not(token and confirmed),type='primary',use_container_width=True):
            def mark_registered():
                st.session_state['registered_course']=(public['id'],public['version'])
            st.session_state.pop('registered_course',None)
            try:
                branch=st.session_state.sb_branch
                branch_path(branch)
                config=public_config(st.session_state.sb_projectUrl,st.session_state.sb_publishableKey)
                backend=TeacherBackend(config['projectUrl'],st.session_state.sb_cliPath)
                with st.spinner('正在登錄課程並提交教材…'):
                    target,index=coordinated_publish(backend,private,
                        lambda:publish(token,public,STUDENT_ASSETS,config,branch),registered=mark_registered)
                st.session_state['github_receipt']={'file':target,'count':len(index['files']),'branch':branch}
                if info:
                    info.update(files=index['files'],hidden=index.get('hidden',[]),initialized=True)
                st.success('Supabase 已確認登錄，GitHub 開發分支已提交。')
            except Exception as ex:
                if st.session_state.get('registered_course'):
                    st.error('Supabase 已確認登錄。GitHub 尚未確認，可使用相同內容重試。'+str(ex))
                else:
                    st.error('Supabase 尚未確認登錄，本次未送出 GitHub。'+str(ex))
    else:st.caption('教材尚未通過檢核，暫不能發布；仍可測試 GitHub 連線。')
    receipt=st.session_state.get('github_receipt')
    if receipt:
        st.caption('本次工作階段最近一次成功提交：'+receipt['file'])
        st.markdown('[查看 GitHub 開發分支](https://github.com/yl164202-byte/VocabResearch/tree/'+receipt['branch']+')')
        st.info('若是首次發布，需到 GitHub Pages 設定 main / (root)。GitHub 提交成功不代表 Pages 已完成部署。')
    st.divider()
    st.markdown('#### 草稿保存')
    draft_name=re.sub(r'[^A-Za-z0-9_.-]','_',meta['id']+'_'+meta['version'])
    draft_file=DRAFTS/(draft_name+'.json')
    if st.button('儲存教師端草稿（本機）'):
        payload={'lesson_key':key,'rows':st.session_state['rows'],'meta':meta,'parts':st.session_state['parts']}
        save_current_draft()
        st.success('已儲存：'+draft_file.name)
    def restore_draft():
        draft=json.loads(draft_file.read_text(encoding='utf-8'))
        if draft.get('lesson_key')!=key:return
        st.session_state['rows']=draft['rows'];st.session_state['parts']=draft.get('parts',[])
        st.session_state['table_revision']=st.session_state.get('table_revision',0)+1
        for mk,sk in [('id','course_id'),('title','course_title'),('version','course_version'),('practiceOpenAt','practice_open'),('delayedOpenAt','delayed_open'),('delayedCloseAt','delayed_close')]:
            st.session_state[sk]=draft.get('meta',{}).get(mk,'')
        # 讀取舊草稿時，不沿用已廢除的個別生詞勾選狀態。
        for row in st.session_state['rows']:
            row.pop('selected',None)
            if not isinstance(row.get('meanings'),dict):row['meanings']={}
            for lang in ('en','vi','id'):row['meanings'].setdefault(lang,'')
        for k in list(st.session_state.keys()):
            if k.startswith(('pin_'+key_hash+'_','mean_'+key_hash+'_','mean_en_'+key_hash+'_','mean_vi_'+key_hash+'_','mean_id_'+key_hash+'_','sent_'+key_hash+'_','accepted_'+key_hash+'_','choose_'+key_hash+'_')):
                del st.session_state[k]
    if draft_file.exists():
        st.button('載入這課的本機草稿',on_click=restore_draft)

with tab_research:
    st.markdown('#### 學生代碼與 PIN')
    with st.form('register_student',clear_on_submit=True):
        new_code=st.text_input('匿名學生代碼')
        new_pin=st.text_input('學生 PIN',type='password')
        if st.form_submit_button('建立學生'):
            try:
                TeacherBackend(st.session_state.sb_projectUrl,st.session_state.sb_cliPath).register_student(new_code.strip(),new_pin)
                st.success('已建立學生 '+new_code.strip())
            except (ValueError,RuntimeError) as ex:st.error(str(ex))
    st.markdown('#### 每日練習與研究紀錄')
    filter_course=st.text_input('依課程 ID 篩選（留空列出全部）')
    if st.button('查閱最近 200 筆工作階段'):
        try:
            rows=TeacherBackend(st.session_state.sb_projectUrl,st.session_state.sb_cliPath).practice_status(filter_course)
            st.session_state['research_rows']=rows
            st.caption('共 '+str(len(rows))+' 筆工作階段')
        except (ValueError,RuntimeError) as ex:
            st.session_state.pop('research_rows',None)
            st.error(str(ex))
    if 'research_rows' in st.session_state:
        st.dataframe(st.session_state['research_rows'],hide_index=True)
