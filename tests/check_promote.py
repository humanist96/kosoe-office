"""부서 · 전사 팩 검수 요청(범위 올리기)과 승인 단계 끝까지 시험 — 서버 없이(Flask test_client), GitHub에 쓰지 않고, AI 없이.

    python tests/check_promote.py

보는 것
- 전사 공개 팩(share: corp)의 변경은 부서 관리자 → 전사 관리자 단계를 거친다. 그 단계의 승인권자가 조직에 없으면 한 단계 위가 대신 승인한다.
- 개인 스킬 → 전사 팩 검수 요청: 폴더를 옮기는 PR, 승인 순서, 처리 중 요청 막기(409), 좁은 팩 상속 막기, 샘플 그림(바이너리) 그대로 옮기기.
- 올린 뒤의 변경 · 샘플 그림이 든 태그로 복구, 팀 팩 → 부서 팩, 스킬 저장소 검사(tools/validate.py).
데이터 폴더는 tests/_home_promote(매번 새로 만든다)이고, 스킬 저장소의 원격은 그 안의 origin.git(이 PC의 사본)이다.
"""
import hashlib
import io
import os
import shutil
import stat
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.join(ROOT, 'tests', '_home_promote')
os.environ['KOSOE_HOME'] = HOME
os.environ['KOSOE_CLOSED_LLM'] = 'rule'
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))
sys.dont_write_bytecode = True
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding='utf-8', errors='replace')

import make_local_home  # noqa: E402


def _rm(fn, p, _):                           # git 객체는 읽기 전용이라 지우기 전에 풀어 준다
    os.chmod(p, stat.S_IWRITE)
    fn(p)


if os.path.isdir(HOME):
    shutil.rmtree(HOME, onerror=_rm)
make_local_home.ensure(HOME)                 # 실제 ~/.kosoe 에서 복사(읽기만) — GitHub와 분리

import yaml  # noqa: E402
from PIL import Image  # noqa: E402

import app as A  # noqa: E402
import core  # noqa: E402
import gitutil  # noqa: E402
import skills  # noqa: E402
import local_github  # noqa: E402

local_github.install()                       # 원격이 GitHub이면 여기서 멈춘다
fails, n = [], [0]


def expect(name, cond, detail=''):
    n[0] += 1
    print('  ', '✅' if cond else '❌', name, '' if cond else str(detail)[:300])
    if not cond:
        fails.append(name)


def git(*a):
    return gitutil.git(*a, cwd=skills.REPO)


SID, CHILD = 'check-pack-u1', 'check-child-u1'


