"""코쇠오피스 — 각자 PC에서 실행하는 클라이언트 (Flask · SQLite · Claude Code 구독 CLI · 전사 공용 스킬 · Git 스킬 저장소).

실행: python app.py  →  http://localhost:8810
"""
import json
import mimetypes
import os
import re
import secrets
import unicodedata
from shutil import which as shutil_which
import subprocess
import sys
import threading
import time
from functools import wraps

import yaml
from flask import Flask, abort, g, has_request_context, jsonify, request, send_file, send_from_directory, session

import checks
import clone
import core
import corp
import doc_themes
import engines
import extract
import fillform
import llm
import skills
from core import CFG, DATA, FMT, GRADE, ROLE, db, now, row, rows


def log(who, what):
    """요청 안에서는 같은 연결로 기록한다(따로 열면 쓰기 잠금에 걸린다)."""
    if has_request_context() and 'con' in g:
        g.con.execute('insert into events(t,who,what) values(?,?,?)', (now(), who, what))
    else:
        core.log(who, what)


app = Flask(__name__, static_folder=None)
mimetypes.add_type('application/wasm', '.wasm')      # rhwp(WASM) 스트리밍 초기화에 필요
_sk = os.path.join(DATA, 'secret.key')
if not os.path.exists(_sk):
    open(_sk, 'w').write(secrets.token_hex(32))
app.secret_key = open(_sk).read().strip()
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024
UP = os.path.join(DATA, 'uploads')
os.makedirs(UP, exist_ok=True)
STATIC = os.path.join(core.ROOT, 'static')
MANUAL_MIN = {'hwp': 90, 'ppt': 180, 'web': 150, 'xlsx': 40}   # 손으로 만들 때 걸리는 시간(분, 가정)
SCOPE_STAGES = {'me': ['ci'], 'team': ['lead'], 'dept': ['dept'], 'corp': ['dept', 'corp']}   # 전사 팩: 부서 관리자 검수 → 전사 관리자 승인
STAGE_NAME = {'ci': '자동 검사', 'lead': '팀장 승인', 'dept': '부서 관리자 승인', 'corp': '전사 관리자 승인', 'done': '등록 완료', 'rejected': '반려'}
KIND_NAME = {'new': '스킬 등록', 'update': '스킬 변경', 'revert': '스킬 복구', 'promote': '검수 요청(범위 올리기)'}
SCOPE_NAME = {'me': '개인', 'team': '팀', 'dept': '부서', 'corp': '전사'}
SCOPE_RANK = {'me': 0, 'team': 1, 'dept': 2, 'corp': 3}


# ───────────── 공통 ─────────────
@app.before_request
def _open():
    g.con = db()


@app.teardown_request
def _close(exc):
    c = g.pop('con', None)
    if c:
        c.commit()
        c.close()


def ok(**k):
    return jsonify({'ok': True, **k})


def err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


def login_required(f):
    @wraps(f)
    def w(*a, **k):
        uid = session.get('uid')
        u = core.get_user(g.con, uid) if uid else None
        if not u:
            return err('로그인이 필요합니다', 401)
        g.u = u
        g.net = u['net'] if (u['net'] == 'closed' or core.inet_active(g.con, u['id'])) else 'closed'
        return f(*a, **k)
    return w


def J(s, d=None):
    try:
        return json.loads(s) if s else d
    except Exception:
        return d


def ai_ctx(fast=False):
    """망 구분에 따른 AI 사용 방식. 인터넷망 = 외부 AI + 마스킹, 폐쇄망 = 사내 모델 자리(시연: 같은 구독 CLI 또는 규칙)."""
    pol = J(row(g.con, "select v from policy where k='mask'")['v'], [])
    if g.net == 'internet':
        return {'use_llm': True, 'label': f"{llm.display()} (인터넷망 · 마스킹)", 'mk': llm.Masker(pol), 'fast': fast}
    if CFG['closed_llm'] == 'rule':
        return {'use_llm': False}
    if llm.external():
        # 시연: 사내에 올릴 모델을 외부 API로 대신 부른다 → 요청이 밖으로 나가므로 망 모드와 관계없이 가린다
        return {'use_llm': True, 'label': '사내 LLM 자리 (시연: ' + llm.display() + ' · 마스킹)', 'mk': llm.Masker(pol), 'fast': fast}
    return {'use_llm': True, 'label': '사내 LLM 자리 (시연: ' + llm.display() + ')', 'mk': None, 'fast': fast}


def ai_state():
    st = llm.state()
    cur = next((p for p in st['providers'] if p['kind'] == st['kind']), {})
    return {'connected': st['connected'], 'model': st['display'], 'kind': st['kind'], 'closed': CFG['closed_llm'],
            'detail': cur.get('detail', ''), 'external': llm.external()}


def load_ai_choice():
    """이 PC에서 마지막으로 고른 AI 제공자를 되살린다(없으면 .env의 KOSOE_AI)."""
    con = db()
    r = row(con, "select v from policy where k='ai'")
    con.close()
    c = J(r['v'], {}) if r else {}
    models = dict(c.get('models') or {})
    if c.get('or_model'):                       # 이전 저장 형식
        models.setdefault('openrouter', c['or_model'])
    keep = llm.provider()
    for k, m in models.items():                 # 외부 API별로 고른 모델(목록에서 빠졌으면 건너뜀)
        try:
            llm.set_provider(k, m)
        except Exception:
            pass
    try:
        llm.set_provider(c.get('kind') or keep)
    except Exception:
        llm.set_provider(keep)


def people_of(u):
    lead = core.lead_of(g.con, u['team'])
    head = row(g.con, "select * from users where dept=? and role='deptAdmin'", u['dept'])
    fmt = lambda x: f"{x['name']} {x['title']}" if x else ''
    return {'담당': fmt(u), '팀장': fmt(lead), '부서장': fmt(head), 'dept': u['team']}


# ───────────── 양식(스킬 저장소 → 갤러리) ─────────────
_sync_lock = threading.Lock()


def sync_forms(force=False, max_age=60):
    """스킬 저장소를 당겨 와 양식 카드 캐시(templates 테이블)를 다시 만든다."""
    with _sync_lock:
        st = skills.ensure(force=force, max_age=max_age)
        if not skills.STATE['head']:
            return st
        con = db()
        uses = {r['template_id']: r['n'] for r in rows(con, 'select * from uses')}
        con.execute('delete from templates')
        for f in skills.form_rows():
            con.execute('insert into templates values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (f['id'], f['name'], f['fmt'], f['use'], f['scope'], json.dumps(f['outline'], ensure_ascii=False), f['desc'],
                         f['preset'], f['grade'], f['dept'], f['team'], f['owner'], uses.get(f['id'], 0), f['ver'], f['path'], f['tag'],
                         '[]', f['rules'], json.dumps(f['fixed'], ensure_ascii=False), '', now(), json.dumps(f['skill'], ensure_ascii=False)))
        con.commit()
        con.close()
        return st


def tpl_view(t, u):
    o = dict(t)
    o['outline'] = J(t['outline'], [])
    o['fixed'] = J(t['fixed'], [])
    info = J(t['skill'], {}) or {}
    o['skill_info'] = info
    if info.get('id'):
        up = list(reversed((info.get('chain') or [])[:-1])) + ['전사']
        o['skill'] = f"{info['id']}@{info.get('version', '')} ← " + ' ← '.join(up)
    else:
        e = engines.fill_engine(engines.fill_cid(info)) if info.get('fill') else engines.engine_of(t['fmt'])
        o['skill'] = f"전사 {e['name']}@{e['sha']}"
    o['usable'] = core.can_use_template(t, u, g.net)
    o['blocked'] = '대외비 양식은 인터넷망에서 쓸 수 없습니다' if g.net == 'internet' and t['grade'] == 'c' else ''
    return o


SAMPLE_EXT = ('.webp', '.png', '.jpg', '.jpeg', '.svg')


def _sample_dir(t):
    """양식 카드의 샘플 그림 폴더(스킬 저장소): 전사 양식 = registry/samples/<id>/, 스킬 양식 = 그 스킬 폴더의 samples/<양식 id>/."""
    if t['path'].startswith('registry/'):      # corp.forms.yaml 의 전사 양식 · corp.lock.yaml 의 서식 채우기형 전사 스킬
        return os.path.join(skills.REPO, 'registry', 'samples', t['id'])
    return os.path.join(skills.REPO, *t['path'].split('/'), 'samples', t['id'].split(':', 1)[-1])


def _sample_files(d):
    return sorted(f for f in os.listdir(d) if f.lower().endswith(SAMPLE_EXT)) if os.path.isdir(d) else []


def samples_of(t, corp_forms):
    """카드를 누르면 보일 샘플: 자기 샘플 → 같은 형식·서식(preset)의 전사 샘플 → 같은 형식의 다른 전사 샘플.
    돌려주는 값 {'src': 그림을 가진 양식 id, 'from': 빌려 온 전사 양식 이름(자기 것이면 ''), 'files': [...]}"""
    fs = _sample_files(_sample_dir(t))
    if fs or (J(t['skill'], {}) or {}).get('fill'):      # 서식 채우기형은 모양이 정해져 있어 다른 양식의 샘플을 빌리지 않는다
        return {'src': t['id'], 'from': '', 'files': fs}
    for c in sorted((c for c in corp_forms if c['fmt'] == t['fmt'] and c['id'] != t['id']), key=lambda c: c['preset'] != t['preset']):
        fs = _sample_files(_sample_dir(c))
        if fs:
            return {'src': c['id'], 'from': c['name'], 'files': fs}
    return {'src': t['id'], 'from': '', 'files': []}


def _visible(t, u):
    return (t['scope'] == 'corp' or u['role'] == 'corpAdmin' or (t['scope'] == 'dept' and t['dept'] == u['dept'])
            or (t['scope'] == 'team' and t['team'] == u['team']) or (t['scope'] == 'me' and t['owner'] == u['id']))


def visible_templates(u):
    allt = rows(g.con, 'select * from templates order by uses desc, scope desc')
    corp_forms = [t for t in allt if t['path'] == 'registry/corp.forms.yaml']
    return [{**tpl_view(t, u), 'samples': samples_of(t, corp_forms)} for t in allt if _visible(t, u)]


def template_for_render(t):
    """엔진에 넘길 양식 정보 + 해석된 스킬 사슬."""
    info = J(t['skill'], {}) or {}
    chain = info.get('chain') or []
    return {**t, 'chain_names': [f'전사 {c}' for c in (info.get('corp') or [])[:1]] + chain[-2:]}


def doc_view(d, u, full=False):
    o = {k: d[k] for k in ('id', 'title', 'template_id', 'fmt', 'grade', 'ver', 'created', 'updated')}
    own = core.get_user(g.con, d['owner'])
    o['owner'] = {'id': own['id'], 'name': own['name'], 'team': own['team']} if own else {}
    o['perm'] = core.doc_perm(d, u)
    o['acl'] = J(d['acl'], [])
    t = row(g.con, 'select name from templates where id=?', d['template_id'])
    o['template'] = t['name'] if t else d['template_id']
    o['locked'] = g.net == 'internet' and d['grade'] == 'c'
    fs = rows(g.con, 'select * from doc_files where doc_id=? order by ver desc, created desc', d['id'])
    o['files'] = [{'ver': f['ver'], 'fmt': f['fmt'], 'checks': J(f['checks'], []), 'warns': J(f['warns'], []), 'ms': f['elapsed_ms'],
                   'llm': J(f['llm'], {}), 'created': f['created'], 'size': os.path.getsize(f['path']) if os.path.exists(f['path']) else 0,
                   'resolution': J(f['resolution'], {}), 'shots': _shots(d['id'], f['ver']) if f['fmt'] == 'ppt' else []} for f in fs]
    if full:
        o['blueprint'] = J(d['blueprint'], {})
        o['made'] = J(d['made'], {})
        o['skill_update'] = _skill_update(d, fs)
    return o


def _skill_update(d, fs):
    """문서를 만들 때 쓴 스킬 버전보다 승인된 새 버전이 있으면 알려 준다(다음 문서부터 반영 → 이 문서는 다시 만들면 반영)."""
    t = row(g.con, 'select skill from templates where id=?', d['template_id'])
    info = (J(t['skill'], {}) or {}) if t else {}
    if not info.get('id') or not fs:
        return None
    last = J(fs[0]['resolution'], {}).get('skills') or []
    used = next((x.split('@', 1)[1] for x in last if x.startswith(info['id'] + '@')), '')
    if used and used != info.get('version'):
        return {'id': info['id'], 'name': info.get('name') or info['id'], 'used': used, 'current': info.get('version')}
    return None


def _shots(doc_id, ver):
    d = os.path.join(engines.OUT, doc_id, f'v{ver}_shots')
    return sorted(os.listdir(d), key=lambda n: int(re.sub(r'\D', '', n) or 0)) if os.path.isdir(d) else []


def _svg_shots(doc_id, ver):
    """셰브론 엔진이 만든 장별 SVG(같은 디자인 원본)를 미리보기 그림으로 쓴다 — PowerPoint가 없는 PC(macOS 등)."""
    import shutil
    src = os.path.join(engines.job_dir(doc_id, ver), 'ppt', 'svg_output')
    if not os.path.isdir(src):
        return False
    dst = os.path.join(engines.OUT, doc_id, f'v{ver}_shots')
    os.makedirs(dst, exist_ok=True)
    for i, f in enumerate(sorted(x for x in os.listdir(src) if x.endswith('.svg')), 1):
        shutil.copy(os.path.join(src, f), os.path.join(dst, f's{i}.svg'))
    return True


def ppt_shots(path, doc_id, ver):
    """미리보기: Windows + PowerPoint면 실제 PPTX를 PNG로 내보내고(백그라운드), 아니면 장별 SVG를 쓴다."""
    if os.name != 'nt' or not shutil_which('powershell'):
        _svg_shots(doc_id, ver)
        return
    dst = os.path.join(engines.OUT, doc_id, f'v{ver}_shots')
    tmp = dst + '_tmp'
    os.makedirs(tmp, exist_ok=True)
    ps = (f"$pp = New-Object -ComObject PowerPoint.Application; $p = $pp.Presentations.Open('{path}', $true, $false, $false); "
          f"$i=1; foreach ($s in $p.Slides) {{ $s.Export('{tmp}\\s' + $i + '.png', 'PNG', 1280, 720); $i++ }}; $p.Close(); $pp.Quit()")
    try:
        subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True, timeout=120)
        if os.listdir(tmp):
            if os.path.isdir(dst):
                import shutil
                shutil.rmtree(dst, ignore_errors=True)
            os.replace(tmp, dst)
            return
    except Exception:
        pass
    _svg_shots(doc_id, ver)                 # PowerPoint가 없거나 실패하면 SVG로


# ───────────── 정적 ─────────────
@app.get('/')
def index():
    return send_from_directory(STATIC, 'index.html')


@app.get('/static/<path:p>')
def static_file(p):
    return send_from_directory(STATIC, p)


# ───────────── 로그인 · 상태 ─────────────
@app.get('/api/personas')
def personas():
    return ok(users=[{**u, 'role_name': ROLE[u['role']]} for u in rows(g.con, 'select * from users')])


@app.post('/api/login')
def login():
    u = core.get_user(g.con, (request.json or {}).get('uid'))
    if not u:
        return err('없는 사용자')
    session['uid'] = u['id']
    log(u['name'], '로그인 (SSO 시연: 가상 사용자 선택)')
    return ok()


@app.post('/api/logout')
def logout():
    session.clear()
    return ok()


def _pending(u):
    n = 0
    for r in rows(g.con, "select * from requests where stage in ('lead','dept','corp')"):
        if _approver_ok(r, u):
            n += 1
    if u['role'] == 'lead':
        n += len(rows(g.con, "select id from ireq where status='wait' and team=? and uid<>?", u['team'], u['id']))
    if u['role'] == 'security':
        n += len(rows(g.con, "select i.id from ireq i join users x on x.id=i.uid where i.status='wait' and x.role in ('lead','deptAdmin','corpAdmin')"))
    return n


@app.get('/api/me')
@login_required
def me():
    u = g.u
    return ok(user={**u, 'role_name': ROLE[u['role']]}, net=g.net, inet=core.inet_active(g.con, u['id']), pending=_pending(u),
              ai=ai_state(), hwp=engines.hwp_ready(),
              repo={'mode': skills.STATE['mode'], 'url': skills.STATE['url'], 'head': skills.STATE['head'][:7], 'error': skills.STATE['error']})


@app.post('/api/net')
@login_required
def set_net():
    want = (request.json or {}).get('net')
    if want == 'internet' and not core.inet_active(g.con, g.u['id']):
        return err('인터넷망은 팀장 승인을 받은 기간에만 쓸 수 있습니다. [인터넷 사용 신청]에서 신청해 주세요.', 403)
    g.con.execute('update users set net=? where id=?', (want if want in ('closed', 'internet') else 'closed', g.u['id']))
    log(g.u['name'], f"망 전환 → {'인터넷망' if want == 'internet' else '폐쇄망'}")
    return ok()


