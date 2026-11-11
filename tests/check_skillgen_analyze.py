"""스킬 만들기 ② 분석 뒤처리 시험 — AI 없이, GitHub에 쓰지 않고.

    python tests/check_skillgen_analyze.py

AI가 뽑은 장 · 규칙을 앞에서 자르지 않고 거르는지 본다: 장 번호 떼기(엔진이 장 머리를 붙인다), 서식 · 개인정보 규칙은 이유와 함께 빼기,
내용 규칙은 6개 넘게 남기기. 함수 시험 + ② 분석 API(AI 응답을 고정한 값으로 바꿔서) 시험.
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.join(ROOT, 'tests', '_home_clone')
os.environ['KOSOE_HOME'] = HOME
os.environ['KOSOE_CLOSED_LLM'] = 'rule'
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))
sys.dont_write_bytecode = True
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding='utf-8', errors='replace')

import make_local_home  # noqa: E402

make_local_home.ensure(HOME)                 # 시험용 데이터 폴더가 없으면 만든다(실제 ~/.kosoe 에서 복사 — GitHub와 분리)
if os.path.exists(os.path.join(HOME, 'kosoe.db')):
    os.remove(os.path.join(HOME, 'kosoe.db'))

import app as A  # noqa: E402
import core  # noqa: E402
import local_github  # noqa: E402

local_github.install()
fails = []


def expect(name, cond, detail=''):
    print('  ', '✅' if cond else '❌', name, '' if cond else str(detail)[:300])
    if not cond:
        fails.append(name)


print('① 장 이름 다듬기')
nh = A.norm_heading
expect('장 번호를 뗀다: 「1. 추진 개요」 「가. 배경」 「Ⅱ. 추진 내용」 「3) 일정」',
       [nh(x) for x in ('1. 추진 개요', '가. 배경', 'Ⅱ. 추진 내용', '3) 일정', ' 12. 기타 사항 ')] == ['추진 개요', '배경', '추진 내용', '일정', '기타 사항'],
       [nh(x) for x in ('1. 추진 개요', '가. 배경', 'Ⅱ. 추진 내용', '3) 일정', ' 12. 기타 사항 ')])
expect('끝의 설명 괄호를 뗀다: 「4. 소요 예산 (표)」', nh('4. 소요 예산 (표)') == '소요 예산', nh('4. 소요 예산 (표)'))
expect('번호가 아닌 것은 그대로: 「2026년 계획」 「3.5 버전 개요」 「가격 정책」 「개요」',
       [nh(x) for x in ('2026년 계획', '3.5 버전 개요', '가격 정책', '개요')] == ['2026년 계획', '3.5 버전 개요', '가격 정책', '개요'],
       [nh(x) for x in ('2026년 계획', '3.5 버전 개요', '가격 정책', '개요')])
expect('서술형 문서(계약서 · 규정)의 조 · 항 번호는 그대로 둔다', nh('1. 목적', prose=True) == '1. 목적' and nh('제 2 조【서비스의 내용】', prose=True) == '제 2 조【서비스의 내용】')

print('② 규칙 거르기')
RULES = ['본문은 맑은 고딕 12pt로 쓴다', '소제목은 굵게 표시한다', '항목은 들여쓰기 2칸', '표는 가운데 정렬한다', '문단 사이에 빈 줄을 둔다',
         '고객사 실명과 담당자 연락처는 가린다',
         '결론을 먼저 쓴다', '관련 근거에는 직접 근거가 되는 문서만 적는다', '금액은 억원 단위로 쓰고 부가세 포함 여부를 밝힌다',
         '표가 2행 이상이면 합계 행을 둔다', '일정은 금액 내림차순으로 정렬하지 않고 날짜순으로 적는다', '해당 사항이 없는 장은 지운다',
         '협조 요청 사항은 필요할 때만 쓴다', '첨부는 한 문서를 한 번만 적는다', '결론을 먼저 쓴다', '']
keep, drop = A.split_rules(RULES)
expect('내용 규칙 8개가 모두 남는다(앞 6개에서 자르지 않는다)', len(keep) == 8 and keep[0] == '결론을 먼저 쓴다' and keep[-1] == '첨부는 한 문서를 한 번만 적는다', keep)
expect('서식 규칙 5개는 「서식」 이유로 뺀다', [d['why'] for d in drop].count('서식(엔진이 맡음)') == 5, drop)
expect('개인정보 규칙은 「개인정보」 이유로 뺀다', [d for d in drop if d['why'].startswith('개인정보')] == [{'rule': '고객사 실명과 담당자 연락처는 가린다', 'why': '개인정보(검사가 맡음)'}], drop)
expect('「날짜순으로 정렬」 같은 내용 규칙은 서식으로 보지 않는다', any('날짜순' in k for k in keep))
expect('같은 규칙 · 빈 규칙은 한 번만', keep.count('결론을 먼저 쓴다') == 1 and '' not in keep)
expect('내용 규칙은 20개까지', len(A.split_rules([f'규칙 {i}번은 그대로 둔다' for i in range(30)])[0]) == 20)
expect('규칙이 없으면 빈 목록', A.split_rules(None) == ([], []))

print('③ ② 분석 API — AI 응답을 고정한 값으로 바꿔서')
core.init_db()
A.load_ai_choice()
A.sync_forms(force=True)
c = A.app.test_client()
assert c.post('/api/login', json={'uid': 'u1'}).status_code == 200
DOC = ('전사 회의실 예약 체계 개선 결과 보고\n1. 추진 개요\nㅇ 회의실 예약 중복을 줄이기 위해 예약 체계를 개선함\n2. 추진 내용\nㅇ 예약 화면 통합 및 알림 기능 추가\n'
       '3. 추진 일정\nㅇ 2026. 9. 1. 착수, 2026. 10. 30. 완료\n4. 소요 예산\nㅇ 총 1.2억원(부가세 포함)\n5. 기타 사항\nㅇ 세부 일정은 유관 부서 협의 후 확정 예정\n')
r = c.post('/api/upload', data={'file': (io.BytesIO(DOC.encode('utf-8')), '회의실예약_결과보고.txt')}, content_type='multipart/form-data')
uid = r.get_json()['upload']['id']
AI = {'name_suggest': '결과 보고', 'outline': ['1. 추진 개요', '2. 추진 내용', '3. 추진 일정', '4. 소요 예산 (표)', '5. 기타 사항', '결재란', '1. 추진 개요'],
      'fixed': [{'heading': '5. 기타 사항', 'text': 'ㅇ 세부 일정은 유관 부서 협의 후 확정 예정'}],
      'fields': [{'name': '사업명', 'desc': '', 'example': '', 'kind': '칸'}], 'rules': RULES}
real = A.llm.extract
A.llm.extract = lambda docs, ctx=None, prose=False: (dict(AI), {'mode': 'llm', 'label': '시험용 고정 응답', 'ms': 0, 'model': 'test'})
try:
    r = c.post('/api/skillgen/analyze', json={'upload_ids': [uid], 'request': '회의실 결과 보고 팩 만들어줘', 'scope': 'me', 'mode': 'compose'})
finally:
    A.llm.extract = real
d = r.get_json() or {}
job = d.get('job') or {}
draft, ana = job.get('draft') or {}, job.get('analysis') or {}
expect('분석이 끝난다', r.status_code == 200 and d.get('ok'), f'{r.status_code} {str(d)[:300]}')
ol = (draft.get('forms') or [{}])[0].get('outline')
expect('장 목록에 번호 · 설명 괄호 · 결재란 · 겹침이 없다', ol == ['추진 개요', '추진 내용', '추진 일정', '소요 예산', '기타 사항'], ol)
expect('초안 규칙 = 내용 규칙 8개', draft.get('rules') == keep, draft.get('rules'))
expect('뺀 규칙 6개가 이유와 함께 분석 결과에 남는다(③ 화면에 보임)', ana.get('dropped_rules') == drop, ana.get('dropped_rules'))
bl = draft.get('blocks') or [{}]
expect('고정 문구의 장은 번호를 뗀 장 이름에 맞춰진다', bl[0].get('heading') == '기타 사항' and bl[0].get('text', '').startswith('세부 일정'), bl)
expect('초안이 스킬 검사를 통과한다', not A.skills.validate(draft, A.skills.all_skills() | {draft['id']: draft}), A.skills.validate(draft, A.skills.all_skills() | {draft.get('id'): draft}) if draft else '')

print('check_skillgen_analyze OK' if not fails else f'실패 {len(fails)}건: ' + ' / '.join(fails))
sys.exit(1 if fails else 0)
