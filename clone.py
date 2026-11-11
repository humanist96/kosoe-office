"""복제형 스킬 — 같은 종류의 한글 문서를 맞대어 바뀌는 칸을 찾고, 원본 파일을 서식으로 삼아 되만든다.

AI가 문서를 다시 그리지 않는다. 문서의 글자·모양은 코드가 원본에서 그대로 가져오고, 문서마다 바뀌는 자리만 칸({{이름}})으로 비운다.

  ① 읽기      inspect · parse   한글 파일 → 구조 줄(문단 · 표 · 칸 + 문단 모양 · 글자 모양 번호 + 위치)
  ② 맞대기    analyze           문서 2건 이상을 줄 단위로 겹쳐, 글이 같은 줄은 고정 · 다른 줄은 낱말 단위로 비교해 칸을 찾는다
  ④ 서식      build             기준 문서에 바꿈표를 적용해 칸 토큰이 든 서식(.hwp)을 만든다
  ⑤ 되만들기  remake · compare  서식에 각 문서의 칸 값을 넣어 다시 만들고 원본과 글자 · 구성 · 모양을 비교한다

한글 파일을 읽고 쓰는 부품(Inspect · TemplateMaker · FillRenderer, hwplib)은 전사 스킬 koscom-hwp-pb-contract 의 것을 그대로 쓴다.
③ 칸 이름 붙이기(AI)는 llm.name_slots, 화면·등록은 app.py 가 맡는다.
"""
import difflib
import os
import re
import subprocess

import checks
import corp

ENGINE = 'koscom-hwp-pb-contract'          # 칸 채우기 부품이 든 전사 스킬(잠금 파일의 kind: hwp-fill)
OLE = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
MIN_FIXED = 0.5                             # 고정된 글이 이 비율보다 적으면 복제형으로 만들지 않는다(조립형이 맞는 문서)
PUA = re.compile('[\ue000-\uf8ff]')


def ready():
    return bool(corp.info(ENGINE))


def _cp():
    root = corp.path(ENGINE)
    f = corp.form_of(ENGINE)
    return os.pathsep.join(os.path.join(root, *p.split('/')) for p in (f.get('lib') or 'lib/hwplib-1.1.9.jar', f.get('jar') or 'scripts/koscom-hwp-fill.jar'))


def _java(*args, timeout=120):
    r = subprocess.run(['java', '-Dfile.encoding=UTF-8', '-cp', _cp(), *args], capture_output=True, timeout=timeout)
    return r.returncode, r.stdout.decode('utf-8', 'replace') + r.stderr.decode('utf-8', 'replace')


# ───────────── ① 읽기 — 구조 줄 ─────────────
P_RX = re.compile(r'^(\s*)(#\d+|p\d+|tb\d+)( \[PAGEBREAK\])? ps(\d+) st(\d+) cs\[([^\]]*)\] seg=(true|false) "(.*)$', re.S)
T_RX = re.compile(r'^(\s*)ctrl(\d+) TABLE (\d+)x(\d+) bf(\d+) h=(\d+)\s*$')
C_RX = re.compile(r'^(\s*)cell\((\d+),(\d+)\) bf(\d+) span(\d+)x(\d+)\s*$')
X_RX = re.compile(r'^(\s*)ctrl(\d+) (.+?)\s*$')


def inspect(path):
    code, out = _java('Inspect', path)
    if code != 0:
        raise RuntimeError('한글 파일을 읽지 못했습니다: ' + out.strip()[-200:])
    return out.splitlines()