@app.get('/api/ai')
@login_required
def ai_get():
    return ok(ai=llm.state(), usage=llm.usage(), closed=CFG['closed_llm'])


@app.post('/api/ai')
@login_required
def ai_set():
    """AI 제공자 바꾸기(이 PC 설정). 예: Claude Code CLI ↔ NVIDIA API · OpenRouter(DeepSeek)."""
    b = request.json or {}
    try:
        st = llm.set_provider(b.get('kind'), b.get('model') or b.get('or_model') or '')
    except ValueError as e:
        return err(str(e))
    g.con.execute("insert into policy(k,v) values('ai',?) on conflict(k) do update set v=excluded.v",
                  (json.dumps({'kind': st['kind'], 'models': llm.chosen_models()}, ensure_ascii=False),))
    log(g.u['name'], f"AI 전환 → {st['display']}" + ('' if st['connected'] else ' (연결 안 됨 — 규칙 기반으로 동작)'))
    return ok(ai=st)


@app.post('/api/ai/ping')
@login_required
def ai_ping():
    p = llm.ping()
    if p.get('ok'):
        log(g.u['name'], f"AI 연결 시험 — {p['model']} {p['ms']}ms")
    return ok(ping=p, usage=llm.usage())


@app.get('/api/doc-themes')
@login_required
def doc_theme_list():
    """PPT·웹슬라이드를 만들 때 고르는 디자인 테마 9가지."""
    return ok(themes=doc_themes.listing(), default=doc_themes.DEFAULT)


@app.get('/api/health')
def health():
    p = llm.ping() if request.args.get('ping') else {'ok': llm.available(), 'error': ai_state()['detail']}
    return ok(ai=p, hwp=engines.hwp_ready(), repo=skills.STATE, model=llm.display(), kind=llm.provider(), corp=corp.status())


# ───────────── 양식 ─────────────
@app.get('/api/templates')
@login_required
def templates():
    return ok(templates=visible_templates(g.u))


@app.get('/api/samples/<tid>/<name>')
@login_required
def template_sample(tid, name):
    """양식 카드 샘플 그림(스킬 저장소의 그 양식 샘플 폴더 안 파일만). 그 양식을 볼 수 있는 사람과, 그 스킬의 검수 요청을 지금 승인할 사람이 본다."""
    t = row(g.con, 'select * from templates where id=?', tid)
    pend = _open_request(tid.split(':', 1)[0]) if t and ':' in tid else None
    if not t or not (_visible(t, g.u) or (pend and _approver_ok(pend, g.u))) or name not in _sample_files(_sample_dir(t)):
        abort(404)
    r = send_from_directory(_sample_dir(t), name)
    r.headers['Cache-Control'] = 'max-age=3600'
    return r


@app.post('/api/route')
@login_required
def route():
    text = (request.json or {}).get('text', '')
    ts = [t for t in visible_templates(g.u) if t['usable']]
    raw = [row(g.con, 'select * from templates where id=?', t['id']) for t in ts]
    out, meta = llm.route(text, raw, ai_ctx(fast=True))
    return ok(suggest=out, meta=meta)


# ───────────── 첨부 ─────────────
@app.post('/api/upload')
@login_required
def upload():
    f = request.files.get('file')
    if not f or not f.filename:
        return err('파일이 없습니다')
    uid = core.new_id('f')
    name = unicodedata.normalize('NFC', os.path.basename(f.filename))      # macOS 파일명(한글 자모 분리) 정리
    path = os.path.join(UP, uid + '_' + re.sub(r'[^\w.\-가-힣]', '_', name))
    f.save(path)
    try:
        r = extract.read(path, name)
    except Exception as e:
        try:
            os.remove(path)                        # 읽지 못한 파일을 uploads에 남기지 않는다
        except OSError:
            pass
        return err(str(e))
    g.con.execute('insert into uploads values(?,?,?,?,?,?,?,?,?)', (uid, g.u['id'], name, path, r['kind'], r['text'],
                                                                  json.dumps(r['tables'], ensure_ascii=False), int(r['drm']), now()))
    log(g.u['name'], f"첨부 {name}" + (' — DRM 문서 감지, 내용 읽지 않음' if r['drm'] else f" — 표 {len(r['tables'])}개, 장 제목 {len(r['heads'])}개"))
    return ok(upload={'id': uid, 'name': name, 'kind': r['kind'], 'drm': r['drm'], 'tables': r['tables'][:3], 'heads': r['heads'],
                      'chars': len(r['text'])})


def _uploads(ids):
    out = []
    for i in ids or []:
        u = row(g.con, 'select * from uploads where id=? and owner=?', i, g.u['id'])
        if u and not u['drm']:
            out.append(u)
    return out


# ───────────── 작성(compose) ─────────────
def compose_view(c):
    return {'id': c['id'], 'template_id': c['template_id'], 'fmt': c['fmt'], 'grade': c['grade'], 'title': c['title'],
            'blueprint': J(c['blueprint'], {}), 'chat': J(c['chat'], []), 'files': J(c['files'], []), 'doc_id': c['doc_id'],
            'llm': J(c['llm'], {}), 'fill': _fill_of(c['template_id'])}


def _fill_of(template_id):
    """서식 채우기형 양식이면 화면에 보일 요약(스킬 id · 형식 제한), 아니면 None."""
    t = row(g.con, 'select skill from templates where id=?', template_id)
    info = (J(t['skill'], {}) or {}) if t else {}
    if not info.get('fill'):
        return None
    e = engines.fill_engine(engines.fill_cid(info))
    return {'corp': e['corp'], 'sha': e['sha'], 'name': info['fill'].get('name', ''), 'fmts': [corp.fill_fmt(info['fill'])]}


def _tpl_for_llm(t):
    """llm.blueprint에 넘길 양식(스킬의 용어·금지어를 작성 규칙에 덧붙인다)."""
    info = J(t['skill'], {}) or {}
    rules = [t['rules'] or '']
    gl = info.get('glossary') or {}
    if gl.get('terms'):
        rules.append('용어: ' + ', '.join(f'{k}={v}' for k, v in gl['terms'].items()))
    banned = (gl.get('banned') or []) + ((info.get('checks') or {}).get('banned') or [])
    if banned:
        rules.append('쓰지 말 것: ' + ', '.join(banned))
    req = (info.get('checks') or {}).get('required') or []
    if req:
        rules.append('반드시 넣을 문구(글자 그대로): ' + ' / '.join(req))
    return {**t, 'rules': '\n'.join(r for r in rules if r), 'style': info.get('style'), 'fill': info.get('fill')}


def _style_of(t):
    """양식(템플릿 행)의 문체와 고정 문구 글 — 검수·자동 수정에 넘긴다. 스킬에 문체가 없으면 None(코스콤 보고 문법)."""
    if not t:
        return None, []
    info = J(t['skill'], {}) or {}
    # 글자 그대로 넣어야 하는 글(고정 문구 · 상위 스킬의 필수 문구)은 문체 검사에서 뺀다
    return info.get('style'), [f.get('text', '') for f in J(t['fixed'], [])] + ((info.get('checks') or {}).get('required') or [])


@app.post('/api/compose')
@login_required
def compose_new():
    b = request.json or {}
    t = row(g.con, 'select * from templates where id=?', b.get('template_id'))
    if not t or not core.can_use_template(t, g.u, g.net):
        return err('이 양식을 쓸 권한이 없습니다' + (' (대외비 양식은 인터넷망 사용 불가)' if t and g.net == 'internet' and t['grade'] == 'c' else ''), 403)
    files = _uploads(b.get('upload_ids'))
    text = (b.get('request') or '').strip() or t['name']
    bp, meta = llm.blueprint(_tpl_for_llm(t), text, files, ai_ctx())
    bp = checks.enforce_fixed(bp, J(t['fixed'], []))
    cid = core.new_id('c')
    info = J(t['skill'], {}) or {}
    who = f" · 스킬 {info['id']}@{info.get('version')}" if info.get('id') else ''
    chat = [{'who': 'me', 'text': text, 't': now()},
            {'who': 'ai', 'text': f"**{t['name']}** 구성({' → '.join(J(t['outline'], []))})으로 초안을 만들었습니다{who}. 고칠 점을 말씀해 주세요.",
             't': now(), 'meta': meta}]
    source = '\n'.join([text] + [f['text'] or '' for f in files])
    g.con.execute('insert into compose values(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (cid, g.u['id'], t['id'], b.get('fmt') or t['fmt'], t['grade'], bp['title'], json.dumps(bp, ensure_ascii=False),
                   json.dumps(chat, ensure_ascii=False), json.dumps([{'id': f['id'], 'name': f['name']} for f in files], ensure_ascii=False),
                   time.time(), None, json.dumps(meta, ensure_ascii=False), source[:30000]))
    g.con.execute('insert into uses values(?,1) on conflict(template_id) do update set n=n+1', (t['id'],))
    g.con.execute('update templates set uses=uses+1 where id=?', (t['id'],))
    log(g.u['name'], f"새 문서 시작 — {t['name']}{who} · AI {meta['label']} {meta['ms']}ms" + (f" · 마스킹 {meta['masked']}건" if meta.get('masked') else ''))
    return ok(compose=compose_view(row(g.con, 'select * from compose where id=?', cid)))


def _my_compose(cid):
    c = row(g.con, 'select * from compose where id=? and owner=?', cid, g.u['id'])
    if not c:
        abort(404)
    return c


@app.get('/api/compose/<cid>')
@login_required
def compose_get(cid):
    return ok(compose=compose_view(_my_compose(cid)))


@app.post('/api/compose/<cid>/chat')
@login_required
def compose_chat(cid):
    c = _my_compose(cid)
    b = request.json or {}
    msg = (b.get('message') or '').strip()
    if not msg:
        return err('내용을 입력해 주세요')
    files = _uploads(b.get('upload_ids'))
    t = row(g.con, 'select * from templates where id=?', c['template_id'])
    fill = (J(t['skill'], {}) or {}).get('fill') if t else None
    out, meta = llm.edit(J(c['blueprint']), msg, files, ai_ctx(), _style_of(t)[0],
                         '이 문서는 모양이 정해진 서식의 칸을 채우는 문서다. 장 제목 · 항목의 label · 표의 열 이름과 순서는 바꾸지 않는다. '
                         '값(text, 표의 칸)만 지시대로 바꾼다. 요청·자료에 없는 값은 지어내지 않는다.' if fill else '')
    if fill:                                    # 칸 이름·표 열이 서식과 같게 되돌린다(값만 유지)
        out['blueprint'] = fillform.normalize(out['blueprint'], fill)
    chat = J(c['chat'], [])
    chat += [{'who': 'me', 'text': msg, 't': now(), 'files': [f['name'] for f in files]}, {'who': 'ai', 'text': out['reply'], 't': now(), 'meta': meta}]
    bp = out['blueprint']
    allf = J(c['files'], []) + [{'id': f['id'], 'name': f['name']} for f in files]
    src = (c['source'] or '') + ''.join('\n' + (f['text'] or '') for f in files)
    g.con.execute('update compose set blueprint=?, chat=?, title=?, files=?, source=? where id=?',
                  (json.dumps(bp, ensure_ascii=False), json.dumps(chat, ensure_ascii=False), bp['title'], json.dumps(allf, ensure_ascii=False), src[:30000], cid))
    return ok(compose=compose_view(row(g.con, 'select * from compose where id=?', cid)))


@app.put('/api/compose/<cid>')
@login_required
def compose_put(cid):
    c = _my_compose(cid)
    b = request.json or {}
    bp = llm._clean_bp(b.get('blueprint') or J(c['blueprint']), [])
    t = row(g.con, 'select skill from templates where id=?', c['template_id'])
    fill = (J(t['skill'], {}) or {}).get('fill') if t else None
    if fill:
        bp = fillform.normalize(bp, fill)
    g.con.execute('update compose set blueprint=?, title=?, fmt=?, grade=? where id=?',
                  (json.dumps(bp, ensure_ascii=False), bp['title'], b.get('fmt') or c['fmt'], b.get('grade') or c['grade'], cid))
    return ok(compose=compose_view(row(g.con, 'select * from compose where id=?', cid)))


def _file_text(path, fmt):
    try:
        if fmt == 'hwp':
            return '\n'.join(engines.hwp_text(path))
        if fmt == 'ppt':
            return '\n'.join(engines.pptx_text(path))
        if fmt == 'xlsx':
            return '\n'.join(engines.xlsx_text(path))
        return checks.html_text(path)
    except Exception:
        return None


def _last_theme(doc_id, fmt):
    """이 문서를 앞서 만들 때 고른 문서 테마(없으면 기본)."""
    f = row(g.con, 'select resolution from doc_files where doc_id=? and fmt=? order by ver desc limit 1', doc_id, fmt)
    return doc_themes.norm((J(f['resolution'], {}) or {}).get('theme') if f else None)


def _render(doc_id, ver, fmt, bp, t, u, meta, source='', theme=None):
    tr = template_for_render(t)
    theme = doc_themes.norm(theme) if theme else _last_theme(doc_id, fmt)      # 고르지 않으면 지난 버전의 테마를 잇는다
    if fmt in ('hwp', 'xlsx'):
        theme = doc_themes.DEFAULT                 # 한글 · 엑셀은 회사 양식 그대로
    path, warns, ms, engine = engines.make(fmt, bp, tr, people_of(u), doc_id, ver, theme)
    cks = engines.check(bp, warns, *_style_of(t))
    if fmt not in ('hwp', 'xlsx'):
        cks = [c for c in cks if c['id'] != 'render']
    if fmt == 'xlsx':                              # 렌더러의 WARN(한 쪽 넘침 · 값 없는 칸)을 엑셀 말로 보여 준다. 자동 수정은 없다
        cks = [{**c, 'name': '엑셀 서식 경고 없음 (한 쪽 넘침 · 빈 칸)', 'fix': False} if c['id'] == 'render' else c for c in cks]
    info = J(t['skill'], {}) or {}
    if info.get('id'):
        cks += checks.skill_checks(bp, {**info, 'fixed': J(t['fixed'], [])})
    if info.get('fill'):                        # 서식 채우기형: 필수 칸 · 칸 형식 · 표
        cks = [c for c in cks if c['id'] not in ('empty', 'todo')] + fillform.check(bp, info['fill'])
    if source and source.strip():
        cc = checks.crosscheck(source, [{'name': FMT[fmt], 'text': _file_text(path, fmt)}])
        bad = [i for i in cc['items'] if i['kind'] in ('mismatch', 'unknown')]
        cks.append({'id': 'cross', 'name': '원본값 대조 (원본 자료 ↔ 결과 파일)', 'ok': not bad, 'fix': False,
                    'detail': '; '.join(i['detail'] for i in bad)[:200] or f"값 {cc['checked']}개 대조 · 빠진 값 {cc['missing']}개는 참고"})
    res = {'engine': engine, 'theme': theme, 'theme_name': doc_themes.NAMES[theme], **(skills.resolve(info['id'])['resolution'] if info.get('id') else
                                {'corp': {engine['corp']: engine['sha']}, 'skills': [], 'repo_head': skills.STATE['head'][:7]})}
    g.con.execute('insert into doc_files values(?,?,?,?,?,?,?,?,?,?)', (doc_id, ver, fmt, path, json.dumps(cks, ensure_ascii=False),
                                                                       json.dumps(warns, ensure_ascii=False), ms, json.dumps(meta or {}, ensure_ascii=False),
                                                                       now(), json.dumps(res, ensure_ascii=False)))
    if fmt == 'ppt':
        threading.Thread(target=ppt_shots, args=(path, doc_id, ver), daemon=True).start()
    return cks, ms


