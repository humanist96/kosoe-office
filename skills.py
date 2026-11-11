"""스킬 저장소(kosoe-office-skills) — 정본은 Git, 포털 DB는 캐시.

- 스킬 1개 = 폴더 1개 = kosoe-skill.yaml 1개 (skills/org/<본부>[/<팀>]/<id>/, skills/user/<사용자>/<id>/)
- 상속: extends = [corp:<전사 스킬 id> ..., skill:<상위 스킬 id>] — 전사 → 본부 → 팀 → 개인 순으로 해석
- 잠금 키(registry/corp.lock.yaml locked_keys)는 하위 스킬이 바꿀 수 없다
- 등록·변경 요청 = 브랜치 + PR, 승인 = PR 승인 코멘트 + 병합 + 태그 <id>@v<버전>, 복구 = 이전 태그 내용으로 되돌리는 PR
"""
import copy
import json
import os
import re
import shutil
import threading
import time

import yaml

import checks
import corp
from core import CFG, HOME, FMT
from gitutil import GitError, gh, git, git_remote, have_gh, identity

REPO = os.path.join(HOME, 'skills-repo')
SLUG = CFG['skills_repo']
_lock = threading.RLock()
STATE = {'mode': 'none', 'url': '', 'head': '', 'synced': 0, 'error': ''}
_labels_done = []
LOCKED_TOP = {'brand', 'fonts', 'logo', 'grade_label', 'hwp_base'}
SEMVER = re.compile(r'^\d+\.\d+\.\d+$')


class NoWriteAccess(GitError):
    """스킬 저장소에 쓸 권한이 없다(읽기만 됨)."""


_push = {'v': None, 't': 0}


def can_push(fresh=False):
    """gh 계정이 스킬 저장소에 쓸 수 있는가: True / False / None(확인 못 함). 5분에 한 번 조회한다.
    clone·fetch 성공(STATE['mode'] == 'github')은 읽기 권한일 뿐이다."""
    if STATE['mode'] != 'github':
        return True                                  # 로컬 모드는 원격에 쓰지 않는다
    if not have_gh():
        return None
    if fresh or _push['v'] is None or time.time() - _push['t'] > 300:
        try:
            out = gh('api', f'repos/{SLUG}', '--jq', '.permissions.push', check=False, timeout=30).strip()
        except Exception:
            out = ''
        _push.update(v={'true': True, 'false': False}.get(out), t=time.time())   # 네트워크 오류 등은 None → 막지 않고 push 결과로 판단
    return _push['v']


def _need_push():
    if can_push(fresh=True) is False:
        who = identity().get('login') or '이 PC의 gh 계정'
        raise NoWriteAccess(f'GitHub 계정 {who}은(는) 스킬 저장소 {SLUG}에 쓰기 권한이 없어 등록·승인할 수 없습니다. '
                            '저장소 관리자에게 Write 권한을 요청하거나, .env의 KOSOE_SKILLS_REPO를 쓸 수 있는 저장소(예: 포크)로 '
                            '바꾸고 서버를 다시 시작하세요.')


def _norm_url(u):
    u = u.strip().lower().rstrip('/')
    return u[:-4] if u.endswith('.git') else u


def _same_repo_or_move():
    """복제본의 origin이 설정(KOSOE_SKILLS_REPO)과 다르면 옆으로 옮겨 두고 새로 받게 한다(지우지 않는다).
    .env만 바꾸면 화면에는 새 저장소 이름이 나오는데 실제로는 예전 저장소를 당기고 그쪽에 쓰게 되는 것을 막는다."""
    if CFG['skills_offline'] or not os.path.isdir(os.path.join(REPO, '.git')):
        return
    origin = _norm_url(git('remote', 'get-url', 'origin', cwd=REPO, check=False))
    if not origin.startswith('https://github.com/'):     # 주소를 못 읽었거나 시험용 로컬 원격이면 건드리지 않는다
        return
    if origin != _norm_url(f'https://github.com/{SLUG}'):
        moved = f"{REPO}.{time.strftime('%Y%m%d-%H%M%S')}"
        os.replace(REPO, moved)
        print(f'[skills] 스킬 저장소 설정이 바뀌어 예전 복제본을 옮겨 두었습니다: {moved}')