def parse(lines):
    """Inspect 출력 → 마디 목록. 마디 = {kind: p|table|cell|ctrl, sig(구성), shape(모양), text, top(문단 번호), addr(위치)}"""
    nodes, stack = [], []          # stack: [(들여쓰기, 종류, 정보)]
    for raw in lines:
        m = P_RX.match(raw)
        if m and raw.rstrip().endswith('"'):
            ind = len(m.group(1))
            while stack and stack[-1][0] >= ind:
                stack.pop()
            label = m.group(2)
            text = m.group(8).rstrip()[:-1]
            info = {'label': label, 'tables': 0}
            stack.append((ind, 'p', info))
            top = next((int(s[2]['label'][1:]) for s in stack if s[1] == 'p' and s[2]['label'].startswith('#')), -1)
            path = [(s[1], s[2].get('ord') if s[1] == 't' else s[2].get('rc') if s[1] == 'c' else s[2].get('label')) for s in stack]
            nodes.append({'kind': 'p', 'ind': ind, 'top': top, 'path': path, 'text': text,
                          'sig': f"{' ' * ind}{'#' if label.startswith('#') else label}{m.group(3) or ''}",
                          'shape': f'ps{m.group(4)} st{m.group(5)} cs[{m.group(6)}] seg={m.group(7)}'})
            continue
        m = T_RX.match(raw)
        if m:
            ind = len(m.group(1))
            while stack and stack[-1][0] >= ind:
                stack.pop()
            par = next((s[2] for s in reversed(stack) if s[1] == 'p'), {'tables': 0})
            stack.append((ind, 't', {'ord': par['tables']}))
            par['tables'] += 1
            nodes.append({'kind': 'table', 'ind': ind, 'text': None, 'sig': f"{' ' * ind}ctrl{m.group(2)} TABLE {m.group(3)}x{m.group(4)}",
                          'shape': f'bf{m.group(5)} h={m.group(6)}'})
            continue
        m = C_RX.match(raw)
        if m:
            ind = len(m.group(1))
            while stack and stack[-1][0] >= ind:
                stack.pop()
            stack.append((ind, 'c', {'rc': (int(m.group(2)), int(m.group(3)))}))
            nodes.append({'kind': 'cell', 'ind': ind, 'text': None, 'sig': f"{' ' * ind}cell({m.group(2)},{m.group(3)}) span{m.group(5)}x{m.group(6)}",
                          'shape': f'bf{m.group(4)}'})
            continue
        m = X_RX.match(raw)
        if m:
            ind = len(m.group(1))
            while stack and stack[-1][0] >= ind:
                stack.pop()
            stack.append((ind, 'x', {'label': m.group(3)}))
            nodes.append({'kind': 'ctrl', 'ind': ind, 'text': None, 'sig': f"{' ' * ind}ctrl{m.group(2)} {m.group(3)}", 'shape': ''})
            continue
        if nodes and nodes[-1]['kind'] == 'p':          # 글 안에 줄바꿈이 있는 문단 — 앞 문단의 글에 잇는다
            t = raw.rstrip()
            nodes[-1]['text'] += '\n' + (t[:-1] if t.endswith('"') else t)
    return nodes


def read(path):
    return parse(inspect(path))


def text_lines(nodes):
    return [n['text'] for n in nodes if n['kind'] == 'p' and n['text'].strip()]


def tables_of(nodes):
    """extract.read 가 쓰는 표 목록 — 맨 위 단계 표만, 칸의 글을 행·열로 모은다."""
    out, cur, depth = [], None, None
    for n in nodes:
        if n['kind'] == 'table' and (cur is None or n['ind'] <= depth):
            cur, depth = {}, n['ind']
            out.append(cur)
        elif n['kind'] == 'cell' and cur is not None and n['ind'] == depth + 2:
            m = re.search(r'cell\((\d+),(\d+)\)', n['sig'])
            cur['_at'] = (int(m.group(1)), int(m.group(2)))
            cur.setdefault(cur['_at'], [])
        elif n['kind'] == 'p' and cur is not None and n['ind'] > depth and '_at' in cur:
            if n['text'].strip():
                cur[cur['_at']].append(PUA.sub('', n['text']).strip())
        elif n['kind'] == 'p' and n['ind'] == 0:
            cur = None
    grids = []
    for t in out:
        cells = {k: ' '.join(v) for k, v in t.items() if k != '_at'}
        if not cells:
            continue
        rows, cols = max(r for r, _ in cells) + 1, max(c for _, c in cells) + 1
        grids.append([[cells.get((r, c), '') for c in range(cols)] for r in range(rows)])
    return grids


