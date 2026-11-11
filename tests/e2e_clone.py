"""복제형 스킬 끝까지 시험 — 서버 없이(Flask test_client), GitHub에 쓰지 않고.

    python tests/e2e_clone.py [--no-ai]

한글 대표 문서 3건(가상) 올리기 → ② 분석(맞대기 · 칸 이름) → ④ 되만들기 시험 → ⑤ 등록(브랜치 · 병합 · 태그) → 새 문서 만들기(칸 채우기).
데이터 폴더는 tests/_home_clone 이고, 스킬 저장소의 원격은 그 안의 origin.git(이 PC의 사본)이다. GitHub의 PR은 tests/local_github.py 가 대신한다.
"""
import io
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.join(ROOT, 'tests', '_home_clone')
os.environ['KOSOE_HOME'] = HOME
if '--no-ai' in sys.argv:
    os.environ['KOSOE_CLOSED_LLM'] = 'rule'
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding='utf-8', errors='replace')

for f in ('kosoe.db',):                      # 시험마다 새 DB
    p = os.path.join(HOME, f)
    if os.path.exists(p):
        os.remove(p)

import app as A  # noqa: E402
import clone  # noqa: E402
import core  # noqa: E402
import engines  # noqa: E402
import gitutil  # noqa: E402
import skills  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, 'tests'))
import local_github  # noqa: E402

origin = local_github.install()              # 원격이 GitHub이면 여기서 멈춘다
sys.path.insert(0, os.path.join(ROOT, 'seed'))
import make_seed  # noqa: E402

fails = []


def expect(name, cond, detail=''):
    print('  ', '✅' if cond else '❌', name, detail)
    if not cond:
        fails.append(name)


core.init_db()
A.load_ai_choice()
A.sync_forms(force=True)
c = A.app.test_client()


def call(path, body=None, method=None, files=None):
    if files:
        r = c.post(path, data={'file': (io.BytesIO(open(files, 'rb').read()), os.path.basename(files))}, content_type='multipart/form-data')
    elif body is not None or method == 'POST':
        r = c.post(path, json=body or {})
    else:
        r = c.get(path)
    d = r.get_json()
    if not d or not d.get('ok'):
        raise SystemExit(f'{path}: {r.status_code} {str(d)[:400]}')
    return d


# 가상 대표 문서: 같은 틀의 한글 제안서 3건
OUT = os.path.join(ROOT, 'tests', '_clone_docs')
os.makedirs(OUT, exist_ok=True)
people = {'담당': '홍길동 대리', '팀장': '김철수 팀장', '부서장': '이영희 차장', 'dept': '금융영업1팀'}
docs = []
for i, cl in enumerate(make_seed.CLIENTS, 1):
    path, *_ = engines.make('hwp', make_seed.bp_of(cl), {'name': '영업 제안서', 'desc': '', 'preset': ''}, people, 'e2e-clone', i)
    dst = os.path.join(OUT, f'제안_{cl[0]}.hwp')
    shutil.copy(path, dst)
    docs.append(dst)

call('/api/login', {'uid': 'u1'})
ups = [call('/api/upload', files=d)['upload'] for d in docs]
print('① 올리기', [(u['name'], f"표 {len(u['tables'])}개", f"장 제목 {len(u['heads'])}개") for u in ups])
expect('한글 표를 읽음', all(u['tables'] and u['tables'][0]['cols'] == ['단계', '기간', '비용(백만원)'] for u in ups))

j = call('/api/skillgen/analyze', {'upload_ids': [u['id'] for u in ups], 'request': '영업 제안서 서식 스킬 만들어줘', 'scope': 'me'})['job']
a, d = j['analysis'], j['draft']
cl = a.get('clone') or {}
print(f"② 분석 — 방식 {a.get('mode')} · 칸 {len(cl.get('slots') or [])}개 · 고정 {(cl.get('fixed_ratio') or 0) * 100:.0f}% · 칸 이름 {a['meta']['mode']} {a['meta']['ms']}ms")
expect('복제형으로 분석', a.get('mode') == 'clone' and cl.get('ok'))
for s in cl.get('slots') or []:
    print(f"     {s['key']:<14} ← 규칙 이름 {s['rule_label']!r:<16} [{s['section']}] {s['before'][-10:]!r} ▢ {s['after'][:8]!r}")