# ───────────── 동기화 ─────────────
def ensure(force=False, max_age=60):
    """로컬 복제본을 준비하고 원격 main을 당겨 온다(기본 60초에 한 번, force면 max_age초 이내 동기화는 건너뜀)."""
    with _lock:
        age = time.time() - STATE['synced']
        limit = max_age if (not force or max_age < 60) else 0
        if STATE['head'] and age < limit:
            return STATE
        try:
            _same_repo_or_move()
            if not os.path.isdir(os.path.join(REPO, '.git')):
                git_remote('clone', '-q', f'https://github.com/{SLUG}.git', REPO, timeout=300)
            elif not CFG['skills_offline']:
                git_remote('fetch', '-q', '--prune', '--tags', '--force', 'origin', cwd=REPO, timeout=120)
                git('checkout', '-q', '-f', 'main', cwd=REPO)
                git('reset', '-q', '--hard', 'origin/main', cwd=REPO)
            STATE.update(mode='github', url=f'https://github.com/{SLUG}', error='')
        except Exception as e:
            STATE.update(mode='local' if os.path.isdir(os.path.join(REPO, '.git')) else 'none', error=str(e)[:300])
        if os.path.isdir(os.path.join(REPO, '.git')):
            STATE['head'] = git('rev-parse', 'HEAD', cwd=REPO, check=False).strip()
            lk = os.path.join(REPO, 'registry', 'corp.lock.yaml')
            if os.path.exists(lk):
                corp.set_lock(yaml.safe_load(open(lk, encoding='utf-8')), STATE['head'])
        STATE['synced'] = time.time()
        return STATE


_vis = {'v': None, 't': 0}


def visibility():
    """스킬 저장소가 공개인지 — 'public' | 'private' | ''(알 수 없음). 등록 화면에서 무엇이 어디에 올라가는지 알릴 때 쓴다(10분에 한 번 조회)."""
    if _vis['v'] is None or time.time() - _vis['t'] > 600:
        v = ''
        if have_gh() and not CFG['skills_offline']:
            try:
                v = gh('repo', 'view', SLUG, '--json', 'visibility', '-q', '.visibility', timeout=20, check=False).strip().lower()
            except Exception:
                v = ''
        _vis.update(v=v if v in ('public', 'private', 'internal') else '', t=time.time())
    return _vis['v']


# ───────────── 읽기 ─────────────
def _load(p):
    d = yaml.safe_load(open(p, encoding='utf-8')) or {}
    d['_path'] = os.path.relpath(os.path.dirname(p), REPO).replace('\\', '/')
    return d


def all_skills():
    out = {}
    base = os.path.join(REPO, 'skills')
    for dp, dns, fns in os.walk(base):
        if 'kosoe-skill.yaml' in fns:
            try:
                s = _load(os.path.join(dp, 'kosoe-skill.yaml'))
                out[s['id']] = s
            except Exception:
                pass
    return out


def corp_forms():
    p = os.path.join(REPO, 'registry', 'corp.forms.yaml')
    return (yaml.safe_load(open(p, encoding='utf-8')) or {}).get('forms', []) if os.path.exists(p) else []


def tags_of(sid):
    out = git('tag', '-l', f'{sid}@v*', '--sort=-creatordate', cwd=REPO, check=False).splitlines()
    return [t for t in out if t]


def file_text(rel):
    p = os.path.join(REPO, *rel.split('/'))
    if not os.path.isfile(p):
        return ''
    try:
        return open(p, encoding='utf-8').read()
    except UnicodeDecodeError:                      # 복제형 스킬의 서식(.hwp) 같은 파일
        return f'(글이 아닌 파일입니다 — {os.path.getsize(p):,}바이트. 한글 서식 파일은 여기서 보여 주지 않습니다)'


def tree(sid):
    s = all_skills().get(sid)
    if not s:
        return []
    root = os.path.join(REPO, *s['_path'].split('/'))
    out = []
    for dp, dns, fns in os.walk(root):
        for f in sorted(fns):
            out.append(os.path.relpath(os.path.join(dp, f), REPO).replace('\\', '/'))
    return out