# ───────────── ② 맞대기 — 고정된 곳과 바뀌는 칸 ─────────────
TOK = re.compile(r'20\d\d\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{1,2}(?!\d)|20\d\d년\s*\d{1,2}월\s*\d{1,2}일|\d+(?:,\d{3})*(?:\.\d+)?|[가-힣]+|[A-Za-z]+|\s+|.', re.S)
STRONG = re.compile(r'[가-힣A-Za-z0-9]')
JOSA = ('으로', '에서', '에게', '이며', '이고', '은', '는', '이', '가', '을', '를', '의', '와', '과', '에', '로', '도')


def _tok(s):
    return TOK.findall(s)


def _key(t):
    return ' ' if t.isspace() else t


def _line_slots(texts):
    """같은 자리의 글 여러 건 → 칸 목록 [(기준 글에서의 시작, 끝, [문서별 값])]. 모든 문서에 같은 순서로 나오는 낱말은 고정으로 본다."""
    toks = [_tok(t) for t in texts]
    base = toks[0]
    maps = []
    for other in toks[1:]:
        mp = {}
        for a, b, n in difflib.SequenceMatcher(None, [_key(t) for t in base], [_key(t) for t in other], autojunk=False).get_matching_blocks():
            for i in range(n):
                mp[a + i] = b + i
        maps.append(mp)
    anchors = [i for i in range(len(base)) if all(i in mp for mp in maps)]
    # 칸 = 이웃한 고정 낱말 사이에서, 어느 문서에든 글이 있는 구간
    gaps = []
    bounds = [-1] + anchors + [len(base)]
    for x, y in zip(bounds, bounds[1:]):
        vals = [''.join(base[x + 1:y])]
        for k, mp in enumerate(maps):
            lo = mp[x] + 1 if x >= 0 else 0
            hi = mp[y] if y < len(base) else len(toks[k + 1])
            vals.append(''.join(toks[k + 1][lo:hi]))
        if any(vals):
            gaps.append([x + 1, y, vals])
    # 칸 사이의 고정 글이 공백·기호뿐이면 한 칸으로 합친다("연 12" · "4. 1")
    merged = []
    for g in gaps:
        if merged:
            mid = base[merged[-1][1]:g[0]]
            if not any(STRONG.search(t) for t in mid):
                glue = ''.join(mid)
                merged[-1] = [merged[-1][0], g[1], [a + glue + b for a, b in zip(merged[-1][2], g[2])]]
                continue
        merged.append(g)
    pos = [0]
    for t in base:
        pos.append(pos[-1] + len(t))
    total = sum(len(t) for t in base if not t.isspace())
    fixed = total - sum(len(re.sub(r'\s+', '', v[2][0])) for v in merged)
    if len(merged) > 4 or (total and fixed / total < 0.2 and len(merged) > 1):      # 우연히 겹친 낱말로 잘게 쪼개진 줄 — 처음 다른 곳부터 마지막 다른 곳까지 한 칸
        a, b = merged[0][0], merged[-1][1]
        vals = [''.join(base[a:b])]
        for k, mp in enumerate(maps):
            lo = mp[a - 1] + 1 if a > 0 else 0
            hi = mp[b] if b < len(base) else len(toks[k + 1])
            vals.append(''.join(toks[k + 1][lo:hi]))
        merged = [[a, b, vals]]
    out = []
    for a, b, vals in merged:
        lead = min(len(v) - len(v.lstrip()) for v in vals) if all(vals) else 0        # 모든 문서의 값이 공백으로 시작·끝나면 그 공백은 고정 쪽에 둔다
        tail = min(len(v) - len(v.rstrip()) for v in vals) if all(vals) else 0
        if not tail and all(vals):                                                    # '지연이(가)' · '증권의' — 모든 값 끝의 같은 조사는 고정 쪽에 둔다
            tail = len(next((j for j in JOSA if all(len(v) > len(j) and v.endswith(j) and re.search('[가-힣]', v[-len(j) - 1]) for v in vals)), ''))
        out.append((pos[a] + lead, pos[b] - tail, [v[lead:len(v) - tail] if tail else v[lead:] for v in vals]))
    return out


