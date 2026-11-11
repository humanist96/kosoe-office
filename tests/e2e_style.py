"""문서 기준 문체 · 검증 미통과 강제 등록 시험.
python tests/e2e_style.py            # 단위 시험(앱 없이): 문체 재기 · 문체별 검수 · 자동 수정
python tests/e2e_style.py --app      # + 실행 중인 앱으로: 계약서 예시 → 분석 → 검증(문체 기준이 문서 기준으로 바뀌는지)
python tests/e2e_style.py --app --force   # + 사람 확인을 건너뛴 채 강제 등록(사유 없음 거절 → 사유 있으면 등록, 실제 PR이 만들어진다)
"""
import json
import os
import sys
import time
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'seed'))
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding='utf-8', errors='replace')

import checks  # noqa: E402
import engines  # noqa: E402
import llm  # noqa: E402

fails = []


def expect(name, cond, detail=''):
    print('  ', '✅' if cond else '❌', name, detail)
    if not cond:
        fails.append(name)


def unit():
    from make_seed import CONTRACT
    print('① 문체 재기')
    st = checks.measure_style([CONTRACT])
    print('   계약서:', checks.style_label(st), '|', st['basis'])
    expect('계약서 → 서술형(~한다)', st['ending'] == 'plain', st['ending'])
    expect('계약서 → 날짜 2019.03.15 형식', st['date'] == 'Y.MM.DD', st['date'])
    expect('계약서 → 90자 제한 풀림', st['max_len'] == 0 or st['max_len'] > 90, str(st['max_len']))
    report = '\n'.join(['□ 추진 배경', 'ㅇ 원장 시스템 노후화로 장애가 반복되어 전환이 필요함', 'ㅇ 2026. 11. 20 고객 세미나에서 전환 사례를 발표할 예정임',
                        'ㅇ 예산 120만원 범위에서 다과와 기념품을 준비함', 'ㅇ 참석 인원 45명 기준으로 좌석을 배치함'])
    sr = checks.measure_style([report])
    print('   보고서:', checks.style_label(sr), '|', sr['basis'])
    expect('보고서 → 전사 보고 문법 그대로', checks.is_default_style(sr))
    polite = '\n'.join(['귀사의 무궁한 발전을 기원합니다.', '아래와 같이 서비스 점검 일정을 안내드립니다.', '점검은 2026년 11월 20일 새벽에 진행합니다.', '문의 사항은 담당 부서로 연락해 주시기 바랍니다.'])
    sp = checks.measure_style([polite])
    expect('공문 → 존댓말(~합니다) · 2026년 10월 28일', sp['ending'] == 'polite' and sp['date'] == 'Y년 M월 D일', checks.style_label(sp))

    print('② 문체별 검수')
    bp = {'title': '계약서', 'sections': [{'heading': '제 1 조【목적】', 'table': None, 'items': [
        {'label': '', 'text': '"갑"과 "을"은 2019.03.15 체결한 기본계약의 부속 계약으로서 추가 업무 이용에 필요한 사항을 정하기 위하여 이 계약을 체결한다. ' * 2, 'children': []}]}]}
    d = {c['id']: c for c in engines.check(bp)}
    expect('보고 문법으로 보면 날짜·길이·종결 모두 미통과', not d['date']['ok'] and not d['long']['ok'] and not d['end']['ok'])
    d = {c['id']: c for c in engines.check(bp, (), st)}
    expect('계약서 문체로 보면 통과', all(c['ok'] for k, c in d.items() if k in ('date', 'long', 'end')), ', '.join(c['name'] for c in d.values()))
    bad = {'title': 't', 'sections': [{'heading': 'h', 'table': None, 'items': [{'label': '', 'text': '계약기간은 2026. 7. 6부터 1년으로 함', 'children': []}]}]}
    d = {c['id']: c for c in engines.check(bad, (), st)}
    expect('계약서 문체에서 개조식(~함)·다른 날짜 형식은 미통과', not d['end']['ok'] and not d['date']['ok'], d['date']['detail'])
    fixed, _ = engines.autofix(bad, lambda xs: (xs, None), (), st)
    t = fixed['sections'][0]['items'][0]['text']
    expect('자동 수정 → 서술형 · 문서의 날짜 형식', t == '계약기간은 2026.07.06부터 1년으로 한다.', t)
    d = {c['id']: c for c in engines.check(bp, (), None, [bp['sections'][0]['items'][0]['text']])}
    expect('고정 문구(글자 그대로 넣는 글)는 문체 검사에서 제외', all(d[k]['ok'] for k in ('date', 'long', 'end')))
    old = '2026-10-28, 2026.10.28, 2026년 10월 28일, 2026. 10. 28'
    b2 = {'title': 't', 'sections': [{'heading': 'h', 'table': None, 'items': [{'label': '', 'text': old, 'children': []}]}]}
    d = {c['id']: c for c in engines.check(b2)}
    expect('기본 문법의 날짜 검사는 그대로(3건 지적)', d['date']['detail'].count('2026') == 3, d['date']['detail'])

    print('③ 고정 문구 안의 칸([칸 이름])')
    fx = '[고객사명](이하 "갑"이라 한다)와 코쇠금융IT(이하 "을"이라 한다)는 "갑"과 "을"이 [기본계약 체결일] 체결한 기본계약의 부속 계약으로서 이 계약을 체결한다.'
    filled = fx.replace('[고객사명]', 'F자산운용 주식회사').replace('[기본계약 체결일]', '2021.05.10')
    broken = 'F자산운용(이하 "갑")과 코쇠금융IT(이하 "을")는 2021.05.10 체결한 기본계약의 부속 계약으로 이 계약을 체결함'
    one = lambda t: {'title': 't', 'sections': [{'heading': '제1조', 'table': None, 'items': [{'label': '', 'text': t, 'children': []}]}]}
    expect('칸을 채운 문장은 고정 문구를 지킨 것', checks.fixed_present(fx, filled) and not checks.fixed_present(fx, broken))
    expect('가림 토큰 [고객사명1]은 칸이 아님', checks.slots_of([fx, '[고객사명1] 귀중']) == ['[고객사명]', '[기본계약 체결일]'])
    expect('채운 문장은 그대로 둠', checks.enforce_fixed(one(filled), [{'heading': '제1조', 'text': fx}])['sections'][0]['items'][0]['text'] == filled)
    b3 = checks.enforce_fixed(one(broken), [{'heading': '제1조', 'text': fx}])
    expect('틀을 바꾼 문장은 고정 문구로 되돌림', b3['sections'][0]['items'][0]['text'] == fx)
    d = {c['id']: c for c in engines.check(b3, (), None, [fx])}
    expect('안 채운 칸은 「확인 필요」로 잡힘', not d['todo']['ok'], d['todo']['detail'])

    print('④ 작성 규칙')
    expect('문체 없으면 코스콤 보고 문법', llm.writing_rules(None) == llm.WRITING_RULES)
    r = llm.writing_rules(st)
    expect('계약서 문체 규칙에 서술형 · 2026.10.28', '서술형 평서문' in r and "'2026.10.28'" in r and '명사형 종결' not in r)
    expect('제목은 한 줄(표지 글 여러 줄이 와도 첫 줄만 — 받기 파일 이름·헤더에 쓰임)', llm._title('계약서\n([추가 업무명])\n코쇠금융IT') == '계약서' and llm._title('') == '문서')
    expect('style 값 검사', checks.validate_style({'ending': 'x'}) and not checks.validate_style({'ending': 'plain', 'date': 'Y.MM.DD', 'max_len': 0}))

    print('⑤ 등록할 때 저장소에 올리는 파일 — 대표 문서의 글·값은 올리지 않는다')
    import app as A
    draft = {'id': 't-u1-x', 'name': '시험 팩', 'scope': 'user', 'owner': 'u1', 'version': '1.0.0', 'extends': ['corp:koscom-hwp-report'],
             'forms': [{'id': 'main', 'name': '시험', 'fmt': 'hwp', 'desc': '대표 문서 1건', 'outline': ['제1조 목적']}],
             'blocks': [{'id': 'b1', 'heading': '제1조 목적', 'text': 'Z증권 주식회사(이하 "갑")와 코쇠금융IT는 이 계약을 체결한다.'}], 'rules': []}
    sc = {'struct': 1.0, 'fixed': True, 'lost': ['24,000천원', '30만명'], 'new': ['2건'], 'grammar': []}
    rep = {'criteria': [{'id': 'numbers', 'name': '숫자·사실 보존', 'pass': False, 'detail': "빠짐 ['24,000천원', '30만명'] 새 숫자 ['2건']"}],
           'tasks': [{'doc': '원문_가나다고객.hwp', 'memo': '다음 메모로 써 줘.\n가나다고객 주식회사 이용료 24,000천원\n활동고객수 30만명', 'with': sc, 'without': sc}]}
    files = A._skill_files(draft, rep, {})
    body = '\n'.join(files.values()) + A._report_md(rep)
    expect('검증 과제 메모(prompt.md)는 올리지 않음', not any(k.endswith('prompt.md') for k in files), str([k.rsplit('/', 1)[-1] for k in files]))
    expect('메모의 글 · 숫자 · 문서 파일 이름이 스킬 파일과 PR 본문에 없음', all(s not in body for s in ('가나다고객', '24,000', '30만명', '원문_')))
    expect('채점 결과는 건수로', "'lost': 2" in str(checks.public_score(sc)) and '빠진 숫자 2건 · 새 숫자 1건' in A._report_md(rep))
    expect('스킬 글의 회사 이름으로 보이는 글을 알려 줌', checks.company_names(draft) == ['Z증권'], str(checks.company_names(draft)))

    print('⑥ 기안문의 결재 요청 문장 — 칸 뒤 조사 · 서술형 한 줄 허용 · 걸린 문장 보이기(가상 문장)')
    t = '2. 위 근거에 의거, [대상 및 추진사항]을 다음과 같이 추진하고자 합니다'
    expect('칸 뒤 조사가 받침에 맞춰 바뀌어도 고정 문구(을→를)', checks.is_fixed_item('2. 위 근거에 의거, 가상 회사 A의 임대차 계약 해지를 다음과 같이 추진하고자 합니다', [t]))
    expect('받침 있는 말(을)도 그대로 인정', checks.is_fixed_item('2. 위 근거에 의거, 가상 회사 A의 임대차 계약을 다음과 같이 추진하고자 합니다', [t]))
    expect('칸 밖 동사가 바뀌면 고정 문구가 아님', not checks.is_fixed_item('2. 위 근거에 의거, 가상 회사 A의 임대차 계약 해지를 다음과 같이 시행하고자 합니다', [t]))
    expect('[기관]으로 ↔ 로', checks.is_fixed_item('가상 기관 B로 통보함', ['[기관]으로 통보함']) and checks.is_fixed_item('가상 법인으로 통보함', ['[기관]으로 통보함']))
    expect('조사 뒤에 한글이 이어지면([칸]이다) 조사로 보지 않음', not checks.is_fixed_item('가상 사업가다', ['[사업]이다']) and checks.is_fixed_item('가상 사업이다', ['[사업]이다']))
    bp3 = {'title': 't', 'sections': [{'heading': '본문', 'table': None, 'items': [
        {'label': '', 'text': '2. 위 근거에 의거, 가상 회사 A의 임대차 계약 해지를 다음과 같이 추진하고자 합니다', 'children': []}]}]}
    fx = checks.enforce_fixed(bp3, [{'id': 'b1', 'heading': '본문', 'text': t}])
    fx = fx[0] if isinstance(fx, tuple) else fx
    n_req = sum(1 for s in fx['sections'] for it in s['items'] if '추진하고자 합니다' in it['text'])
    expect('고정 문구 틀을 한 번 더 덧붙이지 않음(결재 요청 문장 1개)', n_req == 1, f'{n_req}개')
    expect('판정 정규식이 측정과 같은 범위(바랍니다 · 드립니다도 서술형)', all(engines.BAD_END.search(x) for x in ('결재하여 주시기 바랍니다.', '보고드립니다', '추진하고자 합니다'))
           and not any(engines.BAD_END.search(x) for x in ('교체 필요', '협조 요청함', '계약 해지 예정')))
    items = [{'label': '', 'text': f'가상 항목 {i} 추진', 'children': []} for i in range(10)] + \
            [{'label': '', 'text': '가상 사업을 다음과 같이 시행하고자 합니다', 'children': []}]
    bp4 = {'title': 't', 'sections': [{'heading': '본문', 'items': items, 'table': None}]}
    st4 = {'ending': 'noun', 'date': 'Y.MM.DD', 'max_len': 90}
    e1 = next(c for c in engines.check(bp4, (), st4) if c['id'] == 'end')
    e0 = next(c for c in engines.check(bp4, (), None) if c['id'] == 'end')
    expect('대표 문서 기준 명사형: 11줄 중 서술형 1줄은 허용', e1['ok'] and not e1['fix'], str(e1))
    expect('코스콤 보고 문법 기본값은 한 줄도 허용하지 않음', not e0['ok'] and e0['fix'])
    expect('미통과 설명에 걸린 문장이 보임', '시행하고자 합니다' in e0['detail'], e0['detail'])
    f1, _ = engines.autofix(bp4, lambda xs: (xs, None), (), st4)
    f0, _ = engines.autofix(bp4, lambda xs: (xs, None), (), None)
    expect('자동 수정: 허용치 안의 서술형은 그대로, 기본 문법에서는 명사형으로', f1['sections'][0]['items'][-1]['text'].endswith('합니다') and f0['sections'][0]['items'][-1]['text'].endswith('시행하고자 함'),
           f1['sections'][0]['items'][-1]['text'] + ' / ' + f0['sections'][0]['items'][-1]['text'])
    b5 = {'title': 't', 'sections': [{'heading': '본문', 'table': None, 'items': [{'label': '', 'text': '검토하여 주시기 바랍니다', 'children': []}, {'label': '', 'text': '결과를 보고드립니다.', 'children': []}]}]}
    f5, _ = engines.autofix(b5, lambda xs: (xs, None), (), None)
    expect('자동 수정: 바랍니다 → 바람, 드립니다 → 드림', [it['text'] for it in f5['sections'][0]['items']] == ['검토하여 주시기 바람', '결과를 보고드림'], str([it['text'] for it in f5['sections'][0]['items']]))
    form5 = {'outline': ['본문'], 'style': st4}
    items6 = [{'label': '', 'text': f'가상 항목 {i} 추진', 'children': []} for i in range(3)] + [{'label': '', 'text': '가상 건을 다음과 같이 시행하고자 합니다', 'children': []},
                                                                                              {'label': '', 'text': '검토 결과를 알려 드립니다', 'children': []}]
    bp6 = {'title': 't', 'sections': [{'heading': '본문', 'items': items6, 'table': None}]}
    sc6 = A._bp_score(bp6, form5, [], '') if hasattr(A, '_bp_score') else None
    if sc6 is not None:
        expect('채점: 기준 이름(grammar)에는 문장이 없고 화면용(grammar_detail)에만 있음', sc6['grammar'] and all('하고자' not in g for g in sc6['grammar'])
               and any('시행하고자 합니다' in g for g in sc6['grammar_detail']), str(sc6))
        expect('저장소에 올리는 채점 결과에는 걸린 문장이 없음', '하고자' not in str(checks.public_score(sc6)))
        crit = {'id': 'grammar', 'name': '문체', 'pass': False, 'detail': '; '.join(sc6['grammar_detail']), 'public_detail': '; '.join(sc6['grammar'])}
        expect('PR 본문 · 스킬 파일에는 기준 이름만', '하고자' not in A._public_detail(crit, {}) and '하고자' not in A._report_md({'criteria': [crit], 'tasks': []}))