@app.post('/api/compose/<cid>/generate')
@login_required
def compose_generate(cid):
    c = _my_compose(cid)
    b = request.json or {}
    fmts = [f for f in (b.get('fmts') or [c['fmt']]) if f in FMT]
    theme = b.get('theme') if b.get('theme') in doc_themes.IDS else None      # PPT·웹 디자인 테마(없으면 지난 버전의 것)
    sync_forms()                                   # 승인된 최신 스킬로 만든다(다음 문서부터 반영)
    t = row(g.con, 'select * from templates where id=?', c['template_id'])
    if not t:
        return err('양식이 저장소에서 사라졌습니다. 양식을 다시 골라 주세요.', 404)
    bp = J(c['blueprint'])
    meta = J(c['llm'], {})
    fill = (J(t['skill'], {}) or {}).get('fill')
    if fill:                                       # 서식 채우기형(계약서 · 견적서 등)은 그 서식의 형식(한글 또는 엑셀)으로만 만든다
        fmts = [corp.fill_fmt(fill)]
    else:                                          # 엑셀은 서식 채우기형에서만
        fmts = [f for f in fmts if f != 'xlsx']
    if c['doc_id']:
        d = row(g.con, 'select * from docs where id=?', c['doc_id'])
        ver = d['ver'] + 1
        g.con.execute('update docs set ver=?, blueprint=?, title=?, updated=?, grade=? where id=?',
                      (ver, json.dumps(bp, ensure_ascii=False), bp['title'], now(), c['grade'], d['id']))
        doc_id = d['id']
    else:
        doc_id, ver = core.new_id('d'), 1
        g.con.execute('insert into docs values(?,?,?,?,?,?,?,?,?,?,?,?)', (doc_id, bp['title'], t['id'], fmts[0], c['grade'], g.u['id'], '[]', 1,
                                                                         json.dumps(bp, ensure_ascii=False), '{}', now(), now()))
        g.con.execute('update compose set doc_id=? where id=?', (doc_id, cid))
    out = []
    try:
        for f in fmts:
            cks, ms = _render(doc_id, ver, f, bp, t, g.u, meta, c['source'] or '', theme)
            out.append({'fmt': f, 'ms': ms, 'checks': cks})
    except Exception as e:
        return err(f'문서 생성 실패: {e}', 500)
    mins = round((time.time() - c['started']) / 60, 1)
    made = {'minutes': mins, 'manual': sum(MANUAL_MIN[f] for f in fmts), 'fmts': fmts}
    g.con.execute('update docs set made=? where id=?', (json.dumps(made), doc_id))
    log(g.u['name'], f"문서 생성 — {bp['title']} v{ver} ({', '.join(FMT[f] for f in fmts)}) · {', '.join(str(o['ms']) + 'ms' for o in out)}")
    return ok(doc=doc_view(row(g.con, 'select * from docs where id=?', doc_id), g.u, True), results=out)


# ───────────── 문서함 ─────────────
@app.get('/api/docs')
@login_required
def docs():
    out = []
    for d in rows(g.con, 'select * from docs order by updated desc'):
        if core.doc_perm(d, g.u) or g.u['role'] == 'security':
            v = doc_view(d, g.u)
            if not v['perm']:
                v['perm'] = 'audit'
            out.append(v)
    return ok(docs=out)


def _doc(did, need='r'):
    d = row(g.con, 'select * from docs where id=?', did)
    if not d:
        abort(404)
    p = core.doc_perm(d, g.u)
    rank = {'': 0, 'r': 1, 'w': 2, 'm': 3}
    if rank[p] < rank[need]:
        abort(403)
    if g.net == 'internet' and d['grade'] == 'c':
        abort(423)
    return d


@app.errorhandler(403)
def e403(e):
    return err('이 문서에 대한 권한이 없습니다', 403)


@app.errorhandler(404)
def e404(e):
    return err('찾을 수 없습니다', 404)


@app.errorhandler(423)
def e423(e):
    return err('대외비 문서는 인터넷망에서 열 수 없습니다. 폐쇄망으로 전환해 주세요.', 423)


# 처리하지 못한 예외도 늘 JSON으로 — HTML 500이 나가면 화면은 「서버 응답 오류 (500)」만 보여 주고 진짜 이유를 가린다.
# Flask는 예외 클래스의 상속 순서에서 가장 가까운 처리기를 고른다: NoWriteAccess → GitError → Exception.
@app.errorhandler(skills.NoWriteAccess)
def e_nowrite(e):
    return err(str(e), 403)


@app.errorhandler(skills.GitError)
def e_git(e):
    app.logger.exception('git/gh 실패')
    return err(f'스킬 저장소 작업 실패 — {str(e)[-240:]}', 502)


@app.errorhandler(413)
def e413(e):
    return err(f"파일이 너무 큽니다 (최대 {app.config['MAX_CONTENT_LENGTH'] // 1048576}MB)", 413)


@app.errorhandler(Exception)
def e500(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):            # 처리기가 따로 없는 HTTP 오류는 기본 응답 그대로
        return e
    app.logger.exception('처리하지 못한 오류')  # 서버 창에는 전체 traceback이 남는다
    return err(f'서버 오류: {type(e).__name__} — {str(e)[:200]}', 500)


@app.get('/api/docs/<did>')
@login_required
def doc_get(did):
    return ok(doc=doc_view(_doc(did), g.u, True))


@app.post('/api/docs/<did>/open')
@login_required
def doc_open(did):
    d = _doc(did, 'w')
    c = row(g.con, 'select * from compose where doc_id=? and owner=?', did, g.u['id'])
    if not c:
        cid = core.new_id('c')
        g.con.execute('insert into compose values(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (cid, g.u['id'], d['template_id'], d['fmt'], d['grade'], d['title'], d['blueprint'],
                       json.dumps([{'who': 'ai', 'text': f"**{d['title']}** v{d['ver']}을(를) 열었습니다. 고칠 점을 말씀해 주세요.", 't': now()}], ensure_ascii=False),
                       '[]', time.time(), did, '{}', ''))
        c = row(g.con, 'select * from compose where id=?', cid)
    return ok(compose=compose_view(c))


@app.post('/api/docs/<did>/fix')
@login_required
def doc_fix(did):
    d = _doc(did, 'w')
    sync_forms()
    t = row(g.con, 'select * from templates where id=?', d['template_id'])
    last = row(g.con, "select warns from doc_files where doc_id=? and ver=? and fmt='hwp'", did, d['ver'])
    style, fixed_texts = _style_of(t)
    bp, meta = engines.autofix(J(d['blueprint']), lambda xs: llm.shorten(xs, ai_ctx(fast=True), style), J(last['warns'], []) if last else [],
                               style, fixed_texts)
    info = J(t['skill'], {}) if t else {}
    if info and info.get('id'):
        bp = checks.fix_skill(bp, {**info, 'fixed': J(t['fixed'], [])})
    ver = d['ver'] + 1
    fmts = sorted({f['fmt'] for f in rows(g.con, 'select fmt from doc_files where doc_id=? and ver=?', did, d['ver'])}) or [d['fmt']]
    src = (row(g.con, 'select source from compose where doc_id=?', did) or {}).get('source') or ''
    g.con.execute('update docs set ver=?, blueprint=?, title=?, updated=? where id=?', (ver, json.dumps(bp, ensure_ascii=False), bp['title'], now(), did))
    g.con.execute('update compose set blueprint=? where doc_id=?', (json.dumps(bp, ensure_ascii=False), did))
    for f in fmts:
        _render(did, ver, f, bp, t, core.get_user(g.con, d['owner']), meta, src)
    log(g.u['name'], f"검수 자동 수정 — {d['title']} v{ver}")
    return ok(doc=doc_view(row(g.con, 'select * from docs where id=?', did), g.u, True))


@app.put('/api/docs/<did>/acl')
@login_required
def doc_acl(did):
    d = _doc(did, 'm')
    acl = (request.json or {}).get('acl') or []
    clean = []
    for a in acl:
        if a.get('t') not in ('user', 'team', 'dept', 'corp') or a.get('p') not in ('r', 'w'):
            continue
        if not core.acl_allowed(d['grade'], a['t']):
            return err(f"{GRADE[d['grade']]} 문서는 {'부서' if a['t'] == 'dept' else '전사'} 공유를 할 수 없습니다 (사람·팀까지)", 400)
        clean.append({'t': a['t'], 'v': a.get('v', ''), 'p': a['p']})
    grade = (request.json or {}).get('grade') or d['grade']
    if grade == 'c' and any(a['t'] in ('dept', 'corp') for a in clean):
        return err('대외비로 올리려면 부서·전사 공유를 먼저 빼 주세요', 400)
    g.con.execute('update docs set acl=?, grade=?, updated=? where id=?', (json.dumps(clean, ensure_ascii=False), grade, now(), did))
    log(g.u['name'], f"공유 범위 변경 — {d['title']}: " + (', '.join(f"{a['v'] or '전사'}({'쓰기' if a['p'] == 'w' else '읽기'})" for a in clean) or '나만'))
    return ok(doc=doc_view(row(g.con, 'select * from docs where id=?', did), g.u, True))


@app.get('/api/docs/<did>/file')
@login_required
def doc_file(did):
    d = _doc(did)
    ver = int(request.args.get('ver') or d['ver'])
    fmt = request.args.get('fmt') or d['fmt']
    f = row(g.con, 'select * from doc_files where doc_id=? and ver=? and fmt=? order by created desc', did, ver, fmt)
    if not f or not os.path.exists(f['path']):
        return err('파일이 없습니다', 404)
    inline = request.args.get('inline') == '1'
    ext = os.path.splitext(f['path'])[1]
    if not inline:
        log(g.u['name'], f"다운로드 — {d['title']} v{ver}{ext}")
    return send_file(f['path'], as_attachment=not inline, download_name=f"{_file_stem(d['title'])}_v{ver}{ext}")


def _file_stem(title):
    """문서 제목 → 받기 파일 이름. 줄바꿈·제어문자가 있으면 HTTP 헤더에 못 넣어 500이 나므로 첫 줄만, 파일 이름에 못 쓰는 글자는 바꾼다."""
    first = next((l.strip() for l in re.split(r'[\r\n]+', str(title or '')) if l.strip()), '')
    s = re.sub(r'[\x00-\x1f\x7f]', ' ', first)
    s = re.sub(r'[\\/:*?"<>|]', '_', s)
    return re.sub(r'\s+', ' ', s).strip(' .')[:80] or '문서'


@app.get('/api/docs/<did>/sheet')
@login_required
def doc_sheet(did):
    """엑셀 미리보기: 결과 .xlsx의 인쇄 영역을 HTML 표로(글꼴 · 테두리 · 병합 · 그림 자리까지). 파일은 밖으로 나가지 않는다."""
    d = _doc(did)
    ver = int(request.args.get('ver') or d['ver'])
    f = row(g.con, "select * from doc_files where doc_id=? and ver=? and fmt='xlsx' order by created desc", did, ver)
    if not f or not os.path.exists(f['path']):
        return err('엑셀 파일이 없습니다', 404)
    import xlsx_view
    try:
        return ok(**xlsx_view.to_html(f['path']))
    except Exception as e:
        return err(f'엑셀 미리보기를 만들지 못했습니다: {str(e)[:160]} — 「받기」로 내려받아 엑셀에서 열어 주세요.', 500)


@app.get('/api/docs/<did>/shot/<int:ver>/<name>')
@login_required
def doc_shot(did, ver, name):
    _doc(did)
    return send_from_directory(os.path.join(engines.OUT, did, f'v{ver}_shots'), name)


@app.get('/api/docs/<did>/text')
@login_required
def doc_text(did):
    d = _doc(did)
    ver = int(request.args.get('ver') or d['ver'])
    f = row(g.con, "select * from doc_files where doc_id=? and ver=? and fmt='hwp'", did, ver)
    if not f:
        return err('한글 파일이 없습니다', 404)
    pua = re.compile('[-]')
    return ok(lines=[pua.sub('■', l) for l in engines.hwp_text(f['path'])])


@app.get('/api/docs/<did>/report')
@login_required
def doc_report(did):
    """한글 '모양 미리보기'용: 렌더러에 넘긴 보고서 구조(제목·결재란·장·항목·표). 그 버전의 것이 없으면 현재 설계도로 다시 만든다."""
    d = _doc(did)
    ver = int(request.args.get('ver') or d['ver'])
    p = os.path.join(engines.job_dir(did, ver), 'report.json')
    if os.path.exists(p):
        return ok(report=json.load(open(p, encoding='utf-8')), exact=True)
    t = row(g.con, 'select * from templates where id=?', d['template_id']) or {}
    rep = engines.to_report(J(d['blueprint'], {'title': d['title'], 'sections': []}), t, people_of(core.get_user(g.con, d['owner'])))
    return ok(report=rep, exact=ver == d['ver'])


@app.post('/api/docs/<did>/launch')
@login_required
def doc_launch(did):
    """결과 파일을 이 PC에 연결된 프로그램으로 연다(.hwp → 한컴 뷰어·한글, .pptx → PowerPoint·Keynote). 앱은 내 PC에서만 돈다."""
    d = _doc(did)
    b = request.json or {}
    ver = int(b.get('ver') or d['ver'])
    fmt = b.get('fmt') or d['fmt']
    f = row(g.con, 'select * from doc_files where doc_id=? and ver=? and fmt=? order by created desc', did, ver, fmt)
    if not f or not os.path.exists(f['path']):
        return err('파일이 없습니다(사내 보호 도구가 이름을 바꿨을 수 있습니다). 「받기」로 내려받아 열어 주세요.', 404)
    try:
        if os.name == 'nt':
            os.startfile(f['path'])                      # noqa: S606 — 앱이 만든 파일만, 로컬에서만
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', f['path']])
        else:
            subprocess.Popen(['xdg-open', f['path']])
    except Exception as e:
        return err(f'열 수 있는 프로그램을 찾지 못했습니다: {str(e)[:120]} — 「받기」로 내려받아 열어 주세요.', 500)
    log(g.u['name'], f"프로그램으로 열기 — {d['title']} v{ver} ({FMT[fmt]})")
    return ok()


# ───────────── 검수만 하기 (사람이 쓴 문서 · 원본값 대조 · 재검사) ─────────────
@app.post('/api/inspect')
@login_required
def inspect():
    """원본 자료(메모·엑셀) ↔ 대상 파일(내 문서의 결과 파일, 사람이 고친 파일) 값 대조 + 보고 문법·팩 규칙."""
    b = request.json or {}
    src_files = _uploads(b.get('source_ids'))
    source = (b.get('source_text') or '') + ''.join('\n' + (f['text'] or '') for f in src_files)
    targets = []
    for i in b.get('target_ids') or []:
        f = row(g.con, 'select * from uploads where id=? and owner=?', i, g.u['id'])
        if f:
            targets.append({'name': f['name'], 'text': None if f['drm'] else (f['text'] or None)})
    if b.get('doc_id'):
        d = _doc(b['doc_id'])
        src = (row(g.con, 'select source from compose where doc_id=?', d['id']) or {}).get('source') or ''
        source = source or src
        for f in rows(g.con, 'select * from doc_files where doc_id=? and ver=?', d['id'], d['ver']):
            targets.append({'name': f"{FMT[f['fmt']]} v{d['ver']}", 'text': _file_text(f['path'], f['fmt'])})
    if not source.strip():
        return err('대조할 원본 자료(메모·엑셀)를 넣어 주세요')
    if not targets:
        return err('검사할 파일을 올리거나 문서를 골라 주세요')
    cc = checks.crosscheck(source, targets)
    # 대상 파일마다 보고 문법·팩 규칙
    rules = []
    t = row(g.con, 'select * from templates where id=?', b.get('template_id')) if b.get('template_id') else None
    info = (J(t['skill'], {}) or {}) if t else {}
    for tg in targets:
        if tg['text'] is None:
            continue
        bp = {'title': '', 'sections': [{'heading': '', 'items': [{'label': '', 'text': l.strip()} for l in tg['text'].splitlines() if l.strip()], 'table': None}]}
        r = [c for c in engines.check(bp, (), *_style_of(t)) if c['id'] in ('date', 'end')]
        if info.get('id'):
            r += checks.skill_checks(bp, {**info, 'fixed': J(t['fixed'], [])})
        rules.append({'target': tg['name'], 'checks': r})
    log(g.u['name'], f"검수 — 대상 {len(targets)}개 · 불일치 {cc['mismatch']} · 판정 불가 {cc['unknown']}")
    return ok(result=cc, rules=rules, targets=[t['name'] for t in targets])


# ───────────── 스킬 (저장소) ─────────────
def _can_change(s, u):
    """스킬 변경 요청을 낼 수 있는 사람: 그 조직의 구성원·관리자, 개인 스킬은 본인."""
    if u['role'] == 'corpAdmin':
        return True
    if s.get('scope') == 'user':
        return s.get('owner') == u['id']
    org = (s.get('org') or '').split('/')
    return u['dept'] == org[0]


def _scope_of(s):
    if s.get('scope') == 'user':
        return 'me'
    if s.get('share') == 'corp':              # 전사 공개 팩은 바꿀 때도 전사 관리자까지 승인한다
        return 'corp'
    org = (s.get('org') or '').split('/')
    return 'team' if len(org) > 1 else 'dept'


def _open_request(sid):
    """그 스킬에 아직 끝나지 않은 등록 · 변경 · 복구 · 검수 요청(같은 폴더를 고치는 PR이 둘이면 뒤엣것이 충돌한다)."""
    return row(g.con, "select * from requests where json_extract(note, '$.sid')=? and stage not in ('done', 'rejected')", sid)