JO = re.compile(r'^\s*제\s*\d+\s*조')


def _heading(n):
    """맨 위 문단이 장 제목이면 그 이름 — 코스콤 보고서의 기호 글꼴 표시 줄, 계약서·규정의 '제 n 조【…】'."""
    t = n['text']
    if n['ind'] == 0 and (PUA.match(t.lstrip()) or JO.match(t)):
        t = PUA.sub('', t).strip()
        m = re.search(r'【(.+?)】', t)
        return (m.group(1) if m else t).strip()[:24]
    return None


def analyze(paths, names=None, heads=()):
    """문서 2건 이상(첫 문서가 기준) → {'ok', 'reason', 'slots': [...], 'fixed_ratio', ...}. 구조가 다르면 ok=False와 이유."""
    names = names or [os.path.basename(p) for p in paths]
    docs = [read(p) for p in paths]
    base = docs[0]
    res = {'ok': False, 'reason': '', 'docs': names, 'lines': len(base), 'text_lines': len(text_lines(base)), 'slots': []}
    if len(docs) < 2:
        return {**res, 'reason': '같은 종류의 한글 문서가 2건 이상 있어야 바뀌는 칸을 찾을 수 있습니다'}
    for k, d in enumerate(docs[1:], 1):
        sa, sb = [n['sig'] for n in base], [n['sig'] for n in d]
        if sa != sb:
            at = next((i for i, (x, y) in enumerate(zip(sa, sb)) if x != y), min(len(sa), len(sb)))
            near = next((n['text'] for n in reversed(base[:at + 1]) if n['kind'] == 'p' and n['text'].strip()), '')
            return {**res, 'reason': f"「{names[k]}」의 구성(문단 · 표)이 기준 문서와 다릅니다 — 기준 {len(sa)}줄 · 이 문서 {len(sb)}줄, 처음 달라지는 곳: “{PUA.sub('', near).strip()[:30]}” 부근"}
    own = any(_heading(n) for n in base if n['kind'] == 'p')          # 문서에 장 제목 표시가 없을 때만 읽기 단계가 준 장 제목 후보를 쓴다
    heads = [] if own else [re.sub(r'\s+', '', h) for h in heads or []]
    section, slots, total, var = '', [], 0, 0
    for i, n in enumerate(base):
        if n['kind'] != 'p':
            continue
        texts = [d[i]['text'] for d in docs]
        clean = re.sub(r'\s+', '', PUA.sub('', n['text']))
        total += len(clean)
        if len(set(texts)) == 1:
            h = _heading(n) or (PUA.sub('', n['text']).strip() if n['ind'] == 0 and clean in heads else None)
            if h:
                section = h
            continue
        for a, b, vals in _line_slots(texts):
            var += len(re.sub(r'\s+', '', vals[0]))
            slots.append({'id': f's{len(slots) + 1}', 'node': i, 'span': [a, b], 'values': vals, 'section': section,
                          'left': n['text'][:a], 'right': n['text'][b:]})
    if not slots:
        return {**res, 'reason': '문서들의 글이 모두 같아 바뀌는 칸이 없습니다'}
    # 모든 문서에서 값이 똑같은 칸들은 한 칸이다(고객사명이 표지·제1조·서명란에 나오는 경우). 짧은 값·숫자는 우연히 같을 수 있어 묶지 않는다
    first = {}
    for s in slots:
        vals = tuple(v.strip() for v in s['values'])
        same = all(len(re.sub(r'\s+', '', v)) >= 3 and re.search('[가-힣A-Za-z]', v) for v in vals)
        s['group'] = first.setdefault(vals, s['id']) if same else s['id']
    for s in slots:                             # 같은 줄의 앞 칸 이름을 참고하므로 차례로 붙인다
        s['label'] = _rule_label(s, base, slots)
    ratio = (total - var) / total if total else 0
    res.update(ok=ratio >= MIN_FIXED, slots=slots, fields=len({s['group'] for s in slots}), fixed_chars=total - var, slot_chars=var,
               fixed_ratio=round(ratio, 3), var_lines=len({s['node'] for s in slots}),
               base_text=[[i, n['text']] for i, n in enumerate(base) if n['kind'] == 'p' and n['text'].strip()])      # 화면에 칸 자리를 보여 줄 때 쓴다(이 PC에만 둔다)
    if not res['ok']:
        res['reason'] = f'문서마다 바뀌는 글이 많습니다(고정 {ratio * 100:.0f}%). 분량이 달라지는 문서는 조립형이 맞습니다'
    return res