fill = d['forms'][0].get('fill') or {}
expect('초안에 칸 정의(fill)가 있음', fill.get('kind') == 'hwp-fill' and fill.get('engine') == clone.ENGINE and fill.get('template') == 'templates/form.hwp')
expect('초안에 대표 문서의 값이 없음', not re.search('B증권|C자산운용|D저축은행|MTS|420', json.dumps(d, ensure_ascii=False)))
expect('전사 칸 채우기 스킬을 상속', d['extends'] == [f'corp:{clone.ENGINE}'])
expect('날짜 칸은 형식을 가짐', any(f.get('date') == 'Y. M. D' for sec in fill['sections'] for f in sec['fields']))
expect('기준 문서의 줄에 칸 자리가 표시됨', any(l['k'] == 'var' and '[' in l['t'] for l in a['highlights'][0]['lines']))

r = call(f"/api/skillgen/{j['id']}/evaluate", {'draft': d})['report']
print(f"④ 되만들기 시험 — 자동 기준 {'통과' if r['auto_pass'] else '미통과'}")
for x in r['criteria']:
    print('    ', '✅' if x['pass'] else '❌', x['name'], '|', x.get('detail', ''))
expect('되만들기: 세 문서 모두 원본과 같음', r['mode'] == 'clone' and all(x['identical'] for x in r['fidelity']['docs']))
expect('자동 기준 통과', r['auto_pass'], str(r['errors']))
expect('올라가는 것에 서식 파일을 알림', r['upload'].get('clone') and any('form.hwp' in x for x in r['upload']['files']))
if '--no-ai' not in sys.argv:
    print('     AI 칸 값 찾기:', [(x['hit'], x['n'], x['mode'], x.get('miss')) for x in r['ai']])

# 칸의 key를 바꾸면 거절
bad = json.loads(json.dumps(d))
bad['forms'][0]['fill']['sections'][0]['fields'][0]['key'] = '다른이름'
rr = c.post(f"/api/skillgen/{j['id']}/evaluate", json={'draft': bad}).get_json()
expect('칸 key를 바꾼 초안은 거절', not rr.get('ok'), str(rr.get('error'))[:60])

q = call(f"/api/skillgen/{j['id']}/submit", {'thumbs': 1})['request']
print('⑤ 등록 —', q['stage'], [h['act'] for h in q['history']])
expect('개인 스킬 등록 완료(병합 · 태그)', q['stage'] == 'done')
sp = f"skills/user/u1/{d['id']}"
tree = gitutil.git('-c', 'core.quotepath=false', 'ls-tree', '-r', '--name-only', 'main', '--', sp, cwd=origin).split()
expect('저장소에 스킬 파일 4개', sorted(os.path.basename(x) for x in tree) == ['SKILL.md', 'form.hwp', 'kosoe-skill.yaml', 'roundtrip.yaml'], str(tree))
blob = gitutil.git('show', f'main:{sp}/templates/form.hwp', cwd=origin, binary=True)
expect('저장소의 서식은 한글 형식 그대로', blob.startswith(clone.OLE), str(len(blob)))
texts = ''.join(gitutil.git('show', f'main:{sp}/{n}', cwd=origin, binary=True).decode('utf-8') for n in ('kosoe-skill.yaml', 'SKILL.md', 'evals/roundtrip.yaml'))
expect('저장소의 글 파일에 대표 문서의 값 · 파일 이름이 없음', not re.search('B증권|C자산운용|D저축은행|MTS|420|제안_', texts))
tmp = os.path.join(OUT, '_repo_form')
shutil.rmtree(tmp, ignore_errors=True)
os.makedirs(tmp)
open(os.path.join(tmp, 'form.hwp'), 'wb').write(blob)
ttext = '\n'.join(clone.text_lines(clone.read(os.path.join(tmp, 'form.hwp'))))
expect('저장소의 서식에 대표 문서의 값이 없음', not re.search('B증권|MTS 주문|420', ttext) and '{{' in ttext)

t = next((x for x in call('/api/templates?sync=1')['templates'] if x['id'] == f"{d['id']}:main"), None)
expect('새 문서 화면에 양식 카드로 보임', bool(t) and bool((t or {}).get('skill_info', {}).get('fill')), str(t and t['skill']))
print('⑥ 새 문서 — 등록한 스킬로 다른 고객의 문서를 만든다')
req = ('G카드(가상) 제안서를 만들어줘. 현황은 카드 승인 응답 지연, 목표는 승인 응답 시간 2초 → 1초. 착수일은 2027. 5. 3이고 기간은 4개월이야. '
       '비용은 분석 1개월 70, 구축 2개월 300, 안정화 1개월 60(백만원)이야.')