def promote_plan(s, target, u, allsk):
    """개인 · 팀 스킬을 부서 팩(skills/org/<본부>/<id>) 또는 전사 팩(같은 자리 + share: corp)으로 올린 스킬 내용과 오류 목록.
    id는 그대로 둔다 — 버전 태그(<id>@v…)와 이미 만든 문서의 양식 id(<id>:<양식>)가 이어진다."""
    if target not in ('dept', 'corp'):
        return None, ['올릴 범위는 dept(부서 팩) 또는 corp(전사 팩)입니다']
    cur = _scope_of(s)
    if SCOPE_RANK[cur] >= SCOPE_RANK[target]:
        return None, [f'이미 {SCOPE_NAME[cur]} 범위입니다']
    errs = []
    for e in map(str, s.get('extends') or []):
        p = allsk.get(e.split(':', 1)[1].split('@')[0]) if e.startswith('skill:') else None
        if p and SCOPE_RANK[_scope_of(p)] < SCOPE_RANK[target]:      # 좁은 팩을 상속하면 그 팀 규칙이 섞이고, 그 팩이 바뀌면 이 팩도 승인 없이 바뀐다
            errs.append(f"상위 팩 {p['id']}({SCOPE_NAME[_scope_of(p)]})을 상속합니다 — 그 팩의 고정 문구 · 규칙을 이 팩으로 옮기고 상속에서 뺀 뒤 다시 요청하세요")
    # 개인 스킬은 만든 사람의 본부 · 이름으로 올린다(전사 관리자가 대신 요청해도 그 사람 본부에 남는다)
    me = (core.get_user(g.con, s.get('owner')) or u) if s.get('scope') == 'user' else u
    org = (s.get('org') or '').split('/')[0] if s.get('scope') == 'org' else me['dept']
    head = {'id': s['id'], 'name': s['name'], 'scope': 'org', 'org': org, **({'share': 'corp'} if target == 'corp' else {}),
            'owner': me['name'], 'version': skills.bump(s['version'], 'minor')}
    new = {**head, **{k: v for k, v in s.items() if not k.startswith('_') and k not in head and k != 'share'}}
    return new, errs + skills.validate(new, allsk)


def promote_files(s, new):
    """옛 폴더 파일은 지우고(None) 새 폴더에 같은 이름으로. 내용은 작업 폴더가 아니라 git(main)에서 꺼낸다 —
    샘플 그림 · 복제형 서식(.hwp) 같은 바이너리는 바이트 그대로이고, 사내 보호 도구가 디스크의 .hwp를 암호화해 두었어도 원본이 옮겨진다."""
    old, dst = s['_path'], skills.skill_dir(new)
    files = {}
    for rel, content in skills.files_at('main', old).items():
        files[rel] = None
        files[dst + rel[len(old):]] = content
    files[f'{dst}/kosoe-skill.yaml'] = skills.dump_skill(new)
    md = files.get(f'{dst}/SKILL.md')
    if isinstance(md, str):
        files[f'{dst}/SKILL.md'] = (md.rstrip() + f"\n\n- 공개 범위: {SCOPE_NAME[_scope_of(new)]}({new['org']}) — "
                                    f"{core.today_kr()} {SCOPE_NAME[_scope_of(s)]} 스킬에서 올림(v{s['version']} → v{new['version']})\n")
    return files


def _promote_targets(s, u, allsk):
    """스킬 화면의 「검수 요청」 단추: 올릴 수 있는 범위마다 승인 단계와 막는 이유."""
    out = []
    for t in ('dept', 'corp'):
        if SCOPE_RANK[_scope_of(s)] < SCOPE_RANK[t]:
            _, errs = promote_plan(s, t, u, allsk)
            out.append({'target': t, 'name': SCOPE_NAME[t] + ' 팩', 'stages': [STAGE_NAME[x] for x in SCOPE_STAGES[t]], 'why': '; '.join(errs)})
    return out


def skill_view(sid, s, allsk, u, full=False):
    r = skills.resolve(sid, allsk)
    o = {'id': sid, 'name': s.get('name'), 'version': s.get('version'), 'scope': _scope_of(s), 'org': s.get('org', ''), 'owner': s.get('owner', ''),
         'share': s.get('share', ''), 'path': s['_path'], 'chain': r['levels'], 'corp': r['resolution']['corp'], 'tags': skills.tags_of(sid)[:8],
         'forms': [{'id': f['id'], 'name': f['name'], 'fmt': f['fmt'], 'outline': f.get('outline', []), 'clone': bool(f.get('fill')),
                    'style': checks.style_label(f.get('style') or r.get('style')) if (f.get('style') or r.get('style')) else ''} for f in s.get('forms') or []],
         'errors': skills.validate(s, allsk), 'can_change': _can_change(s, u), 'verification': s.get('verification')}
    if full:
        o.update(blocks=s.get('blocks') or [], resolved_blocks=list(r['blocks'].values()), glossary=r['glossary'], checks=r['checks'], rules=r['rules'],
                 own_rules=s.get('rules') or [], approval_line=r['approval_line'], history=skills.history(sid), files=skills.tree(sid),
                 yaml=skills.file_text(s['_path'] + '/kosoe-skill.yaml'), skill_md=skills.file_text(s['_path'] + '/SKILL.md'),
                 promote=_promote_targets(s, u, allsk) if o['can_change'] else [], pending=bool(_open_request(sid)))
    return o


@app.get('/api/skills')
@login_required
def skills_list():
    if request.args.get('sync'):
        sync_forms(force=True)
    allsk = skills.all_skills()
    vis = []
    for sid, s in allsk.items():
        if s.get('scope') == 'user' and s.get('owner') != g.u['id'] and g.u['role'] != 'corpAdmin':
            continue
        vis.append(skill_view(sid, s, allsk, g.u))
    lk = corp.lock()
    return ok(skills=vis, corp=corp.status(), corp_forms=len(skills.corp_forms()), locked=lk.get('locked_keys', []),
              repo={**{k: v for k, v in skills.STATE.items() if k != 'synced'}, 'slug': skills.SLUG})


@app.get('/api/skills/<sid>')
@login_required
def skill_get(sid):
    allsk = skills.all_skills()
    s = allsk.get(sid)
    if not s:
        abort(404)
    return ok(skill=skill_view(sid, s, allsk, g.u, full=True))


@app.get('/api/skills-file')
@login_required
def skill_file():
    p = request.args.get('path', '')
    if not p.startswith(('skills/', 'registry/')) or '..' in p:
        abort(404)
    return ok(text=skills.file_text(p))


def _open_skill_request(kind, s, files, u, report=None, note=''):
    scope = _scope_of(s)
    pr = skills.open_pr(kind, s, files, f"{u['name']} {u['title']} ({u['team']})",
                        body=(f"## {KIND_NAME[kind]} — {s['name']} v{s['version']}\n\n- 범위: {scope} · 위치 `{skills.skill_dir(s)}`\n"
                              f"- 상속: {', '.join(map(str, s.get('extends') or []))}\n- 요청: {u['name']} {u['title']} ({u['team']})\n"
                              + (f"- 메모: {note}\n" if note else '')
                              + (f"\n### 검증 리포트\n{_report_md(report)}\n" if report else '')
                              + "\n_코쇠오피스가 만든 PR입니다. 가상 조직·가상 데이터._\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)"),
                        scope_label='scope:user' if scope == 'me' else 'scope:org')
    rid = core.new_id('r')
    forced = (report or {}).get('forced')
    hist = [{'t': now(), 'who': f"{u['name']} {u['title']}", 'act': KIND_NAME[kind] + ' 요청' + (' (검증 미통과 · 강제 등록)' if forced else ''),
             'note': (f"강제 등록 사유: {forced['reason']}" if forced else note)}]
    fmts = [f['fmt'] for f in s.get('forms') or []] or ['hwp']
    org = (s.get('org') or '').split('/')
    g.con.execute('insert into requests values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (rid, s['name'], fmts[0], scope, u['id'], org[0] if s.get('scope') == 'org' else u['dept'],
                   (org[1] if len(org) > 1 else '') if s.get('scope') == 'org' else u['team'], SCOPE_STAGES[scope][0],
                   json.dumps([f['name'] for f in s.get('forms') or []], ensure_ascii=False), '[]', '', '[]', pr['branch'], pr['pr'], pr['url'],
                   skills.skill_dir(s), json.dumps({'kind': kind, 'sid': s['id'], 'version': s['version'], 'report': report,
                                                    'verification': s.get('verification')}, ensure_ascii=False),
                   json.dumps(hist, ensure_ascii=False), now(), now()))
    log(u['name'], f"{KIND_NAME[kind]} 요청 — {s['name']} v{s['version']} · " + (f"PR #{pr['pr']}" if pr['pr'] else '로컬 브랜치 ' + pr['branch']))
    r = row(g.con, 'select * from requests where id=?', rid)
    if r['stage'] == 'ci':                     # 개인 스킬: 자동 검사 통과 시 바로 병합
        errs = skills.validate(s, skills.all_skills() | {s['id']: s})
        if errs:
            _advance(r, {'name': '자동 검사', 'title': '', 'id': ''}, False, '; '.join(errs)[:300])
        else:
            _advance(r, {'name': '자동 검사', 'title': '(validate.py)', 'id': ''}, True, '스키마·상속·잠금·보안 검사 통과')
    return row(g.con, 'select * from requests where id=?', rid)


def _public_detail(c, rep):
    """PR 본문·스킬 파일에 적을 기준 설명. 숫자 기준은 대표 문서의 값이 드러나지 않게 건수로 적는다.
    문체 기준은 화면에만 걸린 문장을 보여 주고(detail), 저장소에는 기준 이름만 올린다(public_detail)."""
    if c.get('id') == 'grammar':
        return c.get('public_detail', c.get('detail', ''))
    if c.get('id') != 'numbers':
        return c.get('detail', '')
    lost = sum(len(t['with']['lost']) for t in rep.get('tasks') or [])
    new = sum(len(t['with']['new']) for t in rep.get('tasks') or [])
    return f'빠진 숫자 {lost}건 · 새 숫자 {new}건' if lost or new else ''


def _report_md(rep):
    """PR 본문에 넣는 검증 리포트(저장소에 올라간다 — 대표 문서의 글·값은 넣지 않는다)."""
    if not rep:
        return ''
    lines = ['| 기준 | 결과 | 내용 |', '|---|---|---|']
    for c in rep.get('criteria', []):
        lines.append(f"| {c['name']} | {'✅' if c['pass'] else '❌'} | {_public_detail(c, rep)} |")
    if rep.get('mode') == 'clone':
        fid = rep.get('fidelity') or {}
        lines.append(f"\n복제형 — 서식의 고정 글 {fid.get('fixed_chars', '-')}자 · 칸 {fid.get('slots', '-')}개. 되만들기 시험: 대표 문서 {len(fid.get('docs') or [])}건 중 "
                     f"{sum(1 for d in fid.get('docs') or [] if d.get('identical'))}건이 원본과 글자 · 구성 · 모양이 같음")
    else:
        lines.append(f"\n스킬 사용 {rep.get('with_score', 0)}점 / 미사용 {rep.get('without_score', 0)}점")
    st = rep.get('style') or {}
    if st and not st.get('default'):
        lines.append(f"\n문체 기준(대표 문서에서 잼): {st.get('label', '')} — {st.get('basis', '')}")
    f = rep.get('forced')
    if f:
        lines.append(f"\n### ⚠️ 검증 미통과 강제 등록\n- 요청: {f['by']} ({f['t']})\n- 사유: {f['reason']}\n- 미통과 항목:\n" + '\n'.join(f'  - {x}' for x in f['failed']))
    return '\n'.join(lines)


@app.post('/api/skills/<sid>/change')
@login_required
def skill_change(sid):
    """팩 변경(고정 문구·규칙·검수 규칙) → 버전 올림 → PR → 승인 후 다음 문서부터 반영."""
    skills.ensure(force=True, max_age=20)
    allsk = skills.all_skills()
    s = allsk.get(sid)
    if not s:
        abort(404)
    if not _can_change(s, g.u):
        return err('이 스킬의 변경을 요청할 권한이 없습니다', 403)
    if _open_request(sid):
        return err('이 스킬에 처리 중인 요청이 있습니다 — 끝난 뒤 다시 요청하세요', 409)
    b = request.json or {}
    new = {k: v for k, v in s.items() if not k.startswith('_')}
    if 'blocks' in b:
        new['blocks'] = [{'id': x.get('id') or f'b{i + 1}', 'heading': x.get('heading', ''), 'text': x['text']} for i, x in enumerate(b['blocks']) if x.get('text')]
    if 'rules' in b:
        new['rules'] = [x for x in b['rules'] if x]
    if 'checks' in b:
        new['checks'] = b['checks']
    new['version'] = skills.bump(s['version'], 'minor')
    errs = skills.validate(new, allsk)
    if errs:
        return err('검사 실패: ' + '; '.join(errs))
    rel = s['_path'] + '/kosoe-skill.yaml'
    r = _open_skill_request('update', {**new, '_path': s['_path']}, {rel: skills.dump_skill(new)}, g.u, note=b.get('note', ''))
    return ok(request=req_view(r, g.u))


@app.post('/api/skills/<sid>/revert')
@login_required
def skill_revert(sid):
    """이전 승인 버전(태그)의 내용으로 되돌리는 PR. 버전 번호는 앞으로(패치)."""
    skills.ensure(force=True, max_age=20)
    allsk = skills.all_skills()
    s = allsk.get(sid)
    if not s:
        abort(404)
    if not _can_change(s, g.u):
        return err('이 스킬의 복구를 요청할 권한이 없습니다', 403)
    if _open_request(sid):
        return err('이 스킬에 처리 중인 요청이 있습니다 — 끝난 뒤 다시 요청하세요', 409)
    tag = (request.json or {}).get('tag', '')
    if tag not in skills.tags_of(sid):
        return err('없는 태그입니다')
    old = skills.files_at(tag, s['_path'])
    yml = old.get(s['_path'] + '/kosoe-skill.yaml')
    if not yml:
        return err('그 태그 시점의 스킬 파일을 찾지 못했습니다')
    od = yaml.safe_load(yml)
    od['version'] = skills.bump(s['version'], 'patch')
    files = {k: v for k, v in old.items()}
    files[s['_path'] + '/kosoe-skill.yaml'] = skills.dump_skill(od)
    for f in skills.tree(sid):                       # 그 뒤에 생긴 파일은 지운다
        if f not in files:
            files[f] = None
    r = _open_skill_request('revert', {**od, '_path': s['_path']}, files, g.u, note=f'{tag} 내용으로 복구')
    return ok(request=req_view(r, g.u))


@app.post('/api/skills/<sid>/promote')
@login_required
def skill_promote(sid):
    """개인 · 팀 스킬 → 부서 팩 · 전사 팩 검수 요청: 폴더를 새 범위 자리로 옮기는 PR을 열고, 그 범위의 승인 단계를 거쳐 병합한다."""
    skills.ensure(force=True, max_age=20)
    allsk = skills.all_skills()
    s = allsk.get(sid)
    if not s:
        abort(404)
    if not _can_change(s, g.u):
        return err('이 스킬의 검수 요청을 낼 권한이 없습니다', 403)
    if _open_request(sid):
        return err('이 스킬에 처리 중인 요청이 있습니다 — 끝난 뒤 다시 요청하세요', 409)
    b = request.json or {}
    new, errs = promote_plan(s, b.get('target'), g.u, allsk)
    if errs:
        return err('; '.join(errs)[:400])
    dst = skills.skill_dir(new)
    note = f"{s['_path']} → {dst}" + (f" · {str(b['note']).strip()[:200]}" if (b.get('note') or '').strip() else '')
    r = _open_skill_request('promote', {**new, '_path': dst}, promote_files(s, new), g.u, note=note)
    return ok(request=req_view(r, g.u))


# ───────────── ★ 스킬 빌더: 첨부 → 분석 → 상속 기반 생성 → 검증 → 등록 ─────────────
def _slug(name, uid):
    base = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return (base[:20] or 'skill') + '-' + uid + '-' + format(int(time.time()) % 46656, 'x')


def _parent_skill(u, scope, allsk):
    """상속할 가장 가까운 조직 스킬: 개인 → 내 팀 → 내 본부, 팀 → 내 본부."""
    team_path = f"{u['dept']}/{u['team']}"
    cands = []
    if scope == 'me':
        cands += [s for s in allsk.values() if s.get('scope') == 'org' and s.get('org') == team_path]
    if scope in ('me', 'team'):
        cands += [s for s in allsk.values() if s.get('scope') == 'org' and s.get('org') == u['dept']]
    # 복제형 스킬(서식 + 칸)은 물려줄 고정 문구·규칙이 없는 끝단 스킬이다 — 상위 스킬로 삼지 않는다
    cands = [s for s in cands if not (s.get('forms') and all(f.get('fill') for f in s['forms']))]
    return cands[0] if cands else None


