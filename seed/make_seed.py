"""시연용 가상 자료 만들기 — python seed/make_seed.py [출력 폴더]

- 대표문서/: 스킬 빌더 시연용 '영업 제안서' 3건(PPT 2 · 한글 1). 목차·고정 문구가 같고 고객·숫자만 다르다.
- 시연메모_고객세미나.txt: 0:00·1:50 장면용 메모(예산 120만원)
- 계약서예시/: 보고서가 아닌 문서(계약서) 1건 — 스킬 빌더가 그 문서의 문체(서술형·날짜 형식·길이)를 기준으로 삼는지 확인용
- 계약서_3건/: 같은 서식으로 쓴 한글 계약서 3건(값만 다름) — 복제형 스킬 시연용. 스킬 빌더가 세 문서를 맞대어 칸을 찾고 원본을 서식으로 삼는다
모든 회사·사람·숫자는 가상이다.
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding='utf-8', errors='replace')

import engines  # noqa: E402
import skills  # noqa: E402

INTRO = '코쇠금융IT는 자본시장 인프라를 함께 만들어 온 금융 IT 전문 기업임(가상)'
VALID = '제안 유효기간은 제출일로부터 30일임'
NOTE = '본 자료의 수치와 일정은 협의 결과에 따라 달라질 수 있음'
CLIENTS = [
    ('B증권', 'MTS 주문 지연', '주문 처리 시간 0.8초 → 0.3초 목표', 3, '2027. 2. 1', [('분석', '1개월', '90'), ('구축', '3개월', '420'), ('안정화', '1개월', '70')], 'ppt'),
    ('C자산운용', '펀드 기준가 산출 야간 배치 지연', '배치 시간 4시간 → 1시간 목표', 4, '2027. 3. 2', [('분석', '1개월', '60'), ('구축', '2개월', '260'), ('안정화', '1개월', '50')], 'ppt'),
    ('D저축은행', '원장 시스템 노후화', '장애 건수 연 12건 → 4건 목표', 5, '2027. 4. 1', [('분석', '1개월', '80'), ('이전', '3개월', '390'), ('안정화', '2개월', '110')], 'hwp'),
]


# 보고서가 아닌 문서(계약서) 예시 — 스킬 빌더가 '그 문서 기준'으로 문체를 재는지 시험·시연한다. 회사·금액·날짜 모두 가상.
CONTRACT = """전산서비스 추가 업무 이용 계약서 (가상 예시)

2026.    .    .

E증권 주식회사(가상)
코쇠금융IT 주식회사(가상)

제 1 조【목적】
E증권 주식회사(이하 "갑"이라 한다)와 코쇠금융IT 주식회사(이하 "을"이라 한다)는 "갑"과 "을"이 2019.03.15 체결한 전산서비스 이용계약(이하 "기본계약"이라 한다)의 부속 계약으로서, "갑"이 "을"의 전산서비스의 추가 업무를 이용하는 데 필요한 사항을 정하기 위하여 이 계약을 체결한다.

제 2 조【서비스의 내용】
이 계약에 따라 "갑"이 이용하는 추가 업무는 고객확인 모니터링 고도화로 한다.

제 3 조【서비스 이용료】
이 계약에 따라 "갑"은 추가 업무 이용료로 다음의 금액을 "을"에게 지급한다. (단위 : 천원/년, 부가세 별도)
업무구분 | 이용료 | 비고
고객확인 모니터링 고도화 | 18,000 | 가동 다음 달부터 청구
합계 | 18,000 |

제 4 조【계약기간】
① 계약기간은 추가 업무 가동일부터 1년으로 한다.
② 이 계약은 기본계약이 존속하는 동안 효력을 가진다. 계약기간이 끝나기 2개월 전까지 어느 한쪽이 서면으로 다른 뜻을 알리지 않으면 이 계약은 같은 조건으로 1년씩 연장된다.

제 5 조【기타사항】
① "갑"은 "을"에게 서면으로 해지 의사를 알림으로써 이 계약을 해지할 수 있다. 이 경우 해지의 효력은 "을"이 통지서를 받은 날부터 1개월이 지난 때에 생긴다.
② 계약기간이 끝나기 전에 "갑"의 사정으로 이 계약을 해지하는 경우 "갑"은 남은 계약기간의 이용료를 "을"에게 지급한다.
③ 이 계약에서 정하지 않은 사항은 기본계약을 따른다.