def fixture():
    """시험용 개인 스킬 2개를 사본 저장소 main에 올린다: 전사 스킬만 상속(샘플 그림 1장) · 팀 팩(sales-pack) 상속."""
    def skill(sid, name, ext):
        return {'id': sid, 'name': name, 'scope': 'user', 'owner': 'u1', 'version': '1.0.0', 'grade': 'i', 'extends': ext,
                'forms': [{'id': 'main', 'name': name.replace(' 팩', ''), 'fmt': 'hwp', 'use': '보고', 'outline': ['추진 배경', '추진 내용', '향후 계획'],
                           'desc': '시험용 가상 양식', 'blocks': ['b1']}],
                'blocks': [{'id': 'b1', 'heading': '향후 계획', 'text': '세부 일정은 유관 부서 협의 후 확정 예정'}],
                'glossary': {'terms': {}, 'banned': []}, 'checks': {'required': [], 'banned': []}, 'rules': ['결론을 먼저 쓴다']}
    buf = io.BytesIO()
    Image.new('RGB', (64, 90), (240, 110, 30)).save(buf, 'WEBP')
    files = {}
    for s in (skill(SID, '시험 보고 팩', ['corp:koscom-hwp-report']), skill(CHILD, '시험 제안 팩', ['skill:sales-pack', 'corp:koscom-hwp-report'])):
        d = skills.skill_dir(s)
        files[f'{d}/kosoe-skill.yaml'] = skills.dump_skill(s)
        files[f'{d}/SKILL.md'] = f"# {s['name']}\n\n시험용 가상 스킬.\n"
    files[f'{skills.skill_dir({"scope": "user", "owner": "u1", "id": SID})}/samples/main/01.webp'] = buf.getvalue()
    for rel, content in files.items():
        p = os.path.join(skills.REPO, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with (open(p, 'wb') if isinstance(content, bytes) else open(p, 'w', encoding='utf-8', newline='\n')) as f:
            f.write(content)
    git('add', '-A')
    git('-c', 'user.name=local-test', '-c', 'user.email=local-test@example.invalid', 'commit', '-q', '-m', 'test fixture: 시험용 개인 스킬')
    for sid in (SID, CHILD):
        git('-c', 'user.name=local-test', '-c', 'user.email=local-test@example.invalid', 'tag', '-a', f'{sid}@v1.0.0', '-m', 'fixture')
    git('push', '-q', 'origin', 'main', '--tags')
    return buf.getvalue()


core.init_db()
A.load_ai_choice()
webp = fixture()
skills.STATE['synced'] = 0
skills.ensure(force=True)
A.sync_forms(force=True)
c = A.app.test_client()


def req(path, body=None, get=False):
    r = c.get(path) if get or body is None else c.post(path, json=body)
    out = r.status_code, (r.get_json(silent=True) or {}), r.data
    r.close()                                 # 샘플 그림 응답이 파일을 잡고 있으면 Windows에서 git이 그 파일을 옮기지 못한다
    return out


def login(uid):
    assert req('/api/login', {'uid': uid})[0] == 200


def view(sid):
    return req(f'/api/skills/{sid}')[1]['skill']


def reqs():
    return req('/api/requests')[1]['requests']


def decide(rid, approve=True, note=''):
    code, d, _ = req(f'/api/requests/{rid}/decide', {'approve': approve, 'note': note})
    return code, d.get('request') or d


def text_at(rel):
    return gitutil.git('show', f'origin/main:{rel}', cwd=skills.REPO)


allsk = skills.all_skills()
expect('시험용 스킬 2개가 저장소 검사를 통과한다', not skills.validate(allsk[SID], allsk) and not skills.validate(allsk[CHILD], allsk),
       skills.validate(allsk[SID], allsk) + skills.validate(allsk[CHILD], allsk))

print('① 전사 공개 팩(planning-pack, share: corp)의 변경 — 부서 → 전사 단계, 승인권자가 없는 단계는 위에서 대신')
login('u4')                                   # 박지원 부장(전사 관리자, 경영기획본부)
pp = view('planning-pack')
expect('전사 공개 팩의 범위는 「전사」', pp['scope'] == 'corp', pp['scope'])
expect('이미 전사 범위인 팩에는 검수 요청 단추가 없다', pp['promote'] == [], pp['promote'])
code, d, _ = req('/api/skills/planning-pack/change', {'rules': pp['own_rules'] + ['시험용 규칙 — 승인 단계 확인'], 'note': '승인 단계 시험'})
r0 = d.get('request') or {}
expect('변경 요청 단계가 부서 관리자 → 전사 관리자', code == 200 and r0.get('stages') == ['dept', 'corp'] and r0.get('stage') == 'dept', f'{code} {d}')
expect('경영기획본부에는 부서 관리자가 없다 → 전사 관리자가 부서 단계를 대신 승인할 수 있다', r0.get('can_decide') is True)
login('u3')                                   # 이영희 차장(부서 관리자, 금융영업본부) — 다른 본부
expect('다른 본부의 부서 관리자는 승인권자가 아니다', decide(r0['id'])[0] == 403)
login('u4')
code, r1 = decide(r0['id'])
expect('부서 단계 승인 → 전사 단계로', code == 200 and r1.get('stage') == 'corp', f'{code} {r1}')
code, r1 = decide(r0['id'])
expect('전사 단계 승인 → 병합 · 태그', code == 200 and r1.get('stage') == 'done' and 'planning-pack@v1.3.0' in skills.tags_of('planning-pack'), f'{code} {r1}')
with A.app.test_request_context():
    A.g.con = core.db()
    lead = {'stage': 'lead', 'team': '금융영업2팀', 'dept': '금융영업본부'}       # 금융영업2팀에는 팀장이 없다
    u = lambda uid: core.get_user(A.g.con, uid)  # noqa: E731
    expect('팀장이 없는 팀의 팀장 단계는 그 본부의 부서 관리자가 대신 승인한다', A._approver_ok(lead, u('u3')) and not A._approver_ok(lead, u('u2')))
    expect('팀장이 있는 팀은 그대로 팀장만 승인한다', A._approver_ok({**lead, 'team': '금융영업1팀'}, u('u2')) and not A._approver_ok({**lead, 'team': '금융영업1팀'}, u('u3')))

print('② 스킬 화면 — 검수 요청 단추와 막는 이유')
login('u1')                                   # 홍길동 대리
s = view(SID)
tg = {p['target']: p for p in s['promote']}
expect('개인 스킬에 부서 팩 · 전사 팩 단추가 나온다', set(tg) == {'dept', 'corp'} and not tg['dept']['why'] and not tg['corp']['why'], s['promote'])
expect('승인 단계: 부서 팩 = 부서 관리자, 전사 팩 = 부서 관리자 → 전사 관리자',
       tg['dept']['stages'] == ['부서 관리자 승인'] and tg['corp']['stages'] == ['부서 관리자 승인', '전사 관리자 승인'], s['promote'])
ch = view(CHILD)
expect('팀 팩을 상속한 스킬은 막는 이유가 보인다', all('sales-pack' in p['why'] for p in ch['promote']) and len(ch['promote']) == 2, ch['promote'])
code, d, _ = req(f'/api/skills/{CHILD}/promote', {'target': 'dept'})
expect('팀 팩을 상속한 스킬의 검수 요청은 400', code == 400 and 'sales-pack' in d.get('error', ''), f'{code} {d}')
code, d, _ = req(f'/api/skills/{SID}/promote', {'target': 'team'})
expect('올릴 범위가 틀리면 400', code == 400, f'{code} {d}')
login('u5')                                   # 최수민 과장(다른 본부)
expect('남의 개인 스킬은 403', req(f'/api/skills/{SID}/promote', {'target': 'corp'})[0] == 403)
expect('없는 스킬은 404', req('/api/skills/no-such-skill/promote', {'target': 'corp'})[0] == 404)

print('③ 홍길동 대리: 전사 팩 검수 요청')
login('u1')
branches0 = git('branch', '--list')
code, d, _ = req(f'/api/skills/{SID}/promote', {'target': 'corp', 'note': '본부 표준으로 쓰고 싶습니다'})
r = d.get('request') or {}
OLD, NEW = f'skills/user/u1/{SID}', f'skills/org/금융영업본부/{SID}'
expect('검수 요청이 열린다(부서 단계, 전사 범위)', code == 200 and r.get('stage') == 'dept' and r.get('stages') == ['dept', 'corp'] and r.get('scope') == 'corp', f'{code} {d}')
expect('요청 이름 · 버전 · 옮길 자리', r.get('kind_name') == '검수 요청(범위 올리기)' and r['note']['version'] == '1.1.0' and r.get('path') == NEW, r)
expect('요청 기록에 옛 자리 → 새 자리와 메모', f'{OLD} → {NEW}' in r['history'][0]['note'] and '본부 표준' in r['history'][0]['note'], r['history'])
expect('요청 카드에 샘플 그림 목록', r.get('samples') == {f'{SID}:main': ['01.webp']}, r.get('samples'))
expect('처리 중: 검수 요청을 또 내면 409', req(f'/api/skills/{SID}/promote', {'target': 'dept'})[0] == 409)
expect('처리 중: 변경 요청은 409', req(f'/api/skills/{SID}/change', {'rules': ['x']})[0] == 409)
expect('처리 중: 복구 요청은 409', req(f'/api/skills/{SID}/revert', {'tag': f'{SID}@v1.0.0'})[0] == 409)
expect('스킬 화면에 「처리 중」', view(SID)['pending'] is True)
expect('요청자는 승인할 수 없다', decide(r['id'])[0] == 403)

print('④ 승인권자가 보는 것 — 샘플 그림은 볼 수 있는 사람과 지금 단계의 승인권자만')
SURL = f'/api/samples/{SID}:main/01.webp'
expect('요청자(만든 사람)는 샘플을 본다', req(SURL, get=True)[0] == 200)
login('u2')                                   # 김철수 팀장 — 이 요청의 승인권자가 아니다
expect('승인권자가 아닌 팀장은 샘플 404', req(SURL, get=True)[0] == 404)
expect('팀장은 부서 단계를 승인할 수 없다(403)', decide(r['id'])[0] == 403)
login('u3')                                   # 이영희 차장 — 부서 관리자(지금 단계)
code, _, data = req(SURL, get=True)
expect('지금 단계의 승인권자(부서 관리자)는 아직 개인 양식인 샘플을 본다 · 바이트 그대로', code == 200 and data == webp, code)
expect('샘플 폴더 밖의 파일은 읽을 수 없다', req(f'/api/samples/{SID}:main/kosoe-skill.yaml', get=True)[0] == 404
       and req(f'/api/samples/{SID}:main/..%2F..%2Fkosoe-skill.yaml', get=True)[0] == 404)
mine = [x for x in reqs() if x['id'] == r['id']]
expect('승인함에 「내 차례」로 보인다', bool(mine) and mine[0]['can_decide'] is True)
expect('승인권자도 스킬 내용을 열 수 있고, 고치기 · 검수 요청 단추는 없다', view(SID)['can_change'] is False and view(SID)['promote'] == [])
code, r2 = decide(r['id'], note='본부 표준으로 적합')
expect('부서 관리자 승인 → 전사 단계', code == 200 and r2.get('stage') == 'corp', f'{code} {r2}')
expect('부서 관리자는 전사 단계를 승인할 수 없다(403)', decide(r['id'])[0] == 403)
expect('아직 병합 전 — 저장소 main에는 옛 자리 그대로', os.path.isdir(os.path.join(skills.REPO, *OLD.split('/'))) and not os.path.isdir(os.path.join(skills.REPO, *NEW.split('/'))))
login('u4')
code, r3 = decide(r['id'])
expect('전사 관리자 승인 → 병합 · 태그 v1.1.0', code == 200 and r3.get('stage') == 'done' and f'{SID}@v1.1.0' in skills.tags_of(SID), f'{code} {r3}')

print('⑤ 병합 결과')
new = yaml.safe_load(text_at(f'{NEW}/kosoe-skill.yaml'))
expect('새 자리의 스킬: scope org · 본부 · share corp · owner 이름 · v1.1.0 · id 그대로',
       (new['id'], new['scope'], new['org'], new.get('share'), new['owner'], new['version']) == (SID, 'org', '금융영업본부', 'corp', '홍길동', '1.1.0'), new)
expect('내용(양식 · 고정 문구 · 규칙)은 그대로', new['rules'] == ['결론을 먼저 쓴다'] and new['blocks'][0]['text'].startswith('세부 일정') and new['forms'][0]['outline'][0] == '추진 배경')
expect('옛 개인 폴더는 지워진다', not gitutil.git('ls-tree', '-r', '--name-only', 'origin/main', '--', OLD, cwd=skills.REPO).strip())
moved = gitutil.git('show', f'origin/main:{NEW}/samples/main/01.webp', cwd=skills.REPO, binary=True)
expect('샘플 그림이 바이트 그대로 옮겨진다(SHA-256)', hashlib.sha256(moved).hexdigest() == hashlib.sha256(webp).hexdigest())
expect('SKILL.md에 「공개 범위」 줄', '공개 범위: 전사(금융영업본부)' in text_at(f'{NEW}/SKILL.md') and 'v1.0.0 → v1.1.0' in text_at(f'{NEW}/SKILL.md'))
expect('병합 뒤 작업 폴더에 옛 파일이 남지 않는다', git('status', '--porcelain') == '', git('status', '--porcelain'))
for uid, who in (('u5', '다른 본부 사람'), ('u2', '같은 본부 팀장')):
    login(uid)
    t = next((x for x in req('/api/templates')[1]['templates'] if x['id'] == f'{SID}:main'), None)
    expect(f'{who}에게 전사 카드로 보이고 샘플 1장이 붙는다', bool(t) and t['scope'] == 'corp' and t['dept'] == '금융영업본부' and t['samples']['files'] == ['01.webp'], t and (t['scope'], t['samples']))
    expect(f'{who}도 이제 샘플 그림을 본다', req(SURL, get=True)[0] == 200)

print('⑥ 올린 뒤의 변경 · 샘플 그림이 든 태그로 복구')
login('u1')
s = view(SID)
expect('올린 뒤: 범위 전사, 검수 요청 단추 없음, 처리 중 아님', s['scope'] == 'corp' and s['promote'] == [] and s['pending'] is False, (s['scope'], s['promote']))
code, d, _ = req(f'/api/skills/{SID}/change', {'rules': ['결론을 먼저 쓴다', '숫자에는 단위를 붙인다'], 'note': '규칙 추가'})
rc = d.get('request') or {}
expect('올린 뒤의 변경도 부서 → 전사 단계', code == 200 and rc.get('stages') == ['dept', 'corp'], f'{code} {d}')
login('u3'); decide(rc['id'])
login('u4'); code, rc2 = decide(rc['id'])
expect('변경 병합 → v1.2.0', code == 200 and rc2.get('stage') == 'done' and yaml.safe_load(text_at(f'{NEW}/kosoe-skill.yaml'))['version'] == '1.2.0', f'{code} {rc2}')
login('u1')
code, d, _ = req(f'/api/skills/{SID}/revert', {'tag': f'{SID}@v1.1.0'})
rv = d.get('request') or {}
expect('샘플 그림(바이너리)이 든 태그로 복구 요청이 열린다(500 아님)', code == 200 and rv.get('note', {}).get('version') == '1.2.1', f'{code} {d}')
login('u3'); decide(rv['id'])
login('u4'); code, rv2 = decide(rv['id'])
back = yaml.safe_load(text_at(f'{NEW}/kosoe-skill.yaml'))
expect('복구 병합 → v1.2.1, 규칙이 되돌아간다', code == 200 and rv2.get('stage') == 'done' and back['version'] == '1.2.1' and back['rules'] == ['결론을 먼저 쓴다'], back.get('rules'))
expect('복구 뒤에도 샘플 그림은 그대로', gitutil.git('show', f'origin/main:{NEW}/samples/main/01.webp', cwd=skills.REPO, binary=True) == webp)
login('u1')
code, d, _ = req(f'/api/skills/{SID}/revert', {'tag': f'{SID}@v1.0.0'})
expect('범위를 올리기 전 태그로는 복구할 수 없다(안내와 함께 400)', code == 400 and '찾지 못했습니다' in d.get('error', ''), f'{code} {d}')

print('⑦ 팀 팩 → 부서 팩, 그 뒤 하위 스킬')
login('u2')                                   # 김철수 팀장: 팀 팩(sales-pack)을 부서 팩으로
sp = view('sales-pack')
expect('팀 팩에는 부서 팩 단추가 열리고, 전사 팩은 부서 팩(sales-common)을 상속해 막힌다',
       [(p['target'], bool(p['why'])) for p in sp['promote']] == [('dept', False), ('corp', True)], sp['promote'])
code, d, _ = req('/api/skills/sales-pack/promote', {'target': 'dept'})
rs = d.get('request') or {}
expect('팀 팩 → 부서 팩 요청: 부서 관리자 한 단계', code == 200 and rs.get('stages') == ['dept'] and rs.get('path') == 'skills/org/금융영업본부/sales-pack', f'{code} {d}')
login('u3'); code, rs2 = decide(rs['id'])
sp2 = yaml.safe_load(text_at('skills/org/금융영업본부/sales-pack/kosoe-skill.yaml'))
expect('부서 관리자 승인 → 병합, 본부 폴더로 옮겨지고 팀 폴더는 지워진다',
       code == 200 and rs2.get('stage') == 'done' and sp2['org'] == '금융영업본부' and 'share' not in sp2
       and not gitutil.git('ls-tree', '-r', '--name-only', 'origin/main', '--', 'skills/org/금융영업본부/금융영업1팀/sales-pack', cwd=skills.REPO).strip(), f'{code} {sp2.get("org")}')
login('u1')
ch = {p['target']: p['why'] for p in view(CHILD)['promote']}
expect('상위 팩이 부서 팩이 되면 하위 개인 스킬도 부서 팩으로 올릴 수 있다(전사는 여전히 막힘)', ch.get('dept') == '' and 'sales-pack' in ch.get('corp', ''), ch)

print('⑧ 스킬 저장소 검사')
v = subprocess.run([sys.executable, os.path.join(skills.REPO, 'tools', 'validate.py')], cwd=skills.REPO, capture_output=True)
expect('병합 결과가 스킬 저장소 tools/validate.py 를 통과한다', v.returncode == 0, (v.stdout + v.stderr).decode('utf-8', 'replace')[-300:])
expect('작업 폴더가 main에서 깨끗하다', git('status', '--porcelain') == '' and git('rev-parse', '--abbrev-ref', 'HEAD') == 'main', git('status', '--porcelain'))

print(f'check_promote: {n[0] - len(fails)}/{n[0]} 통과' + ('' if not fails else ' — 실패: ' + ' / '.join(fails)))
sys.exit(1 if fails else 0)