# ② 분석 뒤처리: AI가 뽑은 장 · 규칙을 자르지 말고 거른다
NUM_HEAD = re.compile(r'^\s*(?:\d{1,2}|[가나다라마바사아자차카타파하]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ])\s*[.)]\s*(?!\d)')      # 「1. 」「가. 」「Ⅱ. 」 장 번호 — 엔진이 장 머리를 붙인다
FORMAT_RULE = re.compile(r'맑은 고딕|바탕체|돋움|\d+\s*pt\b|포인트|굵게|글꼴|글씨 크기|들여\s*쓰|(?:왼쪽|오른쪽|가운데|좌측|우측|양쪽)\s*정렬|빈 줄|줄 간격|여백|자동생성|기호 순서')
PRIVACY_RULE = re.compile(r'가린다|가려|마스킹|실명|연락처|개인정보')


def norm_heading(h, prose=False):
    """AI가 뽑은 장 후보 한 줄 → 장 이름. 끝의 설명 괄호를 떼고, 개조식 보고서는 장 번호도 뗀다(엔진이 장 머리 □ · 01을 붙인다 —
    남겨 두면 「□ 1. 추진 개요」가 된다). 서술형 문서(계약서 · 규정)의 조 · 항 번호는 그 문서의 내용이라 둔다."""
    h = re.sub(r'\s*\(.*?\)\s*$', '', str(h)).strip()
    return h if prose else NUM_HEAD.sub('', h).strip()


def split_rules(rules):
    """AI 규칙 → (내용 규칙, 뺀 규칙과 이유). 글꼴 · 들여쓰기 · 빈 줄은 엔진(서식)이, 개인정보는 검사(validate)가 맡는다.
    앞에서 몇 개만 남기면 AI가 서식 설명을 먼저 썼을 때 내용 규칙이 잘린다 — 먼저 거르고 20개까지 둔다."""
    keep, drop = [], []
    for r in rules or []:
        r = str(r).strip()
        if not r or r in keep:
            continue
        why = '서식(엔진이 맡음)' if FORMAT_RULE.search(r) else '개인정보(검사가 맡음)' if PRIVACY_RULE.search(r) else ''
        (drop.append({'rule': r, 'why': why}) if why else keep.append(r))
    return keep[:20], drop


def _nearest_corp_form(outline, fmt):
    best, score = None, -1
    for f in skills.corp_forms():
        if f['fmt'] != fmt:
            continue
        a, b = set(outline), set(f['outline'])
        sc = len(a & b) / max(1, len(a | b))
        sc += sum(1 for h in outline for x in f['outline'] if h != x and (h in x or x in h)) * 0.1
        if sc > score:
            best, score = f, sc
    return best, round(max(score, 0), 2)


def _highlights(docs, fixed, outline):
    out = []
    for d in docs:
        lines = []
        for l in (d['text'] or '').splitlines()[:80]:
            s = l.strip()
            if not s:
                continue
            kind = 'fixed' if any(f['text'] and (f['text'] in s or s in f['text'] or checks.is_fixed_item(s, [f['text']])) and len(s) > 8 for f in fixed) else \
                   'head' if any(h == s or (len(s) <= 26 and h in s) for h in outline) else \
                   'var' if checks.NUM_RX.search(s) or re.search(r'20\d\d\.\s*\d', s) else ''
            lines.append({'t': s[:160], 'k': kind})
        out.append({'name': d['name'], 'lines': lines})
    return out


# ───────────── 복제형 스킬 — 원본을 서식으로 삼고 바뀌는 칸만 비운다(clone.py) ─────────────
def _clone_dir(jid):
    d = os.path.join(engines.JOBS, 'skillgen', jid)
    os.makedirs(d, exist_ok=True)
    return d


def _slot_ctx(s, same_line):
    """칸 앞뒤의 고정 글. 같은 줄의 다른 칸은 ▢로 가린다(값이 이름 붙이기 요청·화면에 섞이지 않게)."""
    left, right, off = s['left'], s['right'], s['span'][1]
    for o in sorted(same_line, key=lambda x: -x['span'][0]):
        if o is s:
            continue
        if o['span'][1] <= s['span'][0]:
            left = left[:o['span'][0]] + '▢' + left[o['span'][1]:]
        else:
            right = right[:o['span'][0] - off] + '▢' + right[o['span'][1] - off:]
    return clone.PUA.sub('', left)[-40:], clone.PUA.sub('', right)[:40]


def _clone_job(hw, others, req_text, scope, name):
    """한글 대표 문서 2건 이상 → 복제형 스킬 초안. 돌려주는 값: (job 응답, None) 또는 (None, 만들지 못한 이유)."""
    if not clone.ready():
        return None, f'칸 채우기 부품이 든 전사 스킬({clone.ENGINE})이 잠금 파일에 없습니다'
    heads = extract.read(hw[0]['path'], hw[0]['name'])['heads']
    an = clone.analyze([f['path'] for f in hw], [f['name'] for f in hw], heads)
    if not an['ok']:
        return None, an['reason']
    by = {}
    for s in an['slots']:
        by.setdefault(s['node'], []).append(s)
    for s in an['slots']:
        s['before'], s['after'] = _slot_ctx(s, by[s['node']])
    # ③ 칸 이름 붙이기 — AI의 일은 여기까지다(글자는 코드가 원본에서 옮긴다)
    reps = {}                                   # 값이 늘 같은 칸들은 한 칸으로 묶여 있다(group) — 묶음마다 한 번만 이름을 묻는다
    for s in an['slots']:
        reps.setdefault(s['group'], s)
    named, meta = llm.name_slots([{'id': gid, 'label': next((x['label'] for x in an['slots'] if x['group'] == gid and x['label']), ''),
                                   'places': [{k: x[k] for k in ('section', 'before', 'after')} for x in an['slots'] if x['group'] == gid][:4],
                                   'values': s['values']} for gid, s in reps.items()], ai_ctx(fast=True))
    keys = clone.make_keys(an['slots'], {gid: v.get('label') for gid, v in named.items()})
    jid = core.new_id('j')
    tpl = os.path.join(_clone_dir(jid), 'form.hwp')
    built = clone.build(hw[0]['path'], an, keys, tpl)
    if not built['ok']:
        return None, '서식을 만들지 못했습니다 — ' + '; '.join(built['problems'])[:300]
    sections = []
    for gid, s in reps.items():
        h = s['section'] or '문서 정보'
        sec = next((x for x in sections if x['heading'] == h), None)
        if not sec:
            sec = {'heading': h, 'fields': []}
            sections.append(sec)
        f = {'key': keys[s['id']], 'label': keys[s['id']], 'required': all(v.strip() for v in s['values'])}
        # 적는 법: AI가 붙인 설명 + 서식에서 이 칸의 앞뒤에 이미 적혀 있는 글(값에 그 글을 다시 넣지 않도록 문서를 쓸 때 AI에게도 보여 준다)
        where = max((x for x in an['slots'] if x['group'] == gid), key=lambda x: len(x['before'].strip()) + len(x['after'].strip()))
        spot = f"서식의 자리: “{where['before'][-16:]}▢{where['after'][:16]}”" if (where['before'].strip() or where['after'].strip()) else ''
        hint = ' · '.join(x for x in (named[gid].get('hint') or '', spot) if x)
        if hint:
            f['hint'] = hint
        df = clone.date_format(s['values'])
        if df:
            f['date'] = df
        sec['fields'].append(f)
    fname = name[:40].replace(' 팩', '')
    first = next((f['key'] for sec in sections for f in sec['fields'] if f['required'] and re.fullmatch(r'\w+', f['key'])), '')
    fill = {'kind': 'hwp-fill', 'engine': clone.ENGINE, 'template': 'templates/form.hwp',
            'title': f'{fname} ({{{first}}})' if first else fname, 'sections': sections}
    draft = {'id': _slug('hwp-form', g.u['id']), 'name': name[:40], 'scope': 'user' if scope == 'me' else 'org', 'version': '1.0.0', 'grade': 'i',
             'extends': [f'corp:{clone.ENGINE}'],
             'forms': [{'id': 'main', 'name': fname, 'fmt': 'hwp', 'use': '문서', 'outline': [x['heading'] for x in sections],
                        'desc': f"한글 대표 문서 {len(hw)}건을 맞대어 만든 복제형 서식 — 원본의 글과 모양은 그대로, 칸 {an['fields']}개만 채운다",
                        'blocks': [], 'fill': fill}],
             'blocks': [], 'glossary': {'terms': {}, 'banned': []}, 'checks': {'required': [], 'banned': []}, 'rules': []}
    if scope == 'me':
        draft['owner'] = g.u['id']
    else:
        draft['org'] = g.u['dept'] if scope == 'dept' else f"{g.u['dept']}/{g.u['team']}"
        draft['owner'] = g.u['name']
    # 화면용: 기준 문서의 줄마다 칸 자리를 [칸 이름]으로 보여 준다
    lines = []
    for i, text in an['base_text']:
        ss = sorted(by.get(i, []), key=lambda x: -x['span'][0])
        for x in ss:
            text = text[:x['span'][0]] + f"[{keys[x['id']]}]" + text[x['span'][1]:]
        lines.append({'t': clone.PUA.sub('', text).strip()[:160], 'k': 'var' if ss else 'fixed'})
    analysis = {'mode': 'clone', 'base': None, 'parent': None, 'meta': meta, 'fields': [],
                'highlights': [{'name': hw[0]['name'] + ' — 기준 문서(이 파일이 서식이 됩니다)', 'lines': lines}],
                'docs': [{'name': f['name'], 'heads': [], 'kind': f['kind']} for f in hw],
                'clone': {'ok': True, 'docs': an['docs'], 'file_ids': [f['id'] for f in hw], 'skipped': [f['name'] for f in others],
                          'lines': an['lines'], 'text_lines': an['text_lines'], 'var_lines': an['var_lines'], 'fixed_ratio': an['fixed_ratio'],
                          'fixed_chars': an['fixed_chars'], 'slot_chars': an['slot_chars'], 'template': tpl, 'fields': an['fields'],
                          'slots': [{'id': s['id'], 'key': keys[s['id']], 'group': s['group'], 'rule_label': s['label'], 'section': s['section'] or '문서 정보',
                                     'before': s['before'], 'after': s['after'], 'values': s['values']} for s in an['slots']]}}
    g.con.execute('insert into skill_jobs values(?,?,?,?,?,?,?,?,?,?,?,?)',
                  (jid, g.u['id'], req_text, scope, 'analyzed', json.dumps([f['id'] for f in hw], ensure_ascii=False), json.dumps(analysis, ensure_ascii=False),
                   json.dumps(draft, ensure_ascii=False), '', '', now(), now()))
    log(g.u['name'], f"스킬 빌더 ② 분석(복제형) — 한글 {len(hw)}건을 맞대어 칸 {an['fields']}개({len(an['slots'])}곳) · 고정 {an['fixed_ratio'] * 100:.0f}% · 칸 이름 {meta['label']} {meta['ms']}ms")
    return {'id': jid, 'draft': draft, 'analysis': analysis, 'scope': scope}, None


def _evaluate_clone(j, draft, analysis):
    """④ 되만들기 시험: 서식에 각 대표 문서의 칸 값을 넣어 다시 만들고 원본과 글자 · 구성 · 모양을 비교한다(AI 없이 코드로)."""
    cl = analysis['clone']
    files = _uploads(cl['file_ids'])
    form = draft['forms'][0]
    fill = form.get('fill') or {}
    tpl = cl['template']
    if not os.path.exists(tpl) or len(files) != len(cl['docs']):
        return err('대표 문서나 서식 파일이 이 PC에 남아 있지 않습니다. ② 분석부터 다시 해 주세요')
    want = sorted({s['key'] for s in cl['slots']})
    nf = len(want)
    if sorted(f.get('key') for sec in fill.get('sections') or [] for f in sec.get('fields') or []) != want:
        return err('칸의 key는 서식 파일에 들어 있어 바꾸거나 지울 수 없습니다. 화면에 보이는 이름(label)만 고쳐 주세요')
    errs = skills.validate(draft, skills.all_skills())
    jd = _clone_dir(j['id'])
    docs = []
    for k, f in enumerate(files):
        out = os.path.join(jd, f'remake_{k + 1}.hwp')
        made, warns = clone.remake(tpl, {s['key']: s['values'][k] for s in cl['slots']}, out)
        c = clone.compare(f['path'], out) if made else {'text': [0, 0], 'struct': [0, 0], 'shape': [0, 0], 'identical': False, 'bytes_same': False, 'diffs': []}
        docs.append({'doc': f['name'], 'made': made, 'warns': warns, **{x: c[x] for x in ('text', 'struct', 'shape', 'identical', 'bytes_same', 'diffs')}})
    left = clone.leftovers(tpl, {'slots': cl['slots']})
    # 참고: AI가 대표 문서의 글에서 칸 값을 찾아 넣는가(문서를 새로 만들 때 AI가 하는 일). 정답은 맞대기에서 이미 안다
    ai = [None] * len(files)
    ctx = ai_ctx(fast=True)
    nrm = lambda v: re.sub(r'\s+', '', str(v or ''))

    def find(k, f):
        try:
            bp, m = llm.blueprint({'fill': fill, 'name': form['name']}, '아래 문서와 같은 내용으로 이 서식의 칸을 채워 줘.\n\n' + (f['text'] or '')[:8000], [], ctx)
            got = fillform.to_values(bp, fill)['fields']
            truth = {s['key']: s['values'][k] for s in cl['slots']}
            miss = [key for key, v in truth.items() if nrm(got.get(key)) != nrm(v)]
            ai[k] = {'doc': f['name'], 'hit': nf - len(miss), 'n': nf, 'mode': m['mode'], 'ms': m['ms'], 'miss': miss[:8]}
        except Exception as e:
            ai[k] = {'doc': f['name'], 'hit': 0, 'n': nf, 'mode': 'error', 'ms': 0, 'miss': [], 'error': str(e)[:120]}

    th = [threading.Thread(target=find, args=(k, f)) for k, f in enumerate(files)]
    for t in th:
        t.start()
    for t in th:
        t.join(timeout=600)
    ai = [a for a in ai if a]
    used = [a for a in ai if a['mode'] == 'llm']
    pii = [e for e in errs if e.startswith('보안')]
    need = 1 if draft.get('scope') == 'user' else 3
    frac = lambda key: ' · '.join(f"문서 {i + 1}: {d[key][0]}/{d[key][1]}" for i, d in enumerate(docs))
    full = lambda key: bool(docs) and all(d['made'] and d[key][1] and d[key][0] == d[key][1] for d in docs)
    crit = [
        {'id': 'f_text', 'name': '글자 재현 — 원본과 줄 단위로 같음', 'pass': full('text'), 'detail': frac('text')},
        {'id': 'f_struct', 'name': '구성 재현 — 문단 · 표 · 칸의 순서와 병합', 'pass': full('struct'), 'detail': frac('struct')},
        {'id': 'f_shape', 'name': '모양 재현 — 문단 모양 · 글자 모양 · 칸 테두리', 'pass': full('shape'), 'detail': frac('shape')},
        {'id': 'f_clean', 'name': '서식에 대표 문서의 값이 남지 않음', 'pass': not left, 'detail': f'남은 값 {len(left)}건' if left else f"칸 {nf}개({len(cl['slots'])}곳)를 모두 비움"},
        {'id': 'security', 'name': '보안(실명·연락처·계좌 없음)', 'pass': not pii, 'detail': '; '.join(pii)},
        {'id': 'f_ai', 'name': '참고 — AI가 대표 문서의 글에서 칸 값을 찾음', 'pass': True, 'info': True,
         'detail': ' · '.join(f"문서 {i + 1}: {a['hit']}/{a['n']}칸" for i, a in enumerate(ai)) if used else 'AI를 쓰지 않아 재지 않음'},
        {'id': 'human', 'name': f'사람 확인(시범 작성 {need}건 👍)', 'pass': False, 'detail': '아래에서 확인', 'human': need},
    ]
    report = {'mode': 'clone', 'criteria': crit, 'tasks': [], 'errors': errs,
              'fidelity': {'docs': docs, 'slots': nf, 'places': len(cl['slots']), 'fixed_ratio': cl['fixed_ratio'], 'fixed_chars': cl['fixed_chars'],
                           'slot_chars': cl['slot_chars'], 'left': left[:8]},
              'ai': ai, 'auto_pass': all(c['pass'] for c in crit if c['id'] != 'human') and not errs,
              # 강제 등록: 재현도 미통과는 사유를 남기고 넘길 수 있지만, 스킬 파일 검사 오류 · 보안 · 서식에 남은 값은 넘길 수 없다
              'can_force': not errs and not pii and not left, 'upload': _upload_notice(draft, tpl)}
    g.con.execute("update skill_jobs set skill=?, report=?, stage='evaluated', updated=? where id=?",
                  (json.dumps(draft, ensure_ascii=False), json.dumps(report, ensure_ascii=False), now(), j['id']))
    log(g.u['name'], f"스킬 빌더 ④ 되만들기 시험 — {draft['id']} · 문서 {len(docs)}건 중 {sum(1 for d in docs if d['identical'])}건 원본과 같음 · 자동 기준 {'통과' if report['auto_pass'] else '미통과'}")
    return ok(report=report, draft=draft, analysis=analysis)


