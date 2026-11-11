"""스킬 저장소에 쓰기 권한이 없으면 커밋 전에 막는가(네트워크로 쓰지 않는다).

    KOSOE_HOME=<시험 폴더> KOSOE_SKILLS_OFFLINE=1 python tests/check_skill_write_access.py

시험 폴더에 스킬 저장소 복제본이 있어야 한다(없으면 한 번 받아 온다). 실제 데이터 폴더(~/.kosoe)에 대고 돌리지 않는다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding='utf-8', errors='replace')
if not os.environ.get('KOSOE_HOME'):
    raise SystemExit('KOSOE_HOME을 시험 폴더로 주고 실행하세요(실제 데이터 폴더를 건드리지 않게)')
import skills  # noqa: E402

skills.ensure()
if not os.path.isdir(os.path.join(skills.REPO, '.git')):
    raise SystemExit(f'스킬 저장소 복제본이 없습니다: {skills.REPO} — {skills.STATE["error"]}')
skills.STATE['mode'] = 'github'
real_gh, calls = skills.gh, []


def fake_gh(*a, **k):                                   # 권한 없음 흉내(can_push가 부르는 이름)
    calls.append(a)
    return 'false' if a[:1] == ('api',) and 'permissions.push' in ' '.join(a) else real_gh(*a, **k)


skills.gh = fake_gh
skills.have_gh = lambda: True
assert skills.can_push(fresh=True) is False
before = skills.git('branch', '--list', cwd=skills.REPO)
head = skills.git('rev-parse', 'HEAD', cwd=skills.REPO)
try:
    skills.open_pr('new', {'scope': 'user', 'id': 't-write', 'version': '1.0.0', 'name': '시험'}, {}, '시험', '본문', 'scope:user')
    raise SystemExit('권한이 없으면 막혀야 한다')
except skills.NoWriteAccess as e:
    assert 'KOSOE_SKILLS_REPO' in str(e) and skills.SLUG in str(e), str(e)
    assert isinstance(e, skills.GitError)               # 앱의 오류 처리기가 더 가까운 NoWriteAccess 처리기를 고른다
assert skills.git('branch', '--list', cwd=skills.REPO) == before      # 로컬 브랜치를 만들지 않았다
assert skills.git('rev-parse', 'HEAD', cwd=skills.REPO) == head       # 커밋하지 않았다
try:
    skills.merge(1, 'x', 't-write', '1.0.0', '시험')
    raise SystemExit('승인(병합)도 막혀야 한다')
except skills.NoWriteAccess:
    pass
assert not any(a[:2] == ('pr', 'merge') for a in calls)                # gh pr merge를 부르지 않았다

# 권한 확인이 안 되면(None) 막지 않는다 — push 결과로 판단한다
skills.gh = lambda *a, **k: ''
assert skills.can_push(fresh=True) is None
# 로컬 모드는 원격에 쓰지 않으므로 늘 True
skills.STATE['mode'] = 'local'
assert skills.can_push() is True
print('check_skill_write_access OK')
