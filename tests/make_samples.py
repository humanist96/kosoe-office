"""새 문서 카드 샘플 그림: 양식마다 가상 표본 설계도(sample.json) → 엔진으로 문서 → 앞쪽 몇 장을 그림(webp)으로.

  KOSOE_HOME=<데이터 폴더> PLAYWRIGHT_CORE=<playwright-core 경로> python tests/make_samples.py [--fmt ppt,web] [양식 id ...]
  → 스킬 저장소(KOSOE_HOME/skills-repo)의 샘플 폴더에 sample.json · 01.webp … — 전사 양식은 registry/samples/<id>/,
    스킬 양식은 <스킬 폴더>/samples/<양식 id>/ (앱 _sample_dir). 저장소 브랜치에 커밋해 PR로 올린다.

- 데이터 폴더는 실제 ~/.kosoe 가 아닌 시험용 폴더를 쓴다(tests/make_local_home.py — 그림이 그 폴더의 스킬 저장소 사본에 생긴다).
- sample.json 이 있으면 그 설계도로 다시 그리기만 하고, 없으면 AI로 만든다(앱의 초안 만들기와 같은 길). 내용을 바꾸려면 sample.json 을 지우고 다시 돌린다.
- 그림: PPT = PowerPoint 내보내기(앞 4장, 1920×1080) · 웹 = 전사 웹 스킬의 check_deck.js(앞 4장) ·
  한글 = 한컴 한글 → PDF → PNG(앞 3쪽). 한글은 한컴 한글과 전사 한글 스킬의 scripts/hangul.py 가 있는 PC에서만 된다 — 없으면 그 양식은 건너뛴다.
- 서식 채우기형 · 복제형 양식(모양이 서식 파일로 정해진 것)은 양식 id를 직접 줄 때만 그린다.
- 샘플은 공개 저장소에 올라간다: 내용은 가상으로 짓고(RULE), 올리기 전에 sample.json 과 그림을 사람이 본다.
"""
import concurrent.futures as cf
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding='utf-8', errors='replace')

from PIL import Image  # noqa: E402

import app  # noqa: E402  — 앱과 같은 양식 행 · 작성 규칙 · 렌더 정보 · 샘플 폴더를 쓴다
import checks  # noqa: E402
import core  # noqa: E402
import corp  # noqa: E402
import engines  # noqa: E402
import llm  # noqa: E402

PEOPLE = {'담당': '홍길동 대리', '팀장': '김철수 팀장', '부서장': '이영희 차장', 'dept': '금융영업1팀', 'hq': '금융영업본부'}
MAX = {'hwp': 3, 'ppt': 4, 'web': 4}
WIDTH = {'hwp': 1600, 'ppt': 1920, 'web': 1440}      # 저장할 때의 가로 한도(px) — 크게 보기의 폭 맞춤에서 늘이지 않게
RULE = ("이 문서는 양식 갤러리에 보여 줄 샘플이다. 요청의 주제로 가상의 내용을 그럴듯하게 채운다 — 숫자·날짜·일정·금액·근거 문서 번호를 지어 넣는다. "
        "'(확인 필요)'는 쓰지 않는다. 실존 회사·기관·제품 이름과 실명은 쓰지 않는다(고객사는 A증권·B은행처럼, 사람은 홍길동·김철수·이영희·박지원·최수민). "
        "전화번호·이메일·계좌번호처럼 개인정보로 보이는 값은 쓰지 않는다(연락처는 '내선 2345'처럼). 제목은 22자 이내. "
        "숫자 비교가 어울리는 장 하나 이상에는 표(3~5행)를 넣는다.")
