"""시험용 데이터 폴더 만들기 — GitHub에 쓰지 않는 격리된 KOSOE_HOME.

    python tests/make_local_home.py [폴더]        (기본 tests/_home_clone)

이 PC의 실제 데이터 폴더(~/.kosoe)에서 전사 스킬 캐시(corp)와 스킬 저장소 복제본(skills-repo)을 복사하고,
복사한 스킬 저장소의 원격(origin)을 그 폴더 안의 origin.git(이 PC의 사본)으로 바꾼다.
그래서 시험에서 만드는 브랜치 · 병합 · 태그는 origin.git에만 쌓인다. 실제 ~/.kosoe 와 GitHub는 건드리지 않는다.
앱 모듈을 불러오지 않는다(KOSOE_HOME을 정하기 전에 써야 하므로).
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(ROOT, 'tests', '_home_clone')


def _git(*a, cwd=None):
    r = subprocess.run(['git', '-c', 'core.quotepath=false', *a], cwd=cwd, capture_output=True)
    if r.returncode != 0:
        raise SystemExit('git ' + ' '.join(a[:3]) + ' 실패: ' + (r.stdout + r.stderr).decode('utf-8', 'replace')[-300:])
    return r.stdout.decode('utf-8', 'replace').strip()


def ensure(home=DEFAULT, source=None):
    """home에 시험용 데이터 폴더가 없으면 만든다. 돌려주는 값: 스킬 저장소 원격(이 PC의 사본) 경로."""
    home = os.path.abspath(home)
    repo, origin = os.path.join(home, 'skills-repo'), os.path.join(home, 'origin.git')
    if os.path.isdir(os.path.join(repo, '.git')):
        return _git('remote', 'get-url', 'origin', cwd=repo)
    source = os.path.abspath(source or os.path.expanduser(os.path.join('~', '.kosoe')))
    if os.path.normcase(source) == os.path.normcase(home):
        raise SystemExit('시험용 폴더와 실제 데이터 폴더가 같습니다 — 다른 폴더를 지정하세요')
    for d in ('corp', 'skills-repo'):
        if not os.path.isdir(os.path.join(source, d)):
            raise SystemExit(f'{source} 에 {d} 폴더가 없습니다 — 앱을 한 번 실행해(python kosoe.py doctor) 전사 스킬과 스킬 저장소를 받아 둔 뒤 다시 하세요')
    os.makedirs(home, exist_ok=True)
    print(f'시험용 데이터 폴더를 만듭니다: {home}  (원본 {source} 는 읽기만 합니다)')
    for d in ('corp', 'skills-repo'):
        shutil.copytree(os.path.join(source, d), os.path.join(home, d), symlinks=True)
    _git('checkout', '-q', '-f', 'main', cwd=repo)
    _git('clone', '-q', '--bare', repo, origin)
    _git('remote', 'set-url', 'origin', origin.replace('\\', '/'), cwd=repo)
    return origin.replace('\\', '/')


if __name__ == '__main__':
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding='utf-8', errors='replace')
    print('스킬 저장소 원격(이 PC의 사본):', ensure(sys.argv[1] if len(sys.argv) > 1 else DEFAULT))