def _table_at(nodes, i):
    """마디 i가 든 가장 가까운 표 마디의 번호."""
    return next((j for j in range(i, -1, -1) if nodes[j]['kind'] == 'table' and nodes[j]['ind'] < nodes[i]['ind']), None)


def _cell_paras(nodes, i, rc):
    """마디 i가 든 표에서 칸 rc에 든 문단 마디 번호들."""
    t = _table_at(nodes, i)
    if t is None:
        return []
    out, on = [], False
    for j in range(t + 1, len(nodes)):
        n = nodes[j]
        if n['ind'] <= nodes[t]['ind']:
            break
        if n['kind'] == 'cell' and n['ind'] == nodes[t]['ind'] + 2:
            on = f'cell({rc[0]},{rc[1]})' in n['sig']
        elif on and n['kind'] == 'p':
            out.append(j)
    return out


def _cell_text(nodes, i, rc):
    return ' '.join(PUA.sub('', nodes[j]['text']).strip() for j in _cell_paras(nodes, i, rc) if nodes[j]['text'].strip())[:14]


def _rule_label(s, nodes, slots):
    """AI 없이 붙이는 칸 이름 — 앞의 (라벨) · '이름:' · 표의 행/열 머리글 · 문서의 첫 줄(제목)."""
    left = PUA.sub('', s['left']).rstrip()
    m = re.search(r'[(\[]([^()\[\]]{1,10})[)\]]$', left) or re.search(r'([가-힣A-Za-z][가-힣A-Za-z0-9 ]{0,9})\s*[:：]$', left)
    if m:
        return m.group(1).strip()
    prev = next((x for x in reversed(slots) if x['node'] == s['node'] and x['span'][0] < s['span'][0] and x.get('label')), None)
    if prev:                                    # 같은 줄의 앞 칸에 이름이 있으면 그 이름을 잇는다(번호는 make_keys가 붙인다)
        return prev['label']
    rc = next((p[1] for p in reversed(nodes[s['node']]['path']) if p[0] == 'c'), None)
    if rc and _table_at(nodes, s['node']) is not None:
        var = {x['node'] for x in slots}
        fixed = lambda c: '' if any(j in var for j in _cell_paras(nodes, s['node'], c)) else _cell_text(nodes, s['node'], c)
        # 열 머리글: 표의 맨 위에서부터 '바뀌는 칸이 없는 줄'이 머리글 줄이다. 그중 가장 아래 줄의 칸을 쓴다(병합된 머리글 아래 둘째 줄 포함)
        t = _table_at(nodes, s['node'])
        row_of = {}
        for j in range(t + 1, len(nodes)):
            if nodes[j]['ind'] <= nodes[t]['ind']:
                break
            if nodes[j]['kind'] == 'cell' and nodes[j]['ind'] == nodes[t]['ind'] + 2:
                cur = int(re.search(r'cell\((\d+),', nodes[j]['sig']).group(1))
                row_of.setdefault(cur, False)
            elif nodes[j]['kind'] == 'p' and j in var:
                row_of[cur] = True
        head = next((r for r in sorted(row_of) if row_of[r]), 0)          # 처음으로 바뀌는 칸이 나오는 줄 = 머리글 줄 수
        col = next((x for x in (fixed((r, rc[1])) for r in range(min(head, rc[0]) - 1, -1, -1)) if x), '')
        if rc[1] > 0:
            row = fixed((rc[0], 0)) or (f'{rc[0]}행' if col else '')
            if row or col:
                return f"{row} {col or f'{rc[1] + 1}열'}".strip()[:20]
        elif col:
            return f'{col} {rc[0]}행'
    if s['node'] == next((i for i, n in enumerate(nodes) if n['kind'] == 'p' and n['text'].strip()), -1):
        return '제목'
    return ''