def app(force):
    from e2e_skillgen import call, BASE, op
    import urllib.request

    def try_call(path, body):
        req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={'content-type': 'application/json'})
        try:
            return json.loads(op.open(req, timeout=900).read().decode())
        except urllib.error.HTTPError as e:
            return json.loads(e.read().decode())

    doc = os.path.join(ROOT, 'seed', 'out', '계약서예시', '전산서비스_추가업무_이용계약서_E증권(가상).txt')
    if not os.path.exists(doc):
        raise SystemExit('먼저 python kosoe.py seed')
    call('/api/login', {'uid': 'u1'})
    print('⑤ 앱: 계약서 예시로 스킬 만들기 — AI', call('/api/ai')['ai']['display'])
    uid = call('/api/upload', files=[('file', doc)])['upload']['id']
    t = time.time()
    j = call('/api/skillgen/analyze', {'upload_ids': [uid], 'request': '전산서비스 추가업무 계약서 스킬 만들어줘', 'scope': 'me'})['job']
    a, f = j['analysis'], j['draft']['forms'][0]
    print(f"   분석 {time.time() - t:.1f}s {a['meta']['mode']} | 문체 {a['style']['label']} | 구성 {f['outline']}")
    expect('분석: 문서 기준 문체가 스킬 양식에 적힘', f.get('style', {}).get('ending') == 'plain', json.dumps(f.get('style'), ensure_ascii=False))
    t = time.time()
    r = call(f"/api/skillgen/{j['id']}/evaluate", {'draft': j['draft']})['report']
    print(f"   검증 {time.time() - t:.1f}s 사용 {r['with_score']}/{r['full']} 미사용 {r['without_score']}/{r['full']} auto_pass={r['auto_pass']}")
    for c in r['criteria']:
        print('     ', '✅' if c['pass'] else '❌', c['name'], '|', str(c.get('detail', ''))[:120])
    g = next(c for c in r['criteria'] if c['id'] == 'grammar')
    expect('검증: 문체 기준 이름이 문서 기준', g['name'].startswith('문체 — 대표 문서 기준'), g['name'])
    expect('검증: 문체 기준 통과', g['pass'], g.get('detail', ''))
    if not force:
        return
    print('⑥ 강제 등록(사람 확인 0건인 채로)')
    x = try_call(f"/api/skillgen/{j['id']}/submit", {'thumbs': 0})
    expect('강제 표시 없으면 거절', not x.get('ok'), x.get('error', ''))
    x = try_call(f"/api/skillgen/{j['id']}/submit", {'thumbs': 0, 'force': True, 'reason': ''})
    expect('사유 없으면 거절', not x.get('ok'), x.get('error', ''))
    t = time.time()
    x = try_call(f"/api/skillgen/{j['id']}/submit", {'thumbs': 0, 'force': True, 'reason': '시험: 사람 확인을 건너뛰고 등록되는지 확인'})
    expect('사유 있으면 등록', x.get('ok'), x.get('error', ''))
    if x.get('ok'):
        q = x['request']
        print(f"   {time.time() - t:.1f}s stage={q['stage']} pr={q['pr_url']}", [h['act'] for h in q['history']])
        expect('요청 기록에 강제 등록 표시', '강제 등록' in q['history'][0]['act'] and q['note']['report']['forced']['failed'])
        call('/api/skills?sync=1')
        s = call('/api/skills/' + j['draft']['id'])['skill'] if q['stage'] == 'done' else None
        if s:
            expect('스킬 파일에 verification: forced', (s.get('verification') or {}).get('status') == 'forced', json.dumps(s.get('verification'), ensure_ascii=False)[:160])
            expect('SKILL.md에 강제 등록 기록', '강제 등록됨' in (s.get('skill_md') or ''))


if __name__ == '__main__':
    unit()
    if '--app' in sys.argv:
        app('--force' in sys.argv)
    print('\n' + ('모두 통과' if not fails else f'실패 {len(fails)}건: ' + ', '.join(fails)))
    sys.exit(1 if fails else 0)