TOPIC = {   # 처음 만들 때만 쓰는 샘플 주제(없는 양식은 양식 설명) — 만든 뒤에는 sample.json 의 request 에 남는다
    'result-report': '2026년 하반기 사내 생성형 AI 활용 교육 결과(4회 운영, 수료 212명, 만족도 4.6점)',
    'plan-report': '2027년 고객 상담 챗봇 도입 계획(1분기 시범, 2분기 확대)',
    'review-report': '업무용 노트북 600대 교체 방식 검토(구매와 3년 임차 비교)',
    'issue-report': '2026. 11. 3 시세 조회 API 응답 지연 장애(09:12~09:47, 35분)',
    'meeting-report': '차세대 원장 시스템 착수 회의 결과(유관 부서 6곳 참석)',
    'trip-report': '싱가포르 핀테크 행사 출장 결과(2026. 11. 4 ~ 11. 7)',
    'visit-report': 'A증권 IT기획팀 방문 결과(원장 클라우드 전환 협의)',
    'event-plan': '2026 송년 기술 세미나 행사 계획(12. 18, 본사 대강당, 200명)',
    'weekly-report': '금융영업1팀 11월 2주차 주간 업무 보고',
    'education-plan': '신입사원 금융IT 기초 교육 과정 기획(3일, 40명)',
    'deck-proposal': 'B증권 원장 시스템 클라우드 전환 제안',
    'deck-exec': '데이터센터 전력 설비 증설 결정 요청',
    'web-brief': '3분기 금융영업1팀 실적 브리핑(매출 128억원, 전년 대비 12% 증가)',
    'web-edu': '신입 직원 개인정보 보호 기본 교육',
    'planning-pack:summary-report': '2027년 전사 데이터 거버넌스 체계 구축 추진 계획',
    'sales-pack:proposal': 'A증권 원장 시스템 클라우드 전환 제안',
    'sales-pack:briefing': 'B은행 대상 시세 데이터 API 서비스 브리핑',
    'sales-pack:visit-report': 'C자산운용 운용지원팀 방문 결과(시세 데이터 API 도입 협의)',
}


def sample_bp(t):
    """AI로 가상 표본 설계도(앱 초안 만들기와 같은 길: 스킬 규칙 → llm.blueprint → 고정 문구)."""
    tl = app._tpl_for_llm(t)
    tl['rules'] = f"{tl['rules']}\n{RULE}".strip()
    req = f"{TOPIC.get(t['id'], t['desc'])} — 「{t['name']}」 양식 샘플"
    bp, meta = llm.blueprint(tl, req, [], {'use_llm': True})
    if meta['mode'] != 'llm':
        raise RuntimeError('AI 없이 만들어짐: ' + (meta.get('error') or 'AI 연결 없음'))
    bp = checks.enforce_fixed(bp, json.loads(t['fixed'] or '[]'))
    return {'request': req, 'model': meta.get('model', ''), 'made': core.today_kr(), 'blueprint': bp}


def pngs(fmt, path, tmp):
    """문서 → 앞쪽 몇 장의 PNG 경로."""
    if fmt == 'hwp':
        script = corp.path(engines.HWP, 'scripts/hangul.py')
        if not os.path.exists(script):
            raise RuntimeError('한글 양식은 한컴 한글과 전사 한글 스킬의 scripts/hangul.py 가 있는 PC에서만 그릴 수 있습니다')
        py = os.environ.get('HWP_PY') or shutil.which('python')
        r = subprocess.run([py, script, 'pages', path, tmp, '--dpi', '192'], capture_output=True, timeout=300)
        files = sorted(glob.glob(os.path.join(tmp, 'page-*.png')))
    elif fmt == 'ppt':     # 사용자가 PowerPoint를 켜 두었으면 끄지 않는다
        was = b'POWERPNT.EXE' in subprocess.run(['tasklist', '/FI', 'IMAGENAME eq POWERPNT.EXE'], capture_output=True).stdout
        ps = (f"$pp = New-Object -ComObject PowerPoint.Application; $p = $pp.Presentations.Open('{path}', $true, $false, $false); "
              f"$i = 1; foreach ($s in $p.Slides) {{ if ($i -gt {MAX['ppt']}) {{ break }}; $s.Export('{tmp}\\s' + $i + '.png', 'PNG', 1920, 1080); $i++ }}; "
              f"$p.Close(){'' if was else '; $pp.Quit()'}")
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True, timeout=300)
        files = sorted(glob.glob(os.path.join(tmp, 's*.png')), key=lambda p: int(os.path.basename(p)[1:-4]))
    else:
        r = subprocess.run(['node', corp.path('koscom-webslide', 'scripts/check_deck.js'), path, '--shots', tmp], capture_output=True, timeout=600)
        files = sorted(glob.glob(os.path.join(tmp, 's[0-9]*.png')))
    if not files:
        raise RuntimeError('그림 없음: ' + (r.stdout + r.stderr).decode('utf-8', 'replace')[-400:])
    return files[:MAX[fmt]]


