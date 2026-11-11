"""복제형 스킬 모듈(clone.py) 시험 — 서버 없이, AI 없이. 가상 문서를 만들어 맞대기 → 서식 → 되만들기 → 비교를 확인한다.

    python tests/unit_clone.py            (데이터 폴더: tests/_home_clone — 스킬 저장소의 원격이 이 PC의 사본이라 GitHub에 쓰지 않는다)
"""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('KOSOE_HOME', os.path.join(ROOT, 'tests', '_home_clone'))
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(ROOT, 'tests'))
import make_local_home  # noqa: E402

make_local_home.ensure(os.environ['KOSOE_HOME'])     # 시험용 데이터 폴더가 없으면 만든다(실제 ~/.kosoe 에서 복사 — GitHub와 분리)

import clone  # noqa: E402
import corp  # noqa: E402
import engines  # noqa: E402
import extract  # noqa: E402
import fillform  # noqa: E402
import skills  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, 'seed'))
import make_seed  # noqa: E402

fails = []


def expect(name, cond, detail=''):
    print('  ', '✅' if cond else '❌', name, detail)
    if not cond:
        fails.append(name)


skills.ensure(force=True)
OUT = os.path.join(ROOT, 'tests', '_clone_docs')
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT)
people = {'담당': '홍길동 대리', '팀장': '김철수 팀장', '부서장': '이영희 차장', 'dept': '금융영업1팀'}
tpl = {'name': '영업 제안서', 'desc': '금융영업 고객 제안', 'preset': ''}


def hwp(name, bp, ver):
    path, *_ = engines.make('hwp', bp, tpl, people, 'unit-clone', ver)
    dst = os.path.join(OUT, name)
    shutil.copy(path, dst)
    return dst


# 1) 같은 틀의 제안서 3건(값의 길이가 서로 다름)
docs = [hwp(f'제안_{c[0]}.hwp', make_seed.bp_of(c), i) for i, c in enumerate(make_seed.CLIENTS, 1)]
print('① 맞대기 — 제안서 3건')
heads = extract.read(docs[0], '제안.hwp')['heads']
an = clone.analyze(docs, heads=heads)
expect('구성이 같아 맞대기 성공', an['ok'], an.get('reason', ''))
print(f"   구조 {an['lines']}줄 · 글 {an['text_lines']}줄 · 칸 {len(an['slots'])}개 · 고정 {an['fixed_ratio'] * 100:.0f}%")
keys = clone.make_keys(an['slots'])
for s in an['slots']:
    print(f"   {keys[s['id']]:<16} [{s['section']}] {s['left'][-10:]!r} ▢ {s['right'][:8]!r}  값 {s['values']}")
expect('제목의 고객사명이 칸으로 잡힘', any(s['values'][:3] == ['B증권', 'C자산운용', 'D저축은행'] for s in an['slots']))
expect('날짜는 통째로 한 칸(2027. 2. 1)', any(s['values'][0] == '2027. 2. 1' for s in an['slots']), str([s['values'][0] for s in an['slots'] if '2027' in s['values'][0]]))
expect('숫자를 중간에서 자르지 않음', all(not (s['right'][:1].isdigit() and s['values'][0][-1:].isdigit()) for s in an['slots']))
expect('고정 문구는 칸이 아님', not any('협의 결과' in v for s in an['slots'] for v in s['values']))
expect('장 제목으로 묶임', {s['section'] for s in an['slots']} >= {'고객 과제', '일정·비용'}, str({s['section'] for s in an['slots']}))
expect('날짜 칸의 형식을 앎', clone.date_format(next(s['values'] for s in an['slots'] if s['values'][0] == '2027. 2. 1')) == 'Y. M. D')

print('② 서식 만들기')
t = os.path.join(OUT, 'form.hwp')
b = clone.build(docs[0], an, keys, t)
expect('서식 생성', b['ok'], '; '.join(b['problems']))
expect('칸 토큰이 모두 들어감', sorted(b['tokens']) == sorted(set(keys.values())), str(b['tokens']))
expect('서식 파일은 한글 형식', open(t, 'rb').read(8) == clone.OLE)
left = clone.leftovers(t, an)
expect('서식에 대표 문서의 값이 남지 않음', not left, str(left))
expect('바꿈표 파일을 남기지 않음', not os.path.exists(os.path.join(OUT, 'form.map.tsv')))

print('③ 되만들기 — 서식 + 각 문서의 칸 값 → 원본과 비교')
for k, d in enumerate(docs):
    out = os.path.join(OUT, f'remake_{k}.hwp')
    ok, warns = clone.remake(t, clone.values_of(an, k, keys), out)
    c = clone.compare(d, out)
    expect(f'{os.path.basename(d)}: 글자 {c["text"][0]}/{c["text"][1]} · 구성 {c["struct"][0]}/{c["struct"][1]} · 모양 {c["shape"][0]}/{c["shape"][1]}',
           ok and c['identical'] and not warns, json.dumps(c['diffs'], ensure_ascii=False)[:300] + str(warns))
    print('      파일 바이트 동일:', c['bytes_same'])