def make_keys(slots, labels=None):
    """칸 id → 서식 토큰 이름(key). 같은 묶음(group)의 칸은 같은 이름을 쓴다. 이름에서 토큰 문법 글자({ } .)를 빼고, 겹치는 이름은 번호를 붙인다."""
    keys, seen, by_group = {}, {}, {}
    for n, s in enumerate(slots, 1):
        g = s.get('group', s['id'])
        if g not in by_group:
            members = [x for x in slots if x.get('group', x['id']) == g]
            lab = next((str(v) for v in [(labels or {}).get(g)] + [x.get('label') for x in members] if v), '')
            lab = re.sub(r'\s+', ' ', re.sub(r'[{}.\[\]\t\r\n"]+', ' ', lab)).strip()[:20] or f'칸 {len(by_group) + 1}'
            seen[lab] = seen.get(lab, 0) + 1
            by_group[g] = lab if seen[lab] == 1 else f'{lab} {seen[lab]}'
        keys[s['id']] = by_group[g]
    return keys


def values_of(an, k, keys):
    """k번째 대표 문서의 칸 값 {key: 값}"""
    return {keys[s['id']]: s['values'][k] for s in an['slots']}


def date_format(vals):
    """칸의 값이 모든 문서에서 같은 날짜 형식이면 그 형식."""
    fmts = set()
    for v in vals:
        m = checks.DATE_RX.fullmatch(v.strip())
        if not m:
            return None
        fmts.add(checks._date_format_of(m))
    return fmts.pop() if len(fmts) == 1 and 'other' not in fmts else None


# ───────────── ④ 서식 만들기 ─────────────
def _find_all(text, sub):
    out, at = [], text.find(sub)
    while at >= 0:
        out.append(at)
        at = text.find(sub, at + len(sub))
    return out


