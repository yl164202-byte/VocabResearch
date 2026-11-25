#!/usr/bin/env python3
"""批次轉換教材 JSON 成 VocabResearch 教師端草稿。只使用原文；不捏造翻譯。"""
import argparse, csv, json, re, shutil
from pathlib import Path
from collections import Counter
from core import load_book, lesson_key, unique_words, sentence_candidates, TEXT_PARTS


LANGS=('en','vi','id')

def load_lexicon(path):
    if not path:return {}
    with open(path,encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames or 'word' not in reader.fieldnames:
            raise ValueError('三語詞庫必須含 word 欄位，並建議 course_id,meaning_en,meaning_vi,meaning_id,pinyin')
        results={}
        for row in reader:
            word=(row.get('word') or '').strip()
            if not word:continue
            key=((row.get('course_id') or '').strip(),word) if (row.get('course_id') or '').strip() else word
            results[key]={
                'pinyin':(row.get('pinyin') or '').strip(),
                'accepted':(row.get('accepted') or '').strip(),
                'meanings':{lang:(row.get('meaning_'+lang) or '').strip() for lang in LANGS},
                # 舊欄位不自動當成英文，以免錯把越南文等其他語言放入英文欄。
            }
        return results


def get_lexicon(lex, course_id, word):
    """優先依課次＋生詞比對；舊版單詞詞庫仍可沿用。"""
    return lex.get((course_id, word), lex.get(word, {}))


def best_candidate(candidates, word):
    """只從原課文抽出候選句，取較短且有上下文的句子；沒有就保留空白。"""
    if not candidates:return ''
    def score(s):
        pure=s.replace('＿＿','').strip()
        n=len(pure)
        return (0 if 7<=n<=35 else 1, abs(n-18), n)
    return min(candidates, key=score)


def pinyin_guess(word):
    try:
        from pypinyin import lazy_pinyin, Style
        return ' '.join(lazy_pinyin(word, style=Style.TONE))
    except ImportError:
        return ''


def main():
    p=argparse.ArgumentParser(description='從 DANGDAI_ALL.json 批次生成教師端草稿')
    p.add_argument('json_file',nargs='?',default='data/DANGDAI_ALL.json')
    p.add_argument('--lexicon',help='教師詞義詞庫 CSV，欄位 word,meaning,pinyin,accepted')
    p.add_argument('--output',default='drafts')
    p.add_argument('--with-pinyin',action='store_true',help='需要額外安裝 pypinyin，屬自動拼音候選，須核對多音字')
    p.add_argument('--overwrite',action='store_true',help='覆寫現有草稿（請先備份教師修改）')
    p.add_argument('--fill-missing-pinyin',action='store_true',help='只填現有草稿的空白拼音，保留其他資料並備份原檔')
    p.add_argument('--fill-missing-meanings',action='store_true',help='只用三語詞庫 CSV 補齊既有草稿中空白的 en/vi/id 詞義，不覆蓋已填內容')
    args=p.parse_args()
    src=Path(args.json_file).resolve(); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    lessons=load_book(src); lex=load_lexicon(args.lexicon)
    volumes=list(dict.fromkeys(str(x['冊']) for x in lessons))
    rows_report=[]; summary=Counter()
    for vol in volumes:
        section=[x for x in lessons if str(x['冊'])==vol]
        for index, lesson in enumerate(section,1):
            course_id=f'B{volumes.index(vol)+1:02d}_L{index:02d}'
            dest=out/(course_id+'_v1.json')
            if dest.exists() and (args.fill_missing_pinyin or args.fill_missing_meanings):
                original=json.loads(dest.read_text(encoding='utf-8'))
                count=0
                for row in original.get('rows', []):
                    if not isinstance(row, dict):
                        continue
                    word=str(row.get('word') or '').strip()
                    if 'meanings' not in row or not isinstance(row.get('meanings'),dict):
                        row['meanings']={lang:'' for lang in LANGS}
                        count+=1
                    for lang in LANGS:
                        if not str(row['meanings'].get(lang) or '').strip():
                            value=get_lexicon(lex,course_id,word).get('meanings',{}).get(lang,'') if args.fill_missing_meanings else ''
                            if value:
                                row['meanings'][lang]=value
                                count+=1
                                summary['filled_'+lang]+=1
                    if args.fill_missing_pinyin and not str(row.get('pinyin') or '').strip():
                        word=str(row.get('word') or '').strip()
                        if word:
                            guess=get_lexicon(lex,course_id,word).get('pinyin', '') or pinyin_guess(word)
                            if guess:
                                row['pinyin']=guess
                                count+=1
                                summary['filled_pinyin']+=1
                if count:
                    backup=dest.with_suffix(dest.suffix+'.bak')
                    if not backup.exists():
                        shutil.copy2(dest, backup)
                    temp=dest.with_suffix(dest.suffix+'.tmp')
                    temp.write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding='utf-8')
                    temp.replace(dest)
                    summary['updated_drafts']+=1
                else:
                    summary['unchanged_drafts']+=1
                continue
            if dest.exists() and not args.overwrite:
                summary['skipped']+=1
                continue
            words=unique_words(lesson,TEXT_PARTS)
            for row in words:
                w=row['word']
                entry=get_lexicon(lex,course_id,w)
                row['meaning']=''
                row['meanings']=entry.get('meanings',{lang:'' for lang in LANGS}).copy()
                row['pinyin']=entry.get('pinyin','') or (pinyin_guess(w) if args.with_pinyin else '')
                row['accepted']=entry.get('accepted','')
                row['sentence']=best_candidate(sentence_candidates(lesson,w),w)
                rows_report.append({'course_id':course_id,'book':vol,'lesson':lesson['課'],'word':w,'meaning':row['meaning'],'pinyin':row['pinyin'],'sentence':row['sentence'],'review':'待教師確認' if row['meaning'] and row['sentence'] else '缺少詞義或填空句'})
                summary['words']+=1
                if not row['meaning']:summary['missing_meaning']+=1
                if not row['sentence']:summary['missing_sentence']+=1
            payload={'lesson_key':lesson_key(lesson),'rows':words,
                     'meta':{'id':course_id,'title':f'{vol} {lesson["課"]}','version':'v1','gasUrl':'','practiceOpenAt':'','delayedOpenAt':'','delayedCloseAt':''},
                     'parts':[x for x in TEXT_PARTS if lesson.get(x)]}
            dest.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
            summary['created']+=1
    report=out/'轉換待檢清單.csv'
    if rows_report:
        with report.open('w',encoding='utf-8-sig',newline='') as f:
            wr=csv.DictWriter(f,fieldnames=list(rows_report[0]));wr.writeheader();wr.writerows(rows_report)
    print(f'教材課數：{len(lessons)}；新建草稿：{summary["created"]}；保留舊草稿：{summary["skipped"]}')
    print(f'新建生詞：{summary["words"]}；缺少母語詞義：{summary["missing_meaning"]}；找不到原句：{summary["missing_sentence"]}')
    if rows_report:print('待檢清單：',report.resolve())
    if args.fill_missing_pinyin or args.fill_missing_meanings:
        print(f'更新草稿：{summary["updated_drafts"]}；補入拼音：{summary["filled_pinyin"]}；英文：{summary["filled_en"]}；越南文：{summary["filled_vi"]}；印尼文：{summary["filled_id"]}；無需修改草稿：{summary["unchanged_drafts"]}')
        print('已更新草稿的原檔備份為 *.json.bak；詞義、填空句及既有拼音保持不變。')
    print('草稿資料夾：',out.resolve())
    if summary['missing_meaning']:print('注意：原始 JSON 沒有母語詞義；請提供共用 CSV 詞庫或在 GUI 補入。未完成者不能正式發布。')

if __name__=='__main__':main()