def save(d, files, fmt):
    for old in glob.glob(os.path.join(d, '*.webp')):
        os.remove(old)
    for i, p in enumerate(files, 1):
        im = Image.open(p).convert('RGB')
        if im.width > WIDTH[fmt]:
            im = im.resize((WIDTH[fmt], round(im.height * WIDTH[fmt] / im.width)), Image.LANCZOS)
        im.save(os.path.join(d, f'{i:02d}.webp'), 'WEBP', quality=80, method=6)
    return len(files)


def main(argv):
    fmts = None
    if '--fmt' in argv:
        i = argv.index('--fmt')
        fmts = set(argv[i + 1].split(','))
        argv = argv[:i] + argv[i + 2:]
    ids = argv
    home = os.path.normcase(os.path.abspath(core.HOME)) if hasattr(core, 'HOME') else ''
    if home and home == os.path.normcase(os.path.abspath(os.path.expanduser(os.path.join('~', '.kosoe')))) and '--real-home' not in ids:
        raise SystemExit('실제 데이터 폴더(~/.kosoe)입니다 — KOSOE_HOME을 시험용 폴더로 주고 돌리세요(tests/make_local_home.py)')
    core.init_db()
    app.load_ai_choice()
    app.sync_forms()
    corp.warm()
    ts = []
    for t in core.rows(core.db(), 'select * from templates order by path, id'):
        fill = (json.loads(t['skill'] or '{}') or {}).get('fill')
        if (t['id'] in ids) if ids else (not fill and (not fmts or t['fmt'] in fmts)):
            ts.append(t)
    bad = {}

    def need(t):
        p = os.path.join(app._sample_dir(t), 'sample.json')
        if os.path.exists(p):
            return
        try:
            s = sample_bp(t)
        except Exception as e:
            bad[t['id']] = f'설계도: {e}'
            return
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(s, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        left = json.dumps(s['blueprint'], ensure_ascii=False).count('(확인 필요)')
        print(f"설계도 {t['id']}: {s['blueprint']['title']}" + (f' · (확인 필요) {left}곳' if left else ''), flush=True)

    with cf.ThreadPoolExecutor(2) as ex:      # AI 호출만 병렬, 그리기(PowerPoint · 브라우저)는 하나씩
        list(ex.map(need, ts))
    for t in ts:
        if t['id'] in bad:
            continue
        d = app._sample_dir(t)
        sp = os.path.join(d, 'sample.json')
        s = json.load(open(sp, encoding='utf-8'))
        info = json.loads(t['skill'] or '{}')
        try:
            tpl = app.template_for_render(t)
            make = lambda: engines.make(t['fmt'], s['blueprint'], tpl, PEOPLE, 'sample-' + t['id'].replace(':', '-'), 1)  # noqa: E731
            path, warns, _, eng = make()
            style, fx = app._style_of(t)      # 스킬의 문체 · 글자 그대로 넣는 글(앱의 검수 자동 수정과 같게)
            if any(c['fix'] for c in engines.check(s['blueprint'], warns if t['fmt'] == 'hwp' else (), style, fx)):     # 검수 [자동 수정] 한 번
                bp, _ = engines.autofix(s['blueprint'], lambda xs: llm.shorten(xs, {'use_llm': True, 'fast': True}, style), warns, style, fx)
                s['blueprint'] = checks.fix_skill(bp, {**info, 'fixed': json.loads(t['fixed'] or '[]')}) if info.get('id') else bp
                json.dump(s, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                path, warns, _, eng = make()
            if '대체' in eng.get('name', ''):      # 전사 엔진이 아니라 대체 렌더러로 만들어졌으면 카드 모양과 실제 결과가 달라진다
                raise RuntimeError(f"전사 엔진으로 만들지 못함: {eng['name']} {warns[:1]}")
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                n = save(d, pngs(t['fmt'], path, tmp), t['fmt'])
            print(f"그림 {t['id']}: {n}장 · {eng['name']}" + (f' · 경고 {warns[:2]}' if warns else ''), flush=True)
        except Exception as e:
            bad[t['id']] = f'그림: {e}'
    for k, v in bad.items():
        print(f'실패 {k}: {v}')
    print(f"완료 {len(ts) - len(bad)}/{len(ts)}")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