def history(sid, n=12):
    s = all_skills().get(sid)
    if not s:
        return []
    log = git('log', '-n', str(n), '--date=format:%m/%d %H:%M', '--pretty=%h\x1f%ad\x1f%an\x1f%s', '--', s['_path'], cwd=REPO, check=False)
    return [dict(zip(('sha', 't', 'who', 'msg'), l.split('\x1f'))) for l in log.splitlines() if l]


# ───────────── 상속 해석 ─────────────
def chain(sid, skills=None, _seen=None):
    """sid의 상속 사슬(위 → 아래). 전사 스킬은 'corp:<id>' 문자열로 들어간다."""
    skills = skills or all_skills()
    _seen = _seen or set()
    s = skills.get(sid)
    if not s or sid in _seen:
        return []
    _seen.add(sid)
    out = []
    for e in s.get('extends') or []:
        if str(e).startswith('skill:'):
            out += chain(e.split(':', 1)[1].split('@')[0], skills, _seen)
        elif str(e).startswith('corp:') and e not in out:
            out.append(e)
    out = list(dict.fromkeys([x for x in out if isinstance(x, str)] )) + [x for x in out if not isinstance(x, str)]
    return out + [s]


def resolve(sid, skills=None):
    """상속을 합쳐 실제로 쓰는 규칙 묶음과 해석 기록을 만든다."""
    skills = skills or all_skills()
    ch = chain(sid, skills)
    lk = corp.lock()
    corp_ids = []
    for x in ch:
        if isinstance(x, str):
            cid = x.split(':', 1)[1].split('#')[0]
            if cid not in corp_ids:
                corp_ids.append(cid)
    r = {'blocks': {}, 'glossary': {'terms': {}, 'banned': []}, 'checks': {'required': [], 'banned': []}, 'rules': [],
         'approval_line': ['담당', '팀장', '부서장'], 'illust_topics': [], 'forms': {}, 'grade': 'i'}
    levels = []
    for s in [x for x in ch if isinstance(x, dict)]:
        levels.append({'id': s['id'], 'name': s.get('name', s['id']), 'version': s.get('version', '0.0.0'), 'scope': s.get('scope'),
                       'org': s.get('org', ''), 'owner': s.get('owner', ''), 'path': s['_path']})
        for b in s.get('blocks') or []:
            r['blocks'][b.get('id') or b.get('heading')] = {**b, 'from': s['id']}
        g = s.get('glossary') or {}
        r['glossary']['terms'].update(g.get('terms') or {})
        r['glossary']['banned'] += [w for w in (g.get('banned') or []) if w not in r['glossary']['banned']]
        c = s.get('checks') or {}
        r['checks']['required'] += [w for w in (c.get('required') or []) if w not in r['checks']['required']]
        r['checks']['banned'] += [w for w in (c.get('banned') or []) if w not in r['checks']['banned']]
        r['rules'] += [x for x in (s.get('rules') or []) if x not in r['rules']]
        if s.get('approval_line'):
            r['approval_line'] = s['approval_line']
        r['illust_topics'] += [x for x in (s.get('illust_topics') or []) if x not in r['illust_topics']]
        for f in s.get('forms') or []:
            r['forms'][f['id']] = {**f, 'from': s['id']}
        if s.get('grade'):
            r['grade'] = s['grade']
        if s.get('style'):                      # 문체: 아래 스킬이 위를 덮는다(양식에 적힌 style이 가장 우선)
            r['style'] = s['style']
    r['resolution'] = {
        'corp': {cid: (lk['corp_skills'].get(cid) or {}).get('sha', '')[:7] for cid in corp_ids},
        'skills': [f"{l['id']}@{l['version']}" for l in levels],
        'repo_head': STATE['head'][:7],
    }
    r['levels'] = levels
    r['corp_ids'] = corp_ids
    return r