def build(base_path, an, keys, out_path):
    """기준 문서 + 칸 → 칸 토큰이 든 서식(.hwp). 돌려주는 값: {'ok', 'problems': [...], 'tokens': [...]}

    칸마다 '값 → {{이름}}' 바꿈 줄을 만든다. 글자 모양이 남도록 값만 바꾸는 것이 1순위이고, 그 글이 칸이 아닌 곳에도 나오면
    뒤(그래도 안 되면 앞)의 고정 글을 조금씩 붙여 자리를 특정한다. 그래도 안 되는 표 칸은 칸 글 전체를 바꾼다."""
    nodes = read(base_path)
    texts = {i: n['text'] for i, n in enumerate(nodes) if n['kind'] == 'p'}
    by = {}
    for s in an['slots']:
        by.setdefault(s['node'], []).append(s)
    target = {}
    for i, ss in by.items():
        new, at = '', 0
        for s in sorted(ss, key=lambda x: x['span'][0]):
            new += texts[i][at:s['span'][0]] + '{{' + keys[s['id']] + '}}'
            at = s['span'][1]
        target[i] = new + texts[i][at:]
    problems, rows, ops = [], [], []
    blocked = set()
    for i in by:
        name = '·'.join(dict.fromkeys(keys[s['id']] for s in by[i]))
        if any(p[0] == 'x' for p in nodes[i]['path']):
            problems.append(f'「{name}」 — 글상자 안의 글은 칸으로 만들 수 없습니다')
            blocked.add(i)
        elif '\t' in texts[i] or '\n' in texts[i]:
            problems.append(f'「{name}」 — 탭·줄바꿈이 든 문단은 칸으로 만들 수 없습니다')
            blocked.add(i)
    pos = {(s['node'], s['span'][0]): (s['span'][1], keys[s['id']]) for s in an['slots']}
    done = set()
    for s in sorted(an['slots'], key=lambda x: (x['node'], x['span'][0])):
        i, (a, b) = s['node'], s['span']
        if (i, a) in done or i in blocked:
            continue
        t, key = texts[i], keys[s['id']]
        nxt = min((x['span'][0] for x in by[i] if x['span'][0] >= b and x is not s), default=len(t))      # 이웃 칸 전까지가 쓸 수 있는 고정 글
        prv = max((x['span'][1] for x in by[i] if x['span'][1] <= a and x is not s), default=0)
        R, L = nxt - b, a - prv
        cands = [(0, min(k, R)) for k in (0, 1, 2, 4, 8, 16, R)] + [(min(l, L), R) for l in (1, 2, 4, 8, L)]
        if a == b:                              # 기준 문서에서는 빈 칸 — 앞뒤 고정 글로만 자리를 잡는다
            cands = [c for c in cands if c[0] + c[1] > 0]
        for l, k in dict.fromkeys(cands):
            frm = t[a - l:b + k]
            if not frm.strip() or '\t' in frm or '\n' in frm:
                continue
            occ = [(j, q) for j, tx in texts.items() for q in _find_all(tx, frm)]
            if all(j not in blocked and pos.get((j, q + l)) == (q + l + (b - a), key) for j, q in occ):
                to = t[a - l:a] + '{{' + key + '}}' + t[b:b + k]
                rows.append(f'L\t{frm}\t{to}')
                ops.append((frm, to))
                done.update((j, q + l) for j, q in occ)
                break
    sim = {i: t for i, t in texts.items()}
    for frm, to in ops:
        sim = {i: t.replace(frm, to) for i, t in sim.items()}
    for i in sorted(by):                        # 값만으로 자리를 특정하지 못한 칸 — 맨 위 문단의 첫 표에 든 칸의 첫 문단이면 칸 글 전체를 바꾼다
        if i in blocked or all((i, s['span'][0]) in done for s in by[i]):
            continue
        p = nodes[i]['path']
        if len(p) == 4 and p[0][0] == 'p' and p[1] == ('t', 0) and p[2][0] == 'c' and p[3] == ('p', 'p0'):
            rows.append(f'C\t{nodes[i]["top"]}\t{p[2][1][0]}\t{p[2][1][1]}\t{target[i]}')
            sim[i] = target[i]
            done.update((i, s['span'][0]) for s in by[i])
        else:
            problems.append(f"「{'·'.join(dict.fromkeys(keys[s['id']] for s in by[i]))}」 — 같은 글이 문서의 다른 곳에도 있어 자리를 특정할 수 없습니다")
    bad = [i for i, t in sim.items() if i not in blocked and t != target.get(i, texts[i])]
    if bad and not problems:
        problems.append(f"바꿈표가 뜻한 대로 적용되지 않는 줄이 {len(bad)}곳 있습니다 — “{PUA.sub('', texts[bad[0]]).strip()[:30]}”")
    tsv = os.path.splitext(out_path)[0] + '.map.tsv'
    with open(tsv, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(rows) + '\n')
    code, out = _java('TemplateMaker', base_path, tsv, out_path)
    try:
        os.remove(tsv)                          # 바꿈표에는 기준 문서의 글이 들어 있다 — 남기지 않는다
    except OSError:
        pass
    if code != 0 or not os.path.exists(out_path):
        return {'ok': False, 'problems': problems + ['서식을 만들지 못했습니다: ' + out.strip()[-200:]], 'tokens': []}
    problems += ['바꿀 글을 찾지 못함 — ' + l.split('→', 1)[-1].strip() for l in out.splitlines() if l.startswith('!!')]
    tokens = [m.group(1) for l in out.split('서식에 든 칸:', 1)[-1].splitlines() if (m := re.match(r'\s*\{\{(.+)\}\}\s*$', l))]
    miss = [k for k in dict.fromkeys(keys.values()) if k not in tokens]
    if miss and not problems:
        problems.append('서식에 들어가지 않은 칸: ' + ', '.join(miss))
    return {'ok': not problems, 'problems': problems, 'tokens': tokens}


