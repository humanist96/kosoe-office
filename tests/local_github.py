"""시험·시연 연습용: GitHub 대신 이 PC의 사본 저장소(origin.git)를 쓰게 한다.

    import local_github; local_github.install()      # app · skills 를 불러온 뒤에

- 스킬 저장소의 원격(origin)이 GitHub이면 멈춘다(실수로 올리지 않도록).
- gh의 PR 만들기·병합을 흉내 낸다: 만들기 = 번호만 매김, 병합 = origin의 main에 병합해 올림. 나머지 gh 호출은 아무 일도 하지 않는다.
"""
import os

import gitutil
import skills

PRS = {}


def origin():
    return gitutil.git('remote', 'get-url', 'origin', cwd=skills.REPO).strip()


def fake_gh(*a, **k):
    if a[:2] == ('pr', 'create'):
        n = len(PRS) + 1
        PRS[n] = a[a.index('--head') + 1]
        return f'https://example.invalid/local-pr/{n}\n'
    if a[:2] == ('pr', 'merge'):
        b = PRS[int(a[2])]
        g = lambda *x: gitutil.git(*x, cwd=skills.REPO)
        g('fetch', '-q', 'origin')
        g('checkout', '-q', '-f', '-B', 'main', 'origin/main')
        g('-c', 'user.name=local-test', '-c', 'user.email=local-test@example.invalid', 'merge', '-q', '--no-ff', '-m', f'merge {b}', f'origin/{b}')
        g('push', '-q', 'origin', 'main')
        return ''
    return ''


def install():
    o = origin()
    if 'github.com' in o or not os.path.isdir(o):
        raise SystemExit(f'스킬 저장소의 원격이 이 PC의 사본이 아닙니다: {o} — GitHub에 쓰지 않도록 멈춥니다')
    skills.gh = fake_gh
    skills.have_gh = lambda: True
    gitutil._who.update(name='local-test', email='local-test@example.invalid', login='local-test')
    return o