@app.post('/api/skillgen/analyze')
@login_required
def skillgen_analyze():
    b = request.json or {}
    files = _uploads(b.get('upload_ids'))
    if not files:
        return err('DRM이 없는 대표 문서(초안·기존 문서)를 1건 이상 올려 주세요')
    scope = b.get('scope') if b.get('scope') in ('me', 'team', 'dept') else 'me'
    req_text = (b.get('request') or '').strip()
    docs = []
    for f in files:
        r = extract.read(f['path'], f['name'])
        docs.append({'name': f['name'], 'text': f['text'] or '', 'heads': r['heads'], 'kind': f['kind']})
    name0 = (req_text and re.sub(r'\s*(스킬|팩)?\s*(만들어\s*줘|만들어|생성해\s*줘|해\s*줘)\s*$', '', req_text).strip(' ."')) or files[0]['name'].rsplit('.', 1)[0][:30]
    if not name0.endswith(('팩', '스킬')):
        name0 += ' 팩'
    hw = [f for f in files if f['kind'] == 'hwp']
    why = ''
    if b.get('mode') == 'compose':
        why = '조립형으로 만들도록 골랐습니다'
    elif len(hw) >= 2:                          # 한글 대표 문서가 2건 이상이면 먼저 복제형(원본을 서식으로)으로 만들어 본다
        try:
            job, why = _clone_job(hw, [f for f in files if f['kind'] != 'hwp'], req_text, scope, name0)
        except Exception as e:
            job, why = None, f'복제형 분석 중 오류: {str(e)[:160]}'
        if job:
            return ok(job=job)
    elif hw:
        why = '같은 종류의 한글 문서가 2건 이상 있어야 바뀌는 칸을 찾을 수 있습니다'
    # 문체는 AI가 아니라 코드가 대표 문서 글에서 잰다(종결 형태·날짜 형식·항목 길이). 보고서가 아닌 문서(계약서·공문 등)는 그 문서 기준으로 쓰고 검증한다.
    style = checks.measure_style([d['text'] for d in docs])
    prose = not checks.is_default_style(style)
    out, meta = llm.extract(docs, ai_ctx(), prose)
    kinds = [d['kind'] for d in docs]
    fmt = 'ppt' if 'pptx' in kinds else 'web' if 'html' in kinds else 'hwp'
    if re.search(r'PPT|발표|제안서|덱', req_text, re.I) and not {'hwp', 'hwpx'} & set(kinds):   # hwpx도 한글 문서
        fmt = 'ppt'
    outline = []
    for h in out.get('outline') or []:
        h = norm_heading(h, prose)
        # 표지·목차·결재란과 발표 자료의 맺음 장(감사합니다 등)은 엔진이 따로 만든다 — 장 구성에 넣지 않는다
        if h and len(h) <= (28 if prose else 16) and not re.search(r'표지|목차|결재|^감사|^마무리$|^맺음|thank\s*you|q\s*&\s*a', h, re.I) and h not in outline:
            outline.append(h)
    outline = outline[:14 if prose else 8] or ['개요', '주요 내용', '향후 계획']
    base, sim = _nearest_corp_form(outline, fmt)
    allsk = skills.all_skills()
    parent = _parent_skill(g.u, scope, allsk)
    name = (req_text and re.sub(r'\s*(스킬|팩)?\s*(만들어\s*줘|만들어|생성해\s*줘|해\s*줘)\s*$', '', req_text).strip(' ."')) or out.get('name_suggest') or '나의 문서 스킬'
    if not name.endswith(('팩', '스킬')):
        name += ' 팩'
    sid = _slug(base['id'] if base else fmt, g.u['id'])
    blocks = []
    for x in out.get('fixed') or []:
        t = re.sub(r'^\s*[ㅇ□■○●◦•·\-–※>]+\s*', '', str(x.get('text') or ''))           # 한글 단계 기호
        t = re.sub(r'^\s*\(([^)]{1,8})\)\s*' if prose else r'^\s*[(\[]([^)\]]{1,8})[)\]]\s*', '', t).strip()   # (라벨) — 서술형 문서의 맨 앞 [칸]은 지우지 않는다
        if len(t) >= 8 and t not in [b['text'] for b in blocks]:
            h = str(x.get('heading') or '')
            blocks.append({'id': f'b{len(blocks) + 1}', 'heading': h if h in outline else next((o for o in outline if o in h or h in o), h), 'text': t})
    blocks = blocks[:12 if prose else 6]
    rules, dropped = split_rules(out.get('rules'))
    corp_ext = {'hwp': 'corp:koscom-hwp-report', 'ppt': 'corp:koscom-doc-pack#ppt-master', 'web': 'corp:koscom-webslide'}[fmt]
    extends = ([f"skill:{parent['id']}"] if parent else []) + [corp_ext, 'corp:kosoe-illustrations']
    draft = {'id': sid, 'name': name[:40], 'scope': 'user' if scope == 'me' else 'org', 'version': '1.0.0', 'grade': 'i', 'extends': extends,
             'forms': [{'id': 'main', 'name': name[:40].replace(' 팩', ''), 'fmt': fmt, 'use': '보고', 'outline': outline,
                        'desc': f"{len(docs)}건의 대표 문서로 만든 {FMT[fmt]} 양식", **({'preset': base['preset']} if base and base.get('preset') else {}),
                        'blocks': [x['id'] for x in blocks]}],
             'blocks': blocks, 'glossary': {'terms': {}, 'banned': []}, 'checks': {'required': [], 'banned': []},
             'rules': rules}
    if prose:                                   # 보고 문법과 다를 때만 스킬에 적는다(없으면 전사 보고 문법을 그대로 상속)
        draft['forms'][0]['style'] = {k: style[k] for k in ('ending', 'date', 'max_len')}
        draft['forms'][0]['use'] = '문서'
    if scope == 'me':
        draft['owner'] = g.u['id']
    else:
        draft['org'] = g.u['dept'] if scope == 'dept' else f"{g.u['dept']}/{g.u['team']}"
        draft['owner'] = g.u['name']
    jid = core.new_id('j')
    analysis = {'mode': 'compose', 'clone': {'ok': False, 'reason': why} if why else None,
                'base': {'id': base['id'], 'name': base['name'], 'similarity': sim} if base else None,
                'parent': {'id': parent['id'], 'name': parent['name'], 'version': parent['version']} if parent else None,
                'highlights': _highlights(docs, blocks, outline), 'fields': out.get('fields') or [], 'meta': meta, 'dropped_rules': dropped,
                'style': {**style, 'label': checks.style_label(style), 'default': not prose},
                'docs': [{'name': d['name'], 'heads': d['heads'], 'kind': d['kind']} for d in docs]}
    g.con.execute('insert into skill_jobs values(?,?,?,?,?,?,?,?,?,?,?,?)',
                  (jid, g.u['id'], req_text, scope, 'analyzed', json.dumps([f['id'] for f in files]), json.dumps(analysis, ensure_ascii=False),
                   json.dumps(draft, ensure_ascii=False), '', '', now(), now()))
    log(g.u['name'], f"스킬 빌더 ② 분석 — 대표 문서 {len(files)}건 · 기반 {base['id'] if base else '-'} · 상위 {parent['id'] if parent else '전사'} · {meta['label']} {meta['ms']}ms")
    return ok(job={'id': jid, 'draft': draft, 'analysis': analysis, 'scope': scope})


def _bp_score(bp, form, blocks, memo, allowed='', fixed=()):
    heads = [s['heading'] for s in bp['sections']]
    outline = form['outline']
    # 구성 재현: 기대 목차 순서대로 몇 개가 같은 순서로 나오는가(LCS 비율)
    m, n = len(outline), len(heads)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m):
        for j in range(n):
            dp[i + 1][j + 1] = dp[i][j] + 1 if outline[i] == heads[j] or outline[i] in heads[j] else max(dp[i][j + 1], dp[i + 1][j])
    struct = dp[m][n] / max(1, m)
    text = checks.bp_text(bp)
    fixed_ok = all(checks.fixed_present(b['text'], text) for b in blocks) if blocks else True
    src_vals = [v for v in checks.extract_values(memo)] + checks.extract_values(allowed)   # 고정 문구(상속 포함)의 숫자는 허용
    got = checks.extract_values(text)
    lost = [v['raw'] for v in src_vals if not any(abs(x['value'] - v['value']) < 1e-9 and x['unit'] == v['unit'] for x in got)]
    def derived(x):
        # 원본의 숫자 몇 개(2~4개)를 더한 값은 합계로 본다(표의 단계별 기간 1 + 3 + 1 = 5개월 등)
        import itertools
        same = [v['value'] for v in src_vals if v['unit'] == x['unit']]
        if abs(sum(same) - x['value']) < 1e-9:
            return True
        if any(abs(sum(c) - x['value']) < 1e-9 for n in (2, 3, 4) for c in itertools.combinations(same[:12], n)):
            return True
        # 표의 칸은 단위가 머리글에만 있다('비용(백만원)' 아래 80 · 390 · 110). 메모에 적힌 숫자 그대로이거나 그 몇 개의 합이면 지어낸 숫자가 아니다
        m = re.match(r'[\d,]+(?:\.\d+)?', x['raw'])
        num = float(m.group(0).replace(',', '')) if m else None
        return num is not None and (any(abs(b - num) < 1e-9 for b in bare)
                                    or any(abs(sum(c) - num) < 1e-9 for n in (2, 3, 4) for c in itertools.combinations(bare, n)))
    bare = [float(n.replace(',', '')) for n in dict.fromkeys(re.findall(r'(?<![\d.,])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d,]*\.?\d)', memo))][-24:]      # 표는 메모 끝에 있다 — 뒤에서부터 24개까지
    new = [x['raw'] for x in got if x['unit'] not in ('일', '회') and not any(abs(x['value'] - v['value']) < 1e-9 for v in src_vals) and not derived(x)]
    gram = [c for c in engines.check(bp, (), form.get('style'), fixed) if c['id'] in ('date', 'long', 'end') and not c['ok']]   # 이 양식의 문체 기준
    # grammar(기준 이름)는 스킬 저장소의 evals에 올라간다 — 문장을 섞지 않는다. 걸린 문장은 화면용 grammar_detail에만 둔다.
    return {'struct': round(struct, 3), 'fixed': fixed_ok, 'lost': lost[:5], 'new': new[:5], 'grammar': [c['name'] for c in gram],
            'grammar_detail': [c['name'] + (f" — {c['detail']}" if c.get('detail') else '') for c in gram]}


def _criteria_pass(sc):
    return [sc['struct'] >= 0.95, sc['fixed'], not sc['lost'] and not sc['new'], not sc['grammar']]


@app.get('/api/skillgen/jobs')
@login_required
def skillgen_jobs():
    out = []
    for j in rows(g.con, "select * from skill_jobs where owner=? order by created desc limit 8", g.u['id']):
        d = J(j['skill'], {})
        rep = J(j['report'], {})
        out.append({'id': j['id'], 'stage': j['stage'], 'request': j['request'], 'name': d.get('name'), 'created': j['created'],
                    'auto_pass': rep.get('auto_pass') if rep else None})
    return ok(jobs=out)


@app.get('/api/skillgen/<jid>')
@login_required
def skillgen_get(jid):
    j = row(g.con, 'select * from skill_jobs where id=? and owner=?', jid, g.u['id'])
    if not j:
        abort(404)
    return ok(job={'id': j['id'], 'draft': J(j['skill']), 'analysis': J(j['analysis'], {}), 'report': J(j['report'], None), 'scope': j['scope'],
                   'stage': j['stage'], 'files': [{'id': u['id'], 'name': u['name'], 'drm': bool(u['drm']), 'heads': [], 'kind': u['kind']}
                                                  for u in _uploads(J(j['files'], []))]})


@app.post('/api/skillgen/<jid>/evaluate')
@login_required
def skillgen_evaluate(jid):
    """④ 충분한 검증: 대표 문서에서 만든 과제(메모 → 기대 구성·고정 문구·숫자)를 스킬 사용/미사용으로 채점."""
    j = row(g.con, 'select * from skill_jobs where id=? and owner=?', jid, g.u['id'])
    if not j:
        abort(404)
    b = request.json or {}
    draft = b.get('draft') or J(j['skill'])
    if (J(j['analysis'], {}) or {}).get('mode') == 'clone':
        return _evaluate_clone(j, draft, J(j['analysis'], {}))
    allsk = skills.all_skills()
    form = draft['forms'][0]
    blocks = [x for x in draft.get('blocks') or [] if x['id'] in (form.get('blocks') or [])] or draft.get('blocks') or []
    files = _uploads(J(j['files'], []))[:3]
    analysis = J(j['analysis'], {})
    if 'style' not in analysis:                 # 문체 재기 전에 분석해 둔 작업: 지금 대표 문서에서 잰다
        st = checks.measure_style([f['text'] or '' for f in _uploads(J(j['files'], []))])
        analysis['style'] = {**st, 'label': checks.style_label(st), 'default': checks.is_default_style(st)}
        if not analysis['style']['default'] and not form.get('style'):
            form['style'] = {k: st[k] for k in ('ending', 'date', 'max_len')}
        g.con.execute('update skill_jobs set analysis=? where id=?', (json.dumps(analysis, ensure_ascii=False), jid))
    errs = skills.validate(draft, allsk)
    # 상속 해석: 상위 스킬의 고정 문구·규칙도 함께
    parent_blocks, parent_rules = [], []
    for e in draft.get('extends') or []:
        if str(e).startswith('skill:') and e.split(':', 1)[1] in allsk:
            r = skills.resolve(e.split(':', 1)[1], allsk)
            parent_rules = r['rules']
            own = {x['text'] for x in blocks}
            parent_blocks = [{'heading': x.get('heading', ''), 'text': x['text']} for x in r['blocks'].values() if x['text'] not in own]
    rules = '\n'.join((draft.get('rules') or []) + parent_rules)
    with_t = {'name': form['name'], 'desc': form.get('desc', ''), 'outline': json.dumps(form['outline'], ensure_ascii=False),
              'fixed': json.dumps(blocks + parent_blocks, ensure_ascii=False), 'rules': rules, 'style': form.get('style')}
    without_t = {'name': '일반 문서', 'desc': '', 'outline': json.dumps(['개요', '주요 내용', '향후 계획'], ensure_ascii=False), 'fixed': '[]', 'rules': ''}
    tasks = []
    ctx = ai_ctx(fast=True)

    def memo_of(f):
        fixed_texts = [x['text'] for x in blocks]
        lines = [l.strip() for l in (f['text'] or '').splitlines() if l.strip() and not any(ft in l for ft in fixed_texts)]
        # 읽은 표가 있으면 표의 칸은 낱개 줄 대신 표 모양으로 준다 — '1개월'처럼 무엇의 숫자인지 모를 줄만 남으면 과제가 성립하지 않는다
        tbs = J(f.get('tables'), [])[:2]
        cells = {str(c).strip() for t in tbs for r in [t['cols']] + t['rows'] for c in r if str(c).strip()}
        # 숫자와 단위만 있는 줄(그려서 만든 표의 칸 등)은 무엇의 숫자인지 알 수 없으므로 과제에 넣지 않는다
        orphan = re.compile(r'[\d,.]+\s*' + checks.UNIT)
        keep = [l for l in lines if l not in cells and not orphan.fullmatch(l) and (checks.NUM_RX.search(l) or len(l) > 12)][:14]
        tables = ''.join(f"\n표 — {t.get('title', '')}\n" + ' | '.join(t['cols']) + '\n' + '\n'.join(' | '.join(r) for r in t['rows'][:10]) for t in tbs)
        return '다음 메모로 같은 종류의 문서를 써 줘.\n' + '\n'.join(keep) + tables

    results = [None] * len(files)

    def run(i, f):
        memo = memo_of(f)
        bw, mw = llm.blueprint(with_t, memo, [], ctx)
        bw = checks.enforce_fixed(bw, blocks + parent_blocks)
        bo, mo = llm.blueprint(without_t, memo, [], ctx)
        fx = [x['text'] for x in blocks + parent_blocks] + ((draft.get('checks') or {}).get('required') or [])
        for e in draft.get('extends') or []:      # 상위 스킬의 필수 문구도 글자 그대로 넣는 글
            if str(e).startswith('skill:') and e.split(':', 1)[1] in allsk:
                fx += skills.resolve(e.split(':', 1)[1], allsk)['checks']['required']
        allowed = chr(10).join(fx)
        results[i] = {'doc': f['name'], 'memo': memo, 'with': _bp_score(bw, form, blocks, memo, allowed, fx), 'without': _bp_score(bo, form, blocks, memo, allowed, fx),
                      'mode': mw['mode'], 'ms': mw['ms'] + mo['ms']}

    th = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(files)]
    for t in th:
        t.start()
    for t in th:
        t.join(timeout=600)
    tasks = [r for r in results if r]
    wsc = sum(sum(_criteria_pass(t['with'])) for t in tasks)
    osc = sum(sum(_criteria_pass(t['without'])) for t in tasks)
    full = 4 * max(1, len(tasks))
    pii = [e for e in errs if e.startswith('보안')]
    need = 1 if draft.get('scope') == 'user' else 3
    crit = [
        {'id': 'struct', 'name': '구성 재현(≥95%)', 'pass': bool(tasks) and all(t['with']['struct'] >= 0.95 for t in tasks),
         'detail': ', '.join(f"{t['with']['struct'] * 100:.0f}%" for t in tasks)},
        {'id': 'fixed', 'name': '고정 문구 글자 그대로', 'pass': bool(tasks) and all(t['with']['fixed'] for t in tasks), 'detail': f'{len(blocks)}개 블록'},
        {'id': 'numbers', 'name': '숫자·사실 보존', 'pass': bool(tasks) and all(not t['with']['lost'] and not t['with']['new'] for t in tasks),
         'detail': '; '.join(f"빠짐 {t['with']['lost']} 새 숫자 {t['with']['new']}" for t in tasks if t['with']['lost'] or t['with']['new'])},
        {'id': 'grammar', 'name': '보고 문법(3줄·명사형·날짜)' if checks.is_default_style(form.get('style')) else
            f"문체 — 대표 문서 기준({checks.style_label(form.get('style'))})", 'pass': bool(tasks) and all(not t['with']['grammar'] for t in tasks),
         'detail': '; '.join(', '.join(t['with'].get('grammar_detail') or t['with']['grammar']) for t in tasks if t['with']['grammar']),
         'public_detail': '; '.join(', '.join(t['with']['grammar']) for t in tasks if t['with']['grammar'])},
        {'id': 'security', 'name': '보안(실명·연락처·계좌 없음)', 'pass': not pii, 'detail': '; '.join(pii)},
        {'id': 'compare', 'name': '효과 비교(스킬 사용 > 미사용)', 'pass': wsc > osc, 'detail': f'사용 {wsc}/{full} · 미사용 {osc}/{full}'},
        {'id': 'human', 'name': f'사람 확인(시범 작성 {need}건 👍)', 'pass': False, 'detail': '아래에서 확인', 'human': need},
    ]
    report = {'criteria': crit, 'tasks': tasks, 'with_score': wsc, 'without_score': osc, 'full': full, 'errors': errs,
              'auto_pass': all(c['pass'] for c in crit if c['id'] != 'human') and not errs, 'style': analysis.get('style'),
              # 강제 등록: 품질 기준 미통과는 사유를 남기고 넘길 수 있지만, 스킬 파일 검사 오류와 보안(개인정보)은 넘길 수 없다
              'can_force': not errs and not pii, 'upload': _upload_notice(draft)}
    g.con.execute("update skill_jobs set skill=?, report=?, stage='evaluated', updated=? where id=?",
                  (json.dumps(draft, ensure_ascii=False), json.dumps(report, ensure_ascii=False), now(), jid))
    log(g.u['name'], f"스킬 빌더 ④ 검증 — {draft['id']} · 사용 {wsc}/{full} vs 미사용 {osc}/{full} · 자동 기준 {'통과' if report['auto_pass'] else '미통과'}")
    return ok(report=report, draft=draft, analysis=analysis)