print('④ 서식 채우기 양식으로 — 칸 정의가 앱의 fillform과 맞물리는지')
form = {'name': '영업 제안서', 'kind': 'hwp-fill', 'sections': []}
for s in an['slots']:
    sec = next((x for x in form['sections'] if x['heading'] == (s['section'] or '문서 정보')), None)
    if not sec:
        sec = {'heading': s['section'] or '문서 정보', 'fields': []}
        form['sections'].append(sec)
    sec['fields'].append({'key': keys[s['id']], 'label': keys[s['id']], 'required': True})
bp = fillform.to_blueprint(form, clone.values_of(an, 1, keys), {})
v = fillform.to_values(bp, form)
expect('설계도 ↔ 칸 값 왕복', v['fields'] == clone.values_of(an, 1, keys), str(v['fields'])[:200])

print('⑤ 구성이 다른 문서 — 복제형으로 만들지 않고 이유를 알린다')
c = list(make_seed.CLIENTS[0])
bp2 = make_seed.bp_of(c)
bp2['sections'][1]['items'].append({'label': '배경', 'text': '감독 규정 개정으로 대응 필요(가상)', 'children': []})
extra = hwp('제안_항목추가.hwp', bp2, 9)
an2 = clone.analyze([docs[0], extra])
expect('맞대기 실패로 표시', not an2['ok'] and '구성' in an2['reason'], an2['reason'])
an3 = clone.analyze([docs[0]])
expect('문서 1건은 맞대기 불가', not an3['ok'], an3['reason'])
an4 = clone.analyze([docs[0], docs[0]])
expect('같은 문서 2건은 칸 없음', not an4['ok'], an4['reason'])

print('⑥ 읽기 — 한글 표를 행·열로')
g = clone.tables_of(clone.read(docs[0]))
expect('표 2개(표지 · 일정표)', len(g) == 2, str([len(x) for x in g]))
expect('일정표 머리글과 값', g[1][0] == ['단계', '기간', '비용(백만원)'] and g[1][1][0] == '분석', str(g[1][:2]))

print('⑦ 사람이 만든 서식 — 전사 계약서 스킬의 서식으로 쓴 가상 계약서 3건(같은 값이 여러 곳에 나오고, 한 줄에 글자 모양이 여러 번 바뀐다)')
make_seed.contracts(OUT)
cdir = os.path.join(OUT, '계약서_3건')
cdocs = [os.path.join(cdir, f) for f in sorted(os.listdir(cdir))] if os.path.isdir(cdir) else []
if len(cdocs) == 3:
    can = clone.analyze(cdocs)
    ckeys = clone.make_keys(can['slots'])
    expect('계약서 3건 맞대기', can['ok'] and can['fields'] < len(can['slots']), f"칸 {can.get('fields')}개({len(can['slots'])}곳) · 고정 {can.get('fixed_ratio', 0) * 100:.0f}%")
    expect('고객사명이 세 곳에 나와도 한 칸', len({ckeys[x['id']] for x in can['slots'] if x['values'][0] == 'E증권'}) == 1 and sum(1 for x in can['slots'] if x['values'][0] == 'E증권') == 3)
    expect("장 제목은 '제 n 조【…】'에서", {x['section'] for x in can['slots']} >= {'목적', '서비스 이용료', '계약기간'}, str({x['section'] for x in can['slots']}))
    expect('표의 둘째 줄 머리글로 이름', any(x['label'] == '2행 중분류' for x in can['slots']), str([x['label'] for x in can['slots']]))
    ct = os.path.join(OUT, 'contract_form.hwp')
    cb = clone.build(cdocs[0], can, ckeys, ct)
    expect('계약서 서식 생성', cb['ok'], '; '.join(cb['problems']))
    expect('서식에 값이 남지 않음', not clone.leftovers(ct, can))
    for k, d in enumerate(cdocs):
        o = os.path.join(OUT, f'contract_remake_{k}.hwp')
        made, warns = clone.remake(ct, clone.values_of(can, k, ckeys), o)
        c = clone.compare(d, o)
        expect(f'{os.path.basename(d)}: 글자 {c["text"][0]}/{c["text"][1]} · 구성 {c["struct"][0]}/{c["struct"][1]} · 모양 {c["shape"][0]}/{c["shape"][1]} · 바이트 동일 {c["bytes_same"]}',
               made and c['identical'] and not warns, json.dumps(c['diffs'], ensure_ascii=False)[:300])
else:
    expect('계약서 시드 자료 3건', False, '칸 채우기 전사 스킬이 없어 만들지 못함')

print('\n결과:', '통과' if not fails else f'실패 {len(fails)}건 — ' + ' / '.join(fails))
sys.exit(1 if fails else 0)