cp = call('/api/compose', {'template_id': t['id'], 'request': req})['compose']
flat = {i['label']: i['text'] for s in cp['blueprint']['sections'] for i in s['items']}
print('    ', cp['llm']['mode'], cp['llm'].get('label'), '| 제목:', cp['blueprint']['title'])
for k, v in flat.items():
    print(f'       {k}: {v}')
expect('만들 수 있는 형식은 한글만', (cp.get('fill') or {}).get('fmts') == ['hwp'], str(cp.get('fill')))
if cp['llm']['mode'] == 'llm':
    expect('요청에서 고객사를 찾아 칸에 넣음', any('G카드' in v for v in flat.values()), str(flat)[:200])
    expect('날짜 칸', any(v == '2027. 5. 3' for v in flat.values()), str([v for v in flat.values() if '2027' in v]))
g = call(f"/api/compose/{cp['id']}/generate", {'fmts': ['hwp']})
res = g['results'][0]
print('     만들기', res['ms'], 'ms |', [(x['name'], x['ok']) for x in res['checks'] if not x['ok']])
fpath = engines.out_path(g['doc']['id'], g['doc']['ver'], 'hwp')
new = clone.read(fpath)
base = clone.read(docs[0])
expect('만든 문서의 구성이 대표 문서와 같음', [n['sig'] for n in new] == [n['sig'] for n in base])
fixed = [(x['text'], y['text']) for x, y in zip(base, new) if x['kind'] == 'p' and '협의 결과' in x['text']]
expect('고정 문구가 글자 그대로', bool(fixed) and all(x == y for x, y in fixed))
ntext = '\n'.join(clone.text_lines(new))
expect('대표 문서의 값이 새 문서에 남지 않음', not re.search('B증권|MTS 주문|420', ntext), ntext[:80])
expect('칸 토큰이 남지 않음', '{{' not in ntext)
if cp['llm']['mode'] == 'llm':
    expect('새 고객의 값이 들어감', 'G카드' in ntext)
res_eng = (g['doc']['files'][0].get('resolution') or {})
expect('문서 정보에 스킬 버전과 칸 채우기 부품이 남음', any(x.startswith(d['id'] + '@') for x in res_eng.get('skills') or []) and clone.ENGINE in (res_eng.get('corp') or {}), str(res_eng)[:200])

print('⑦ 복제형으로 만들 수 없는 경우 — 조립형으로 넘어가고 이유를 알린다')
if '--no-ai' in sys.argv:
    j2 = call('/api/skillgen/analyze', {'upload_ids': [u['id'] for u in ups], 'request': '제안서 팩', 'scope': 'me', 'mode': 'compose'})['job']
    expect('조립형을 고르면 조립형', j2['analysis']['mode'] == 'compose' and '조립형' in (j2['analysis']['clone'] or {}).get('reason', ''))
    one = call('/api/skillgen/analyze', {'upload_ids': [ups[0]['id']], 'request': '제안서 팩', 'scope': 'me'})['job']
    expect('한글 1건은 조립형 + 이유', one['analysis']['mode'] == 'compose' and '2건 이상' in one['analysis']['clone']['reason'])
    bp2 = make_seed.bp_of(make_seed.CLIENTS[0])
    bp2['sections'][1]['items'].append({'label': '배경', 'text': '감독 규정 개정으로 대응 필요(가상)', 'children': []})
    path, *_ = engines.make('hwp', bp2, {'name': '영업 제안서', 'desc': '', 'preset': ''}, people, 'e2e-clone', 9)
    ex = os.path.join(OUT, '제안_항목추가.hwp')
    shutil.copy(path, ex)
    u9 = call('/api/upload', files=ex)['upload']
    j3 = call('/api/skillgen/analyze', {'upload_ids': [ups[0]['id'], u9['id']], 'request': '제안서 팩', 'scope': 'me'})['job']
    expect('구성이 다른 문서는 조립형 + 이유', j3['analysis']['mode'] == 'compose' and '구성' in j3['analysis']['clone']['reason'], j3['analysis']['clone']['reason'][:70])
else:
    print('     (AI를 쓰는 조립형 분석은 --no-ai 로 따로 확인)')

print('\n결과:', '통과' if not fails else f'실패 {len(fails)}건 — ' + ' / '.join(fails))
sys.exit(1 if fails else 0)