# ───────────── 검사 (저장소 CI와 같은 규칙) ─────────────
PII = [(re.compile(r'01[016-9]-?\d{3,4}-?\d{4}'), '휴대전화번호'), (re.compile(r'\d{6}-[1-4]\d{6}'), '주민등록번호'),
       (re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+'), '이메일'), (re.compile(r'(?<!\d)\d{3,6}-\d{2,6}-\d{2,8}(?!\d)'), '계좌번호')]


def validate_fill(fill, lk):
    """복제형 양식의 칸 정의(fill) 검사 → 오류 목록."""
    if fill is None:
        return []
    if not isinstance(fill, dict):
        return ['fill은 kind · engine · template · sections 를 가진 묶음이어야 함']
    errs = []
    if fill.get('kind') not in corp.FILL_KINDS:
        errs.append('fill.kind는 ' + ' | '.join(corp.FILL_KINDS))
    if fill.get('engine') not in lk['corp_skills']:
        errs.append(f"fill.engine이 잠금 파일에 없는 전사 스킬: {fill.get('engine')}")
    if not re.fullmatch(r'templates/[\w.\-]+\.(hwp|xlsx)', str(fill.get('template') or '')):
        errs.append('fill.template은 templates/<파일>.hwp')
    keys = [str(f.get('key') or '') for sec in fill.get('sections') or [] for f in sec.get('fields') or []]
    if not keys:
        errs.append('fill.sections에 칸이 없음')
    if any(not k or re.search(r'[{}.\t\n]', k) for k in keys):
        errs.append('칸 이름(key)에는 { } . 을 쓸 수 없음')
    if len(set(keys)) != len(keys):
        errs.append('같은 칸 이름(key)이 두 번 있음')
    return errs


def validate(s, skills=None):
    """오류 목록(비면 통과)."""
    errs = []
    for k in ('id', 'name', 'scope', 'version'):
        if not s.get(k):
            errs.append(f'필수 항목 없음: {k}')
    if s.get('version') and not SEMVER.match(str(s['version'])):
        errs.append('version은 1.2.3 형식')
    if s.get('scope') not in ('org', 'user'):
        errs.append('scope는 org 또는 user')
    bad = LOCKED_TOP & set(s.keys())
    if bad:
        errs.append(f"잠금 항목은 하위 스킬에서 바꿀 수 없음(전사 잠금): {', '.join(sorted(bad))}")
    lk = corp.lock()
    ext = s.get('extends') or []
    if not any(str(e).startswith('corp:') for e in ext) and not any(str(e).startswith('skill:') for e in ext):
        errs.append('extends에 전사 스킬(corp:) 또는 상위 스킬(skill:)이 하나 이상 필요')
    for e in ext:
        e = str(e)
        if e.startswith('corp:') and e.split(':', 1)[1].split('#')[0] not in lk['corp_skills']:
            errs.append(f'잠금 파일에 없는 전사 스킬: {e}')
        if e.startswith('skill:') and skills is not None and e.split(':', 1)[1].split('@')[0] not in skills:
            errs.append(f'없는 상위 스킬: {e}')
    for f in s.get('forms') or []:
        if f.get('fmt') not in FMT:
            errs.append(f"양식 {f.get('id')}: fmt는 hwp|ppt|web")
        if not f.get('outline'):
            errs.append(f"양식 {f.get('id')}: outline(장 구성) 없음")
        errs += [f"양식 {f.get('id')}: {e}" for e in checks.validate_style(f.get('style'))]
        errs += [f"양식 {f.get('id')}: {e}" for e in validate_fill(f.get('fill'), lk)]
    errs += checks.validate_style(s.get('style'))
    v = s.get('verification')
    if v is not None and not (isinstance(v, dict) and v.get('status') in ('passed', 'forced')):
        errs.append('verification.status는 passed | forced')
    text = json.dumps({k: v for k, v in s.items() if not k.startswith('_')}, ensure_ascii=False)
    for rx, name in PII:
        if rx.search(text):
            errs.append(f'보안: {name}로 보이는 값이 스킬에 남아 있음')
    return errs


# ───────────── 양식 카드(포털 갤러리용) ─────────────
def form_rows():
    """전사 양식 + 저장소 스킬의 양식 → templates 테이블 행."""
    rows = []
    for f in corp_forms():
        rows.append({'id': f['id'], 'name': f['name'], 'fmt': f['fmt'], 'use': f.get('use', '보고'), 'scope': 'corp',
                     'outline': f['outline'], 'desc': f.get('desc', ''), 'preset': f.get('preset', ''), 'grade': f.get('grade', 'i'),
                     'dept': '', 'team': '', 'owner': '전사', 'ver': '-', 'path': 'registry/corp.forms.yaml', 'tag': '',
                     'fields': [], 'rules': '', 'fixed': [], 'skill': {'id': '', 'corp': f.get('corp', '')}})
    # 서식 채우기형 스킬(목적별: 계약서·견적서 등) — 잠금 파일에 kind: hwp-fill · xlsx-fill 로 올라온 스킬의 form.yaml이 곧 전사 양식 카드
    for cid, c in corp.fill_skills():
        try:
            f = corp.form_of(cid)
        except Exception as e:
            print(f'[skills] 서식 채우기 스킬 {cid}의 form.yaml을 읽지 못함: {str(e)[:160]}')
            continue
        fmt = corp.fill_fmt(f)
        rows.append({'id': f.get('id') or cid, 'name': f.get('name') or cid, 'fmt': fmt, 'use': f.get('use', '견적' if fmt == 'xlsx' else '계약'), 'scope': 'corp',
                     'outline': [s.get('heading', '') for s in f.get('sections') or []], 'desc': f.get('purpose', ''), 'preset': '',
                     'grade': f.get('grade', 'i'), 'dept': '', 'team': '', 'owner': f.get('owner', '전사'), 'ver': '-',
                     'path': 'registry/corp.lock.yaml', 'tag': '', 'fields': [], 'rules': '', 'fixed': [],
                     'skill': {'id': '', 'corp': cid, 'fill': f, 'style': {'ending': 'any', 'date': 'any', 'max_len': 0}}})
    skills = all_skills()
    for sid, s in skills.items():
        r = resolve(sid, skills)
        org = (s.get('org') or '').split('/')
        dept, team = (org + ['', ''])[:2]
        scope = 'me' if s.get('scope') == 'user' else ('corp' if s.get('share') == 'corp' else ('team' if team else 'dept'))
        for f in s.get('forms') or []:
            if f.get('fill'):
                # 복제형 스킬: 대표 문서를 서식으로 삼아 칸만 채운다. 서식 파일은 이 스킬 폴더에, 칸 채우기 부품은 전사 스킬(engine)에 있다
                fill = {**f['fill'], 'name': f['fill'].get('name') or f['name']}
                rows.append({'id': f"{sid}:{f['id']}", 'name': f['name'], 'fmt': corp.fill_fmt(fill), 'use': f.get('use', '문서'), 'scope': scope,
                             'outline': f['outline'], 'desc': f.get('desc', s.get('name', '')), 'preset': '',
                             'grade': f.get('grade', r['grade']), 'dept': dept, 'team': team, 'owner': s.get('owner', ''),
                             'ver': s.get('version', ''), 'path': s['_path'], 'tag': (tags_of(sid) or [''])[0],
                             'fields': [], 'rules': '', 'fixed': [],
                             'skill': {'id': sid, 'name': s.get('name'), 'version': s.get('version'), 'chain': [l['id'] for l in r['levels']],
                                       'corp': r['corp_ids'], 'checks': {'required': [], 'banned': []}, 'glossary': {'terms': {}, 'banned': []},
                                       'fill': fill, 'fill_path': s['_path'], 'style': {'ending': 'any', 'date': 'any', 'max_len': 0},
                                       'verification': s.get('verification')}})
                continue
            fixed = [{'heading': b.get('heading', ''), 'text': b['text'], 'id': b.get('id', '')} for b in r['blocks'].values()
                     if not f.get('blocks') or b.get('id') in f['blocks']]
            rows.append({'id': f"{sid}:{f['id']}", 'name': f['name'], 'fmt': f['fmt'], 'use': f.get('use', '보고'), 'scope': scope,
                         'outline': f['outline'], 'desc': f.get('desc', s.get('name', '')), 'preset': f.get('preset', ''),
                         'grade': f.get('grade', r['grade']), 'dept': dept, 'team': team, 'owner': s.get('owner', ''),
                         'ver': s.get('version', ''), 'path': s['_path'], 'tag': (tags_of(sid) or [''])[0],
                         'fields': [], 'rules': '\n'.join(r['rules']), 'fixed': fixed,
                         'skill': {'id': sid, 'name': s.get('name'), 'version': s.get('version'), 'chain': [l['id'] for l in r['levels']],
                                   'corp': r['corp_ids'], 'checks': r['checks'], 'glossary': r['glossary'],
                                   'style': f.get('style') or r.get('style'), 'verification': s.get('verification')}})
    return rows


# ───────────── 쓰기: 브랜치 · PR · 병합 · 태그 ─────────────
def skill_dir(s):
    if s['scope'] == 'user':
        return f"skills/user/{s['owner']}/{s['id']}"
    return f"skills/org/{s['org']}/{s['id']}"


def dump_skill(s):
    body = {k: v for k, v in s.items() if not k.startswith('_')}
    return yaml.safe_dump(body, allow_unicode=True, sort_keys=False, width=1000)


def _commit_files(branch, files, message, requested_by):
    """origin/main에서 새 브랜치를 만들고 files({상대경로: 내용|None})를 커밋·푸시한다."""
    who = identity()
    git('checkout', '-q', '-f', '-B', branch, 'origin/main' if STATE['mode'] == 'github' else 'main', cwd=REPO)
    for rel, content in files.items():
        p = os.path.join(REPO, *rel.split('/'))
        if content is None:
            if os.path.exists(p):
                os.remove(p)
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if isinstance(content, bytes):              # 복제형 스킬의 서식 파일(.hwp)
            with open(p, 'wb') as f:
                f.write(content)
            continue
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
    git('add', '-A', cwd=REPO)
    git('-c', f"user.name={who['name']}", '-c', f"user.email={who['email']}", 'commit', '-q', '-m',
        f'{message}\n\nRequested-by: {requested_by}', cwd=REPO)
    if STATE['mode'] == 'github':
        git_remote('push', '-q', '-f', '-u', 'origin', branch, cwd=REPO, timeout=180)


def open_pr(kind, s, files, requested_by, body, scope_label):
    """kind: new | update | revert. 돌려주는 값: {'branch','pr','url'}."""
    with _lock:
        ensure(force=True, max_age=20)
        _need_push()                                   # 커밋 전에 막아 로컬 브랜치를 남기지 않는다
        branch = f"skill/{s['scope']}/{s['id']}/v{s['version']}"
        title = {'new': '스킬 등록', 'update': '스킬 변경', 'revert': '스킬 복구'}[kind] + f": {s['name']} v{s['version']}"
        try:
            _commit_files(branch, files, f"skill({s['scope']}): {s['id']} v{s['version']} — {title}", requested_by)
            if STATE['mode'] != 'github' or not have_gh():
                return {'branch': branch, 'pr': 0, 'url': ''}
            if not _labels_done:
                for name, color in (('scope:user', '1D76DB'), ('scope:org', 'F26522')):
                    gh('label', 'create', name, '--color', color, '-R', SLUG, check=False)
                _labels_done.append(1)
            url = gh('pr', 'create', '-R', SLUG, '--base', 'main', '--head', branch, '--label', scope_label,
                     '--title', title, '--body', body, timeout=120).strip().splitlines()[-1]
            return {'branch': branch, 'pr': int(url.rstrip('/').split('/')[-1]), 'url': url}
        except Exception:                              # 실패한 시도의 로컬 브랜치를 치우고 그대로 던진다
            git('checkout', '-q', '-f', 'main', cwd=REPO, check=False)
            git('branch', '-D', branch, cwd=REPO, check=False)
            raise
        finally:
            git('checkout', '-q', '-f', 'main', cwd=REPO, check=False)


def _bg(fn, *a):
    threading.Thread(target=fn, args=a, daemon=True).start()


def comment(pr, text, wait=False):
    """PR 코멘트(승인 기록). 기본은 뒤에서 보낸다(화면을 기다리게 하지 않음)."""
    if pr and STATE['mode'] == 'github':
        f = lambda: gh('pr', 'comment', str(pr), '-R', SLUG, '--body', text, check=False)
        f() if wait else _bg(f)


def merge(pr, branch, sid, version, approved_by):
    """승인 → 병합 + 태그. 돌려주는 값: 태그."""
    tag = f'{sid}@v{version}'
    with _lock:
        if STATE['mode'] == 'github' and pr:
            _need_push()
            gh('pr', 'merge', str(pr), '-R', SLUG, '--merge', '--delete-branch', timeout=180)
            ensure(force=True)
        else:
            git('checkout', '-q', 'main', cwd=REPO)
            git('merge', '-q', '--no-ff', '-m', f'merge {branch}', branch, cwd=REPO)
        who = identity()
        git('-c', f"user.name={who['name']}", '-c', f"user.email={who['email']}", 'tag', '-f', '-a', tag, '-m',
            f'{tag}\n\nApproved-by: {approved_by}', cwd=REPO)
        if STATE['mode'] == 'github':
            git_remote('push', '-q', '-f', 'origin', tag, cwd=REPO, timeout=120, check=False)
        STATE['synced'] = 0
        ensure(force=True)
        return tag


def close(pr, reason):
    if pr and STATE['mode'] == 'github':
        gh('pr', 'close', str(pr), '-R', SLUG, '--comment', f'반려: {reason}', '--delete-branch', check=False)


def files_at(tag, path):
    """태그 시점의 스킬 폴더 내용 {상대경로: 텍스트}. 글이 아닌 파일(복제형 스킬의 서식 .hwp)은 bytes 그대로."""
    names = git('-c', 'core.quotepath=false', 'ls-tree', '-r', '--name-only', tag, '--', path, cwd=REPO, check=False).splitlines()
    out = {}
    for n in names:
        if n:
            data = git('show', f'{tag}:{n}', cwd=REPO, binary=True)
            try:
                out[n] = data.decode('utf-8')
            except UnicodeDecodeError:
                out[n] = data
    return out


def fresh_file(rel, dest):
    """스킬 저장소(main)의 파일을 git 객체에서 꺼내 dest 폴더에 쓴다 — 복제형 스킬의 서식.
    작업 폴더의 파일을 직접 쓰지 않는다(사내 보호 도구가 디스크의 .hwp를 암호화해 두었을 수 있다)."""
    data = git('show', f'main:{rel}', cwd=REPO, binary=True)
    os.makedirs(dest, exist_ok=True)
    p = os.path.join(dest, os.path.basename(rel))
    with open(p, 'wb') as f:
        f.write(data)
    return p


def bump(v, part='minor'):
    a, b, c = (int(x) for x in str(v).split('.'))
    return f'{a}.{b + 1}.0' if part == 'minor' else f'{a}.{b}.{c + 1}'


def demo_cleanup(user_skills=False):
    """시연 초기화: 열린 PR을 닫는다. user_skills=True면 시연 중 만든 개인 스킬 폴더(skills/user/*)를
    새 커밋으로 지운다(이력·태그는 남음)."""
    with _lock:
        if STATE['mode'] == 'github' and have_gh():
            out = gh('pr', 'list', '-R', SLUG, '--state', 'open', '--json', 'number', '-q', '.[].number', check=False)
            for n in out.split():
                gh('pr', 'close', n, '-R', SLUG, '--comment', '시연 초기화로 닫음', '--delete-branch', check=False)
        STATE['synced'] = 0
        ensure(force=True)
        if user_skills:
            base = os.path.join(REPO, 'skills', 'user')
            gone = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))] if os.path.isdir(base) else []
            if gone:
                for d in gone:
                    shutil.rmtree(os.path.join(base, d), ignore_errors=True)
                open(os.path.join(base, '.gitkeep'), 'a').close()
                who = identity()
                git('add', '-A', cwd=REPO)
                git('-c', f"user.name={who['name']}", '-c', f"user.email={who['email']}", 'commit', '-q', '-m',
                    f"시연 초기화: 개인 스킬 정리 ({', '.join(gone)})", cwd=REPO, check=False)
                if STATE['mode'] == 'github':
                    git_remote('push', '-q', 'origin', 'HEAD:main', cwd=REPO, timeout=120, check=False)
                STATE['synced'] = 0
                ensure(force=True)