def _clone_md(d, report):
    form = d['forms'][0]
    fill = form['fill']
    fid = (report or {}).get('fidelity') or {}
    rows = '\n'.join(f"| {sec['heading']} | {f.get('label', f['key'])} | {'필수' if f.get('required') else ''} | {f.get('hint', '')} |" for sec in fill['sections'] for f in sec['fields'])
    score = '\n'.join(f"| 문서 {i + 1} | {x['text'][0]}/{x['text'][1]} | {x['struct'][0]}/{x['struct'][1]} | {x['shape'][0]}/{x['shape'][1]} | {'같음' if x['identical'] else '다름'} |"
                      for i, x in enumerate(fid.get('docs') or []))
    v = d.get('verification') or {}
    forced = (f"\n> ⚠️ **검증 미통과 상태로 강제 등록됨** ({v.get('date', '')}, {v.get('by', '')})\n> - 미통과: {' / '.join(v.get('failed') or [])}\n> - 사유: {v.get('reason', '')}\n"
              if v.get('status') == 'forced' else '')
    return (f"---\nname: {d['id']}\ndescription: {d['name']} — 한글 서식의 칸을 채워 같은 모양의 문서를 만든다(복제형). 서식의 글과 모양은 바꾸지 않고 칸 값만 넣는다.\n---\n\n"
            f"# {d['name']}\n\n- 방식: **복제형** — 대표 문서를 서식(`{fill['template']}`)으로 삼고, 문서마다 바뀌는 칸만 비웠다. 문서를 다시 그리지 않는다.\n"
            f"- 칸 채우기 부품: 전사 스킬 `{fill['engine']}` (Inspect · TemplateMaker · FillRenderer, hwplib)\n"
            f"- 서식의 고정 글: {fid.get('fixed_chars', '-')}자 · 칸: {fid.get('slots', '-')}개\n\n"
            f"## 칸\n| 묶음 | 이름 | 필수 | 적는 법 |\n|---|---|---|---|\n{rows}\n\n"
            f"## 쓰는 법\n1. 요청과 자료에서 칸 값만 찾는다. 서식에 든 문장은 쓰지 않는다.\n2. 자료에 없는 값은 비워 둔다. 금액 · 날짜 · 이름을 짐작하지 않는다.\n"
            f"3. 값을 `values.json`(`fields`)으로 넘겨 `FillRenderer 서식.hwp values.json 결과.hwp`로 만든다.\n\n"
            f"## 되만들기 시험\n서식에 각 대표 문서의 칸 값을 넣어 다시 만들고 원본과 비교했다. 대표 문서 파일과 칸 값은 저장소에 올리지 않았다.\n\n"
            f"| 대표 문서 | 글자 | 구성 | 모양 | 원본과 |\n|---|---|---|---|---|\n{score}\n{forced}")


def _skill_md(d, analysis):
    form = d['forms'][0]
    blocks = '\n'.join(f"- {b.get('heading') or '고정'}: {b['text']}" for b in d.get('blocks') or []) or '- (없음)'
    rules = '\n'.join(f'- {r}' for r in d.get('rules') or []) or '- (상위 스킬 규칙을 따른다)'
    base = (analysis or {}).get('base') or {}
    st = (analysis or {}).get('style') or {}
    style = (f"- 문체(대표 문서에서 잼 — 전사 보고 문법 대신 이 기준으로 쓰고 검수한다): {checks.style_label(form['style'])}"
             + (f" · 근거: {st['basis']}" if st.get('basis') else '') + '\n') if form.get('style') else '- 문체: 전사 보고 문법(명사형 종결 · 2026. 10. 28 · 90자)을 그대로 따른다.\n'
    v = d.get('verification') or {}
    forced = (f"\n> ⚠️ **검증 미통과 상태로 강제 등록됨** ({v.get('date', '')}, {v.get('by', '')})\n> - 미통과: {' / '.join(v.get('failed') or [])}\n> - 사유: {v.get('reason', '')}\n"
              if v.get('status') == 'forced' else '')
    return (f"---\nname: {d['id']}\ndescription: {d['name']} — {form['desc']}. 상위 스킬과 전사 공용 스킬을 상속하고 이 부서의 구성·고정 문구·규칙만 더한다.\n---\n\n"
            f"# {d['name']}\n\n- 상속: {', '.join(d['extends'])}. 전사 지침은 그대로 따르고 아래만 덧붙인다.\n"
            f"- 기반 양식: {base.get('name', '-')} (유사도 {base.get('similarity', '-')})\n- 형식: {FMT[form['fmt']]}\n{style}"
            f"- 구성(이 순서와 제목 그대로): {' → '.join(form['outline'])}\n\n## 고정 문구(글자 그대로)\n{blocks}\n\n## 작성 규칙\n{rules}\n\n"
            f"## 검증\n대표 문서에서 만든 과제(메모 → 기대 구성·고정 문구·숫자)로 스킬 사용/미사용을 채점했다. `evals/`에는 기대 구성과 채점 결과만 있다. "
            f"대표 문서 파일과 과제 메모(대표 문서에서 뽑은 줄)는 저장소에 올리지 않았다.\n{forced}")


def _skill_files(draft, report, analysis):
    """등록할 때 스킬 저장소에 올리는 파일 묶음.
    대표 문서의 원문은 올리지 않는다: 검증 과제 메모(대표 문서에서 뽑은 줄)는 이 PC의 작업 기록에만 두고,
    저장소에는 기대 구성·고정 문구와 채점 결과(빠진 숫자·새 숫자는 값이 아니라 건수)만 올린다."""
    path = skills.skill_dir(draft)
    if (analysis or {}).get('mode') == 'clone':
        # 복제형: 서식 파일(대표 문서에서 칸 값만 비운 것)이 올라간다. 대표 문서 파일 · 칸 값 · 바꿈표는 올리지 않는다
        tpl = open(analysis['clone']['template'], 'rb').read()
        if not tpl.startswith(clone.OLE):
            raise RuntimeError('서식 파일이 한글 형식이 아닙니다(이 PC의 보호 도구가 암호화했을 수 있음). ② 분석부터 다시 해 주세요')
        fid = report.get('fidelity') or {}
        return {f'{path}/kosoe-skill.yaml': skills.dump_skill(draft), f'{path}/SKILL.md': _clone_md(draft, report),
                f"{path}/{draft['forms'][0]['fill']['template']}": tpl,
                f'{path}/evals/roundtrip.yaml': yaml.safe_dump(
                    {'note': '되만들기 시험 — 서식에 각 대표 문서의 칸 값을 넣어 다시 만들고 원본과 비교한 줄 수(같은 줄/전체). 대표 문서와 칸 값은 저장소에 올리지 않는다.',
                     'slots': fid.get('slots'), 'fixed_chars': fid.get('fixed_chars'), 'slot_chars': fid.get('slot_chars'),
                     'docs': [{'doc': i + 1, 'text': x['text'], 'struct': x['struct'], 'shape': x['shape'], 'identical': x['identical']}
                              for i, x in enumerate(fid.get('docs') or [])]}, allow_unicode=True, sort_keys=False)}
    files = {f'{path}/kosoe-skill.yaml': skills.dump_skill(draft), f'{path}/SKILL.md': _skill_md(draft, analysis)}
    for i, t in enumerate(report.get('tasks') or [], 1):
        files[f'{path}/evals/case-{i}/case.yaml'] = yaml.safe_dump(
            {'memo': {'kept': 'local', 'lines': len([l for l in (t.get('memo') or '').splitlines() if l.strip()]),
                      'note': '과제 메모(대표 문서에서 뽑은 줄)는 저장소에 올리지 않는다. 등록한 PC의 작업 기록에만 있다.'},
             'expect': {'outline': draft['forms'][0]['outline'], 'fixed': [x['text'] for x in draft.get('blocks') or []]},
             'score': {'with': checks.public_score(t['with']), 'without': checks.public_score(t['without'])}}, allow_unicode=True, sort_keys=False)
    return files


def _upload_notice(draft, template=None):
    """등록하면 저장소에 무엇이 올라가는지 — 화면에 미리 보여 준다(저장소가 공개인지, 스킬 글에 회사 이름으로 보이는 글이 있는지)."""
    if template:                                # 복제형: 서식 파일의 고정 글이 그대로 올라간다
        names = checks.company_names(draft)
        try:
            for line in clone.text_lines(clone.read(template)):
                names += [m.group(0) for m in llm.MASK_RX['고객사명'].finditer(line) if '가상' not in line and m.group(0) not in names]
        except Exception:
            pass
        return {'visibility': skills.visibility(), 'repo': skills.SLUG, 'names': names[:8], 'clone': True,
                'writable': skills.can_push(),     # False면 화면이 등록 버튼을 막고 이유를 알린다(None = 확인 못 함)
                'files': ['kosoe-skill.yaml (칸 정의)', 'SKILL.md', 'templates/form.hwp (대표 문서에서 칸 값만 비운 서식 — 고정된 글과 모양이 그대로 들어 있음)',
                          'evals/roundtrip.yaml (재현도 점수)'],
                'not_uploaded': '대표 문서 파일 · 칸에 들어 있던 값 · 바꿈표'}
    return {'visibility': skills.visibility(), 'repo': skills.SLUG, 'names': checks.company_names(draft),
            'writable': skills.can_push(),         # False면 화면이 등록 버튼을 막고 이유를 알린다(None = 확인 못 함)
            'files': ['kosoe-skill.yaml (구성 · 고정 문구 · 규칙)', 'SKILL.md', 'evals/case-N/case.yaml (기대 구성 · 채점 결과)'],
            'not_uploaded': '대표 문서 파일과 검증 과제 메모(대표 문서에서 뽑은 줄)'}


@app.post('/api/skillgen/<jid>/submit')
@login_required
def skillgen_submit(jid):
    j = row(g.con, 'select * from skill_jobs where id=? and owner=?', jid, g.u['id'])
    if not j:
        abort(404)
    b = request.json or {}
    draft = J(j['skill'])
    report = J(j['report'], {})
    if not report:
        return err('먼저 ④ 검증을 실행해 주세요')
    thumbs = int(b.get('thumbs') or 0)
    need = next((c['human'] for c in report['criteria'] if c['id'] == 'human'), 3)
    for c in report['criteria']:
        if c['id'] == 'human':
            c['pass'] = thumbs >= need
            c['detail'] = f'{thumbs}/{need}건 확인'
    failed = [c for c in report['criteria'] if not c['pass']]
    draft.pop('verification', None)
    if failed:
        # 미통과 강제 등록: 사유를 남기면 품질 기준(구성·고정 문구·숫자·문체·효과 비교·사람 확인)은 넘길 수 있다.
        # 스킬 파일 검사 오류(스키마·상속·잠금)와 보안(개인정보)은 넘길 수 없다.
        if not b.get('force'):
            return err('검증 기준을 모두 통과해야 등록할 수 있습니다' + ('' if report.get('auto_pass') else ' (자동 채점 미통과)'))
        if report.get('errors') or any(c['id'] in ('security', 'f_clean') for c in failed):
            return err('스킬 파일 검사 오류 · 보안(개인정보) · 서식에 남은 값은 강제 등록으로 넘길 수 없습니다: '
                       + '; '.join((report.get('errors') or []) + [c['detail'] for c in failed if c['id'] in ('security', 'f_clean') and c.get('detail')])[:300])
        reason = re.sub(r'\s+', ' ', str(b.get('reason') or '')).strip()
        if len(reason) < 5:
            return err('강제 등록 사유를 5자 이상 적어 주세요 (PR과 스킬 파일에 남습니다)')
        who = f"{g.u['name']} {g.u['title']}".strip()
        names = [c['name'] for c in failed]
        report['forced'] = {'by': who, 'reason': reason[:200], 't': now(),
                            'failed': [c['name'] + (f' — {d}' if d else '') for c in failed for d in [_public_detail(c, report)]]}
        draft['verification'] = {'status': 'forced', 'failed': names, 'reason': reason[:200], 'by': who, 'date': core.today_kr()}
        errs = skills.validate(draft, skills.all_skills())
        if errs:                                # 사유에 개인정보가 들어간 경우 등
            return err('검사 실패: ' + '; '.join(errs))
    analysis = J(j['analysis'], {})
    path = skills.skill_dir(draft)
    try:
        files = _skill_files(draft, report, analysis)
    except (OSError, RuntimeError) as e:
        return err(str(e))
    r = _open_skill_request('new', {**draft, '_path': path}, files, g.u, report=report, note=j['request'] or '')
    g.con.execute("update skill_jobs set stage='submitted', skill=?, report=?, request_id=?, updated=? where id=?",
                  (json.dumps(draft, ensure_ascii=False), json.dumps(report, ensure_ascii=False), r['id'], now(), jid))
    if report.get('forced'):
        log(g.u['name'], f"스킬 빌더 ⑤ 검증 미통과 강제 등록 — {draft['id']} · 미통과 {len(failed)}건 · 사유: {report['forced']['reason'][:60]}")
    return ok(request=req_view(r, g.u))