이 계약의 체결을 증명하기 위하여 계약서 2부를 작성하고 "갑"과 "을"이 기명날인한 다음 각각 1부씩 보관한다.
"""


# 복제형 스킬 시연: 전사 계약서 스킬의 서식에 서로 다른 가상 값을 넣은 계약서 3건. 표는 한 행씩(구성이 같아야 줄 단위로 맞댈 수 있다)
CONTRACTS = [
    ('E증권', '서울특별시 영등포구 가상로 1', '홍 길 동', '고객확인 모니터링 고도화', '2019.03.15', '1', ('영업지원', '고객관리', '18,000', '')),
    ('F자산운용', '서울특별시 중구 가상대로 25', '이 영 수', '펀드 기준가 검증 자동화', '2021.05.10', '2', ('운용지원', '펀드', '12,000', '가동 다음 달부터')),
    ('G저축은행', '부산광역시 해운대구 가상해변로 7', '박 민 지', '여신 심사 보고서 자동 작성', '2023.11.01', '1', ('여신지원', '심사', '24,500', '')),
]


def contracts(out):
    import clone
    import corp
    if not clone.ready():
        print('계약서 3건 — 칸 채우기 전사 스킬이 잠금 파일에 없어 건너뜀')
        return
    kd = os.path.join(out, '계약서_3건')
    os.makedirs(kd, exist_ok=True)
    tmp = os.path.join(engines.JOBS, 'seed-contract')
    tpl = corp.fresh_copy(clone.ENGINE, [corp.form_of(clone.ENGINE)['template']], tmp)[0]
    for name, addr, ceo, work, base, years, (big, mid, fee, note) in CONTRACTS:
        dst = os.path.join(kd, f'추가업무계약서_{name}(가상).hwp')
        made, warns = clone.remake(tpl, {'고객사명': f'{name} 주식회사(가상)', '갑주소': addr, '갑대표이사': ceo, '을대표이사': '김 철 수', '추가업무명': work,
                                         '기본계약체결일': base, '계약기간': f'추가업무 가동 이후 {years}년간', '계약일': '2026.    .    .', '합계': fee}, dst,
                                   {'이용료': [{'대분류': big, '중분류': mid, '소분류': work, '회사기본': fee, '영업점당': '-', '이용량': '-', '비고': note}]})
        print('계약서', dst, '' if made else '실패', warns)


def bp_of(c):
    name, pain, goal, months, start, cost, _ = c
    return {'title': f'{name} 제안서', 'sections': [
        {'heading': '회사 소개', 'items': [{'label': '', 'text': INTRO, 'children': []}, {'label': '실적', 'text': '증권·자산운용·저축은행 고객 40여 곳 운영(가상)', 'children': []}], 'table': None},
        {'heading': '고객 과제', 'items': [{'label': '현황', 'text': f'{pain}이(가) 반복됨', 'children': []}, {'label': '목표', 'text': goal, 'children': []}], 'table': None},
        {'heading': '서비스 제안', 'items': [{'label': '서비스', 'text': '코쇠 원장 클라우드 도입', 'children': []}, {'label': '방식', 'text': '단계별 무중단 전환, 데이터 대조 자동화', 'children': []}], 'table': None},
        {'heading': '레퍼런스', 'items': [{'label': '사례', 'text': 'A증권 원장 클라우드 전환 완료(가상)', 'children': []}], 'table': None},
        {'heading': '일정·비용', 'items': [{'label': '기간', 'text': f'{start} 착수, {months}개월', 'children': []}, {'label': '유의', 'text': NOTE, 'children': []},
                                         {'label': '유효', 'text': VALID, 'children': []}],
         'table': {'cols': ['단계', '기간', '비용(백만원)'], 'rows': [list(r) for r in cost]}},
    ]}


def main(out):
    skills.ensure(force=True)
    d = os.path.join(out, '대표문서')
    os.makedirs(d, exist_ok=True)
    people = {'담당': '홍길동 대리', '팀장': '김철수 팀장', '부서장': '이영희 차장', 'dept': '금융영업1팀'}
    tpl = {'name': '영업 제안서', 'desc': '금융영업 고객 제안', 'preset': ''}
    for i, c in enumerate(CLIENTS, 1):
        path, warns, ms, eng = engines.make(c[6], bp_of(c), tpl, people, 'seed', i)
        dst = os.path.join(d, f'영업제안_{c[0]}.' + ('pptx' if c[6] == 'ppt' else 'hwp'))
        shutil.copy(path, dst)
        print('대표 문서', dst, f'{ms}ms', eng['name'])
    memo = ('2026 고객 세미나 준비 메모 (가상)\n'
            '- 행사명: 원장 클라우드 고객 세미나\n- 일시: 2026. 11. 20 14:00, 장소: 본사 대회의실\n'
            '- 대상: 증권·자산운용 고객 IT 담당자, 참석 인원 45명\n- 예산: 120만원 (다과 40만원, 기념품 80만원)\n'
            '- 진행: 서비스 소개 20분, A증권 전환 사례 20분, 질의응답 20분\n- 후속: 참석사 대상 개별 PoC 제안\n')
    mp = os.path.join(out, '시연메모_고객세미나.txt')
    open(mp, 'w', encoding='utf-8').write(memo)
    print('시연 메모', mp)
    cd = os.path.join(out, '계약서예시')
    os.makedirs(cd, exist_ok=True)
    cp = os.path.join(cd, '전산서비스_추가업무_이용계약서_E증권(가상).txt')
    open(cp, 'w', encoding='utf-8').write(CONTRACT)
    print('계약서 예시', cp)
    contracts(out)
    # 검수 시연: 사람이 고치다 예산을 잘못 바꾼 PPT(100만원)와 바로잡은 PPT(120만원)
    ev = lambda budget: {'title': '원장 클라우드 고객 세미나 계획', 'sections': [
        {'heading': '행사 개요', 'items': [{'label': '일시', 'text': '2026. 11. 20 14:00, 본사 대회의실', 'children': []},
                                         {'label': '대상', 'text': '증권·자산운용 고객 IT 담당자, 참석 인원 45명', 'children': []}], 'table': None},
        {'heading': '소요 예산', 'items': [{'label': '예산', 'text': f'{budget}만원 (다과 40만원, 기념품 80만원)', 'children': []}], 'table': None},
        {'heading': '진행 순서', 'items': [{'label': '1부', 'text': '서비스 소개 20분', 'children': []}, {'label': '2부', 'text': 'A증권 전환 사례 20분', 'children': []},
                                         {'label': '3부', 'text': '질의응답 20분', 'children': []}], 'table': None}]}
    for name, budget in (('검수시연_사람이고친PPT_예산오류.pptx', 100), ('검수시연_사람이고친PPT_수정본.pptx', 120)):
        path, *_ = engines.make('ppt', ev(budget), {'name': '행사 계획', 'desc': '고객 세미나'}, people, 'seed-ev', budget)
        shutil.copy(path, os.path.join(out, name))
        print('검수 시연', name)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'seed', 'out'))