def leftovers(template_path, an):
    """서식에 대표 문서의 값이 남아 있는지 — 4자 이상인 값이 서식의 글에 그대로 있으면 알려 준다(건수만 저장소에 올린다)."""
    text = '\n'.join(text_lines(read(template_path)))
    text = re.sub(r'\{\{[^{}]+\}\}', ' ', text)
    out = []
    for s in an['slots']:
        for v in s['values']:
            v = v.strip()
            if len(re.sub(r'\s+', '', v)) >= 4 and v in text and v not in out:
                out.append(v)
    return out


# ───────────── ⑤ 되만들기 시험 ─────────────
def remake(template_path, values, out_path, rows=None):
    """서식에 값을 넣어 문서를 다시 만든다 → (성공 여부, 경고). rows = 늘어나는 표의 행(전사 서식 채우기 스킬의 서식에만 있다)"""
    import json
    vp = os.path.splitext(out_path)[0] + '.values.json'
    with open(vp, 'w', encoding='utf-8') as f:
        json.dump({'fields': values, 'rows': rows or {}}, f, ensure_ascii=False)
    code, out = _java('FillRenderer', template_path, vp, out_path)
    try:
        os.remove(vp)
    except OSError:
        pass
    return code == 0 and os.path.exists(out_path), [l[5:].strip() for l in out.splitlines() if l.startswith('WARN')]


def compare(orig_path, new_path):
    """원본과 되만든 문서를 세 층으로 비교한다: 글자(문단의 글) · 구성(문단 · 표 · 칸의 순서와 병합) · 모양(문단 모양 · 글자 모양 구간 · 칸 테두리 번호)."""
    a, b = read(orig_path), read(new_path)
    n = max(len(a), len(b))
    pa = [x for x in a if x['kind'] == 'p' and x['text'].strip()]
    res = {'lines': len(a), 'lines_got': len(b), 'text': [0, len(pa)], 'struct': [0, n], 'shape': [0, n], 'diffs': []}
    for i in range(n):
        x, y = (a[i] if i < len(a) else None), (b[i] if i < len(b) else None)
        if x and y and x['sig'] == y['sig']:
            res['struct'][0] += 1
            if x['shape'] == y['shape']:
                res['shape'][0] += 1
            elif len(res['diffs']) < 8:
                res['diffs'].append({'layer': '모양', 'want': x['shape'], 'got': y['shape'], 'near': PUA.sub('', x.get('text') or '').strip()[:30]})
            if x['kind'] == 'p' and x['text'].strip():
                if x['text'] == y['text']:
                    res['text'][0] += 1
                elif len(res['diffs']) < 8:
                    res['diffs'].append({'layer': '글자', 'want': x['text'].strip()[:60], 'got': (y['text'] or '').strip()[:60]})
        elif len(res['diffs']) < 8:
            res['diffs'].append({'layer': '구성', 'want': (x or {}).get('sig', '(없음)').strip(), 'got': (y or {}).get('sig', '(없음)').strip()})
    res['identical'] = res['text'][0] == res['text'][1] and res['struct'][0] == n and res['shape'][0] == n
    try:
        res['bytes_same'] = open(orig_path, 'rb').read() == open(new_path, 'rb').read()
    except OSError:
        res['bytes_same'] = False
    return res