# ───────────── 등록 요청 · 승인 ─────────────
def _approver_ok(req, u):
    st = req['stage']
    if st == 'lead' and not core.lead_of(g.con, req['team']):      # 그 팀에 팀장이 없으면 부서 관리자가 대신 승인한다
        st = 'dept'
    if st == 'dept' and not row(g.con, "select 1 from users where dept=? and role='deptAdmin'", req['dept']):   # 부서 관리자가 없으면 전사 관리자가
        st = 'corp'
    return ((st == 'lead' and u['role'] == 'lead' and u['team'] == req['team']) or
            (st == 'dept' and u['role'] == 'deptAdmin' and u['dept'] == req['dept']) or
            (st == 'corp' and u['role'] == 'corpAdmin'))


def req_view(r, u):
    o = dict(r)
    for k in ('outline', 'fields', 'fixed', 'history'):
        o[k] = J(r[k], [])
    o['stages'] = SCOPE_STAGES.get(r['scope'], ['lead'])
    o['stage_name'] = STAGE_NAME.get(r['stage'], r['stage'])
    o['can_decide'] = _approver_ok(r, u)
    me = core.get_user(g.con, r['requester'])
    o['requester_name'] = f"{me['name']} {me['title']}" if me else r['requester']
    o['note'] = J(r['note'], {})
    o['kind_name'] = KIND_NAME.get(o['note'].get('kind'), '등록')
    if o['note'].get('kind') == 'promote' and r['stage'] not in ('done', 'rejected'):     # 승인권자가 카드에서 볼 샘플 그림(아직 옮기기 전 자리)
        o['samples'] = {t['id']: _sample_files(_sample_dir(t)) for t in rows(g.con, 'select * from templates where id like ?', o['note']['sid'] + ':%')}
    return o


@app.get('/api/requests')
@login_required
def req_list():
    u = g.u
    out = []
    for r in rows(g.con, 'select * from requests order by created desc'):
        mine = r['requester'] == u['id']
        if mine or _approver_ok(r, u) or u['role'] in ('corpAdmin', 'security') or (u['role'] == 'lead' and r['team'] == u['team']) \
                or (u['role'] == 'deptAdmin' and r['dept'] == u['dept']):
            out.append(req_view(r, u))
    return ok(requests=out)


def _advance(r, u, approve, note):
    hist = J(r['history'], [])
    stages = SCOPE_STAGES.get(r['scope'], ['lead'])
    who = f"{u['name']} {u['title']}".strip()
    meta = J(r['note'], {})
    if not approve:
        hist.append({'t': now(), 'who': who, 'act': STAGE_NAME[r['stage']].replace('승인', '반려').replace('자동 검사', '자동 검사 실패'), 'note': note})
        g.con.execute('update requests set stage=?, history=?, updated=? where id=?', ('rejected', json.dumps(hist, ensure_ascii=False), now(), r['id']))
        threading.Thread(target=skills.close, args=(r['pr_number'], note or '사유 없음'), daemon=True).start()
        log(u['name'] or '시스템', f"{KIND_NAME.get(meta.get('kind'), '등록')} 반려 — {r['name']}: {note}")
        return
    hist.append({'t': now(), 'who': who, 'act': STAGE_NAME[r['stage']], 'note': note})
    skills.comment(r['pr_number'], f"✅ **{STAGE_NAME[r['stage']]}** — {who}" + (f"\n\n> {note}" if note else '') + '\n\n_코쇠오피스 승인 기록_')
    i = stages.index(r['stage'])
    if i + 1 < len(stages):
        nxt = stages[i + 1]
        g.con.execute('update requests set stage=?, history=?, updated=? where id=?', (nxt, json.dumps(hist, ensure_ascii=False), now(), r['id']))
        return
    try:
        tag = skills.merge(r['pr_number'], r['branch'], meta['sid'], meta['version'], who)
    except Exception as e:
        hist.append({'t': now(), 'who': '시스템', 'act': '병합 실패', 'note': str(e)[:200]})
        g.con.execute('update requests set history=?, updated=? where id=?', (json.dumps(hist, ensure_ascii=False), now(), r['id']))
        log('시스템', f'병합 실패: {e}')
        raise
    hist.append({'t': now(), 'who': '시스템', 'act': f'병합 · 태그 {tag}', 'note': '다음 문서부터 반영'})
    g.con.execute('update requests set stage=?, history=?, updated=? where id=?', ('done', json.dumps(hist, ensure_ascii=False), now(), r['id']))
    g.con.commit()
    sync_forms(force=True, max_age=30)             # merge()가 방금 당겨 왔으므로 다시 받지 않고 양식만 다시 만든다
    log(u['name'] or '시스템', f"{KIND_NAME.get(meta.get('kind'), '등록')} 완료 — {r['name']} · {tag}")


@app.post('/api/requests/<rid>/decide')
@login_required
def req_decide(rid):
    r = row(g.con, 'select * from requests where id=?', rid)
    if not r:
        abort(404)
    if not _approver_ok(r, g.u):
        return err('지금 단계의 승인권자가 아닙니다', 403)
    b = request.json or {}
    try:
        _advance(r, g.u, bool(b.get('approve')), (b.get('note') or '').strip())
    except Exception as e:
        return err(f'저장소 병합 실패: {e}', 500)
    return ok(request=req_view(row(g.con, 'select * from requests where id=?', rid), g.u))


# ───────────── 인터넷망 사용 신청 ─────────────
def ireq_view(r, u):
    o = dict(r)
    o['feats'] = J(r['feats'], [])
    x = core.get_user(g.con, r['uid'])
    o['user'] = f"{x['name']} {x['title']} · {x['team']}" if x else r['uid']
    o['can_decide'] = _ireq_approver(r, u) and r['status'] == 'wait'
    o['can_revoke'] = r['status'] == 'ok' and (u['role'] == 'security' or _ireq_approver(r, u))
    return o


def _ireq_approver(r, u):
    x = core.get_user(g.con, r['uid'])
    if x['role'] in ('lead', 'deptAdmin', 'corpAdmin', 'security') or not core.lead_of(g.con, x['team']):
        return u['role'] == 'security' and u['id'] != x['id']
    return u['role'] == 'lead' and u['team'] == x['team']


@app.get('/api/ireq')
@login_required
def ireq_list():
    out = [ireq_view(r, g.u) for r in rows(g.con, 'select * from ireq order by created desc')
           if r['uid'] == g.u['id'] or _ireq_approver(r, g.u) or g.u['role'] == 'security']
    pol = {r['k']: J(r['v'], r['v']) for r in rows(g.con, 'select * from policy')}
    return ok(requests=out, policy=pol, active=core.inet_active(g.con, g.u['id']))


@app.post('/api/ireq')
@login_required
def ireq_new():
    b = request.json or {}
    mx = int(row(g.con, "select v from policy where k='maxDays'")['v'])
    days = max(1, min(int(b.get('days') or 7), mx))
    purpose = (b.get('purpose') or '').strip()
    if len(purpose) < 5:
        return err('사용 목적을 5자 이상 적어 주세요')
    if row(g.con, "select id from ireq where uid=? and status='wait'", g.u['id']):
        return err('이미 대기 중인 신청이 있습니다')
    iid = core.new_id('i')
    g.con.execute('insert into ireq values(?,?,?,?,?,?,?,?,?,?)', (iid, g.u['id'], g.u['team'], purpose, days,
                                                               json.dumps(b.get('feats') or ['ai'], ensure_ascii=False), 'wait', '', '', now()))
    log(g.u['name'], f'인터넷망 사용 신청 — {days}일 · {purpose}')
    return ok()


@app.post('/api/ireq/<iid>/decide')
@login_required
def ireq_decide(iid):
    r = row(g.con, 'select * from ireq where id=?', iid)
    if not r:
        abort(404)
    b = request.json or {}
    if b.get('revoke'):
        if not ireq_view(r, g.u)['can_revoke']:
            return err('회수 권한이 없습니다', 403)
        g.con.execute("update ireq set status='revoked', decided_by=? where id=?", (g.u['name'], iid))
        g.con.execute("update users set net='closed' where id=?", (r['uid'],))
        log(g.u['name'], f"인터넷망 권한 회수 — {core.get_user(g.con, r['uid'])['name']}")
        return ok()
    if not (_ireq_approver(r, g.u) and r['status'] == 'wait'):
        return err('승인 권한이 없습니다', 403)
    if b.get('approve'):
        days = max(1, min(int(b.get('days') or r['days']), int(row(g.con, "select v from policy where k='maxDays'")['v'])))
        g.con.execute("update ireq set status='ok', days=?, until=?, decided_by=? where id=?", (days, core.until_date(days), g.u['name'], iid))
        log(g.u['name'], f"인터넷망 사용 승인 — {core.get_user(g.con, r['uid'])['name']} {days}일 (~{core.until_date(days)})")
    else:
        g.con.execute("update ireq set status='no', decided_by=? where id=?", (g.u['name'], iid))
        log(g.u['name'], f"인터넷망 사용 반려 — {core.get_user(g.con, r['uid'])['name']}")
    return ok()


@app.put('/api/policy')
@login_required
def policy_put():
    if g.u['role'] not in ('security', 'corpAdmin'):
        return err('권한이 없습니다', 403)
    b = request.json or {}
    if 'maxDays' in b:
        g.con.execute("update policy set v=? where k='maxDays'", (str(max(1, min(int(b['maxDays']), 90))),))
    if 'mask' in b:
        g.con.execute("update policy set v=? where k='mask'", (json.dumps([m for m in b['mask'] if m in llm.MASK_RX], ensure_ascii=False),))
    log(g.u['name'], '보안 정책 변경')
    return ok()


@app.post('/api/mask-test')
@login_required
def mask_test():
    pol = J(row(g.con, "select v from policy where k='mask'")['v'], [])
    m = llm.Masker(pol)
    return ok(masked=m.mask((request.json or {}).get('text', '')), map=m.map)


# ───────────── 대시보드 · 로그 · 시연 ─────────────
@app.get('/api/dashboard')
@login_required
def dashboard():
    c = g.con
    docs_ = rows(c, 'select * from docs')
    files = rows(c, 'select * from doc_files')
    saved, real = 0, 0
    for d in docs_:
        m = J(d['made'], {})
        if m.get('manual'):
            saved += m['manual'] - m['minutes']
            real += 1
    llm_n = sum(1 for f in files if J(f['llm'], {}).get('mode') == 'llm')
    by_fmt = {k: sum(1 for f in files if f['fmt'] == k) for k in FMT}
    checks_ok = sum(1 for f in files if all(x['ok'] or x['id'] in ('todo', 'cross') for x in J(f['checks'], [])))
    tops = rows(c, 'select name, uses, fmt, scope from templates order by uses desc limit 8')
    by_skill = {}
    for f in files:
        for s in J(f['resolution'], {}).get('skills') or []:
            by_skill[s] = by_skill.get(s, 0) + 1
    return ok(kpi={'docs': len(docs_), 'files': len(files), 'made': real, 'saved_h': round(saved / 60, 1), 'templates': len(rows(c, 'select id from templates')),
                   'pending': len(rows(c, "select id from requests where stage in ('lead','dept','corp')")),
                   'inet': len(rows(c, "select id from ireq where status='ok'")), 'llm_rate': round(100 * llm_n / len(files)) if files else 0,
                   'check_rate': round(100 * checks_ok / len(files)) if files else 0, 'skills': len(skills.all_skills())},
              by_fmt=by_fmt, tops=tops, by_skill=by_skill,
              avg_ms={k: round(sum(f['elapsed_ms'] for f in files if f['fmt'] == k) / max(1, by_fmt[k])) for k in FMT})


@app.get('/api/events')
@login_required
def events():
    return ok(events=rows(g.con, 'select * from events order by id desc limit 200'))


@app.post('/api/sync')
@login_required
def sync():
    st = sync_forms(force=True)
    log(g.u['name'], f"스킬 저장소 당겨오기 — {st['head'][:7]}")
    return ok(repo={k: v for k, v in st.items() if k != 'synced'})


def boot():
    core.init_db()
    load_ai_choice()
    sync_forms(force=True)
    threading.Thread(target=corp.warm, kwargs={'log': lambda m: None}, daemon=True).start()


def reset_demo(user_skills=False):
    """시연 초기화: 로컬 기록(문서·첨부·요청·작업·로그)과 결과물을 비우고, 스킬 저장소의 열린 PR을 닫는다(병합된 이력·태그는 그대로)."""
    import shutil
    core.init_db()
    con = db()
    for t in ('docs', 'doc_files', 'compose', 'uploads', 'requests', 'skill_jobs', 'ireq', 'events', 'uses'):
        con.execute(f'delete from {t}')
    con.execute("update users set net='closed'")
    con.execute('insert into events(t,who,what) values(?,?,?)', (now(), '시스템', '시연 초기화'))
    con.commit()
    con.close()
    for p in (engines.OUT, UP, engines.JOBS):
        shutil.rmtree(p, ignore_errors=True)
        os.makedirs(p, exist_ok=True)
    skills.demo_cleanup(user_skills)
    sync_forms(force=True, max_age=10)


# ───────────── 시연 도우미 ─────────────
SEED = os.path.join(core.ROOT, 'seed', 'out')


@app.get('/api/demo/files')
@login_required
def demo_files():
    out = []
    for dp, _, fns in os.walk(SEED):
        for f in sorted(fns):
            rel = os.path.relpath(os.path.join(dp, f), SEED).replace(os.sep, '/')
            out.append({'name': rel, 'size': os.path.getsize(os.path.join(dp, f))})
    return ok(files=out, ready=bool(out))


@app.post('/api/demo/seed')
@login_required
def demo_seed():
    import importlib.util
    spec = importlib.util.spec_from_file_location('make_seed', os.path.join(core.ROOT, 'seed', 'make_seed.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.main(SEED)
    log(g.u['name'], '시연 자료 만들기 (seed/out)')
    return demo_files()


@app.post('/api/demo/attach')
@login_required
def demo_attach():
    import shutil
    out = []
    for rel in (request.json or {}).get('names') or []:
        src = os.path.normpath(os.path.join(SEED, rel))
        if not src.startswith(os.path.normpath(SEED)) or not os.path.isfile(src):
            continue
        name = os.path.basename(src)
        uid = core.new_id('f')
        path = os.path.join(UP, uid + '_' + re.sub(r'[^\w.\-가-힣]', '_', name))
        shutil.copy(src, path)
        r = extract.read(path, name)
        g.con.execute('insert into uploads values(?,?,?,?,?,?,?,?,?)', (uid, g.u['id'], name, path, r['kind'], r['text'],
                                                                      json.dumps(r['tables'], ensure_ascii=False), int(r['drm']), now()))
        out.append({'id': uid, 'name': name, 'kind': r['kind'], 'drm': r['drm'], 'tables': r['tables'][:3], 'heads': r['heads'], 'chars': len(r['text']),
                    'text': (r['text'] or '')[:4000]})
        time.sleep(0.002)
    log(g.u['name'], f"시연 자료 첨부 — {', '.join(o['name'] for o in out)}")
    return ok(uploads=out)


@app.post('/api/demo/warm')
@login_required
def demo_warm():
    """시연 전 예열: 엔진 3종을 한 번씩 돌려 백신 첫 검사·디스크 캐시를 미리 끝낸다."""
    bp = {'title': '예열', 'sections': [{'heading': '개요', 'items': [{'label': '목적', 'text': '시연 전 예열', 'children': []}], 'table': None}]}
    out = {}
    for fmt in ('hwp', 'ppt', 'web'):
        t0 = time.time()
        try:
            engines.make(fmt, bp, {'name': '예열', 'desc': ''}, {'dept': '예열', '담당': '예열'}, 'warm', 1)
            out[fmt] = round(time.time() - t0, 1)
        except Exception as e:
            out[fmt] = str(e)[:80]
    st = llm.ping() if request.args.get('ai') else {}
    log(g.u['name'], f'시연 예열 — {out}' + (f" · AI {st.get('ms')}ms" if st.get('ok') else ''))
    return ok(sec=out, ai=st)


@app.post('/api/demo/reset')
@login_required
def demo_reset():
    g.con.commit()
    g.con.close()
    g.pop('con', None)
    reset_demo(bool((request.json or {}).get('user_skills')))
    session.clear()
    return ok()


if __name__ == '__main__':
    import sys
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding='utf-8', errors='replace')
    if '--reset' in sys.argv:
        reset_demo()
        print('시연 데이터를 초기화했습니다.')
    port = int(os.environ.get('PORT') or os.environ.get('KOSOE_PORT') or 8810)
    boot()
    print(f"코쇠오피스 — http://localhost:{port}  (AI: {llm.display() + ' 연결' if llm.available() else ai_state()['detail'] + ' → 규칙 기반 보조 모드'}"
          f" · 스킬 저장소 {skills.STATE['mode']} {skills.STATE['head'][:7]})")
    app.run(host='127.0.0.1', port=port, debug=False, threaded=True)
