"""검수 확장 — 스킬 규칙 검사와 원본값 대조(수정 누락 찾기).

- skill_checks: 상속 해석된 스킬의 필수 문구·금지어·고정 문구가 결과에 지켜졌는지
- extract_values / crosscheck: 원본(메모·엑셀)과 결과 파일(한글·PPT·웹·사람이 고친 파일)에서
  '항목명 + 숫자 + 단위'를 뽑아 같은 항목의 값이 다르거나 빠진 곳을 찾는다. 읽지 못한 파일은 '판정 불가'.
"""
import html
import re

UNIT = r'(조원|억원|천만원|백만원|만원|원|억|%|건|명|개월|개|시간|분|일|회|배|점)'
NUM_RX = re.compile(r'(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*' + UNIT)
KEY_RX = re.compile(r'([가-힣A-Za-z][가-힣A-Za-z0-9·()\s]{0,14})\s*[:：]?\s*$')
STOP = {'약', '총', '및', '등', '각', '연', '월', '주', '전', '후', '기준', '이내', '이상', '이하', '대비'}


def _norm(v, unit):
    x = float(v.replace(',', ''))
    mul = {'조원': 10**12, '억원': 10**8, '억': 10**8, '천만원': 10**7, '백만원': 10**6, '만원': 10**4, '원': 1}.get(unit)
    return (x * mul, '원') if mul else (x, unit)


def _key(before):
    b = re.split(r'[,.;\n|·•■□○ㅇ\-–(]\s*', before)[-1].strip()
    m = KEY_RX.search(b)
    if not m:
        return ''
    words = [w for w in m.group(1).split() if w not in STOP]
    return ' '.join(words[-2:]).strip()


def extract_values(text):
    """[{key, value, unit, raw, ctx}] — 같은 항목이 여러 번 나오면 모두."""
    out = []
    label = ''
    for line in str(text or '').splitlines():
        s = line.strip()
        if not s:
            continue
        found = False
        for m in NUM_RX.finditer(line):
            v, u = _norm(m.group(1), m.group(2))
            k = _key(line[:m.start()])
            if not k and m.start() <= 2 and label:      # PPT처럼 이름표('예산')와 값이 다른 글상자에 있을 때
                k = label
            out.append({'key': k, 'value': v, 'unit': u, 'raw': m.group(0).strip(), 'ctx': (f'{label} ' if k == label and label else '') + s[:80]})
            found = True
        label = s if (not found and len(s) <= 12 and not re.search(r'\d', s)) else ''
    return out


def crosscheck(source_text, targets):
    """source_text: 원본 자료 글. targets: [{'name','text'|None}]. 돌려주는 값: {'items': [...], 'summary'}"""
    src = [x for x in extract_values(source_text) if x['key']]
    items = []
    for t in targets:
        if t.get('text') is None:
            items.append({'target': t['name'], 'kind': 'unknown', 'detail': '파일을 읽지 못해 판정 불가'})
            continue
        tv = extract_values(t['text'])
        for s in src:
            same_key = [x for x in tv if x['key'] and (x['key'] == s['key'] or s['key'] in x['key'] or x['key'] in s['key']) and x['unit'] == s['unit']]
            if any(abs(x['value'] - s['value']) < 1e-9 for x in same_key):
                continue
            # 원본끼리 같은 항목 값이 다를 수 있다(보고서 33.7억원 · 투자계획서 33.66억원). 결과가 그중 하나를 쓰면 다름이 아니라 빠진 값(참고)
            alts = [o['value'] for o in src if o['key'] == s['key'] and o['unit'] == s['unit']]
            if not same_key or any(abs(x['value'] - v) < 1e-9 for x in same_key for v in alts):
                if not any(abs(x['value'] - s['value']) < 1e-9 and x['unit'] == s['unit'] for x in tv):
                    items.append({'target': t['name'], 'kind': 'missing', 'key': s['key'], 'want': s['raw'], 'got': '',
                                  'detail': f"원본의 '{s['key']} {s['raw']}'이(가) 없음"})
                continue
            got = same_key[0]
            items.append({'target': t['name'], 'kind': 'mismatch', 'key': s['key'], 'want': s['raw'], 'got': got['raw'],
                          'detail': f"'{s['key']}' 원본 {s['raw']} ≠ {t['name']} {got['raw']}", 'ctx': got['ctx']})
    mism = [i for i in items if i['kind'] == 'mismatch']
    return {'items': items, 'checked': len(src), 'mismatch': len(mism), 'missing': sum(1 for i in items if i['kind'] == 'missing'),
            'unknown': sum(1 for i in items if i['kind'] == 'unknown')}


# ───────────── 문체(style) — 대표 문서에서 재서 스킬 양식에 적는다 ─────────────
# 스킬에 style이 없으면 코스콤 보고 문법(명사형 종결 · 2026. 10. 28 · 90자)을 그대로 쓴다.
# 계약서·공문·규정처럼 보고서가 아닌 문서는 그 문서의 문체를 기준으로 쓰고 검수한다.
DEFAULT_STYLE = {'ending': 'noun', 'date': 'Y. M. D', 'max_len': 90}
ENDINGS = {'noun': '명사형 종결 (~함, ~임)', 'plain': '서술형 종결 (~한다)', 'polite': '서술형 종결 (~합니다)', 'any': '종결 형태 자유'}
DATE_FORMATS = ('Y. M. D', 'Y.MM.DD', 'Y-MM-DD', 'Y년 M월 D일', 'any')
DATE_RX = re.compile(r'(20\d\d)(?:[-./]\s*(\d{1,2})[-./]\s*(\d{1,2})(?!\d)|년\s*(\d{1,2})월\s*(\d{1,2})일)')
SENT_END = re.compile(r'[가-힣]다[.。]?[”"’\')\]]*$')            # ~한다. ~합니다.
POLITE_END = re.compile(r'니다[.。]?[”"’\')\]]*$')
NOUN_END = re.compile(r'(함|임|됨|했음|하였음|되었음|있음|없음)[.]?$')   # 개조식
NOUN_TOLERANCE = 0.1     # 서술형이 이 비율 이하면 명사형 문서로 본다 — 측정(measure_style)과 판정(engines.check)이 같은 숫자를 쓴다


def norm_style(style):
    """스킬의 style(없거나 일부만 있어도 됨) → 빠진 값은 코스콤 보고 문법으로 채운다."""
    if isinstance(style, str):
        import json
        try:
            style = json.loads(style)
        except Exception:
            style = None
    st = dict(DEFAULT_STYLE)
    for k in ('ending', 'date', 'max_len'):
        if isinstance(style, dict) and style.get(k) is not None:
            st[k] = style[k]
    if st['ending'] not in ENDINGS:
        st['ending'] = 'noun'
    if st['date'] not in DATE_FORMATS:
        st['date'] = 'Y. M. D'
    try:
        st['max_len'] = max(0, int(st['max_len']))
    except Exception:
        st['max_len'] = 90
    return st


def is_default_style(style):
    return norm_style(style) == DEFAULT_STYLE


def date_parts(m):
    """DATE_RX 매치 → (연, 월, 일)"""
    return int(m.group(1)), int(m.group(2) or m.group(4)), int(m.group(3) or m.group(5))


def fmt_date(y, m, d, fmt):
    return {'Y. M. D': f'{y}. {m}. {d}', 'Y.MM.DD': f'{y}.{m:02d}.{d:02d}', 'Y-MM-DD': f'{y}-{m:02d}-{d:02d}',
            'Y년 M월 D일': f'{y}년 {m}월 {d}일'}.get(fmt)


def _unpad(s):
    return re.sub(r'(?<!\d)0(\d)', r'\1', re.sub(r'\s+', ' ', s))


def date_ok(m, fmt):
    """날짜 한 건이 이 형식인가. 기본 형식(2026. 10. 28)은 글자 그대로, 나머지는 0 채움 차이를 봐준다."""
    if fmt == 'any':
        return True
    want = fmt_date(*date_parts(m), fmt)
    return m.group(0) == want if fmt == 'Y. M. D' else _unpad(m.group(0)) == _unpad(want)


def _date_format_of(m):
    return next((f for f in DATE_FORMATS[:-1] if date_ok(m, f)), 'other')


def style_label(style):
    st = norm_style(style)
    parts = [ENDINGS[st['ending']]]
    parts.append('날짜 자유' if st['date'] == 'any' else '날짜 ' + fmt_date(2026, 10, 28, st['date']))
    parts.append(f"항목 {st['max_len']}자 이내" if st['max_len'] else '길이 제한 없음')
    return ' · '.join(parts)


def measure_style(texts):
    """대표 문서들의 글에서 문체를 잰다 → {'ending','date','max_len','basis'}.
    문서가 보고 문법과 어긋나지 않으면 기본값(명사형·2026. 10. 28·90자)을 유지한다."""
    import math
    lines = []
    for t in texts:
        for l in str(t or '').splitlines():
            s = l.strip()
            if len(s) >= 15 and re.search(r'[가-힣]', s) and not s.startswith('<'):      # 표 칸·짧은 제목은 뺀다
                lines.append(s)
    st = dict(DEFAULT_STYLE)
    basis = [f'대표 문서 {len(texts)}건']
    if len(lines) >= 3:
        sent = [l for l in lines if SENT_END.search(l)]
        ratio = len(sent) / len(lines)
        if ratio >= 0.35:
            st['ending'] = 'polite' if sum(1 for l in sent if POLITE_END.search(l)) * 2 >= len(sent) else 'plain'
        elif ratio > NOUN_TOLERANCE:
            st['ending'] = 'any'
        basis.append(f'문장 {len(lines)}개 중 서술형(~다) {ratio * 100:.0f}%')
        over = sum(1 for l in lines if len(l) > 90) / len(lines)
        if over > 0.1:
            lim = int(math.ceil(max(len(l) for l in lines) * 1.2 / 50) * 50)
            st['max_len'] = 0 if lim > 600 else lim
        basis.append(f'90자 초과 {over * 100:.0f}%')
    kinds = [_date_format_of(m) for t in texts for m in DATE_RX.finditer(str(t or ''))]
    if kinds:
        top = max(set(kinds), key=kinds.count)
        st['date'] = top if top != 'other' and kinds.count(top) / len(kinds) >= 0.6 else 'any'
        basis.append(f"날짜 {len(kinds)}건 중 {kinds.count(top)}건이 {'여러 형식' if st['date'] == 'any' else fmt_date(2026, 10, 28, st['date']) + ' 형식'}")
    st['basis'] = ' · '.join(basis)
    return st


def validate_style(style):
    """스킬 파일의 style 값 검사 → 오류 목록."""
    if style is None:
        return []
    if not isinstance(style, dict):
        return ['style은 ending · date · max_len 을 가진 묶음이어야 함']
    errs = []
    if style.get('ending') is not None and style['ending'] not in ENDINGS:
        errs.append('style.ending은 ' + ' | '.join(ENDINGS))
    if style.get('date') is not None and style['date'] not in DATE_FORMATS:
        errs.append('style.date는 ' + ' | '.join(DATE_FORMATS))
    if style.get('max_len') is not None and not (isinstance(style['max_len'], int) and style['max_len'] >= 0):
        errs.append('style.max_len은 0(제한 없음) 이상의 정수')
    return errs


# ───────────── 고정 문구 안의 칸 — "[칸 이름]" ─────────────
# 계약서 조항처럼 '틀은 같고 값만 바뀌는' 고정 문구는 바뀌는 자리를 [칸 이름]으로 적는다.
# 칸 밖의 글자가 그대로면 고정 문구를 지킨 것으로 본다. 숫자로 끝나는 [고객사명1]은 가림 토큰이라 칸이 아니다.
SLOT_RX = re.compile(r'\[[^\[\]\n]{1,23}[^\[\]\n\d]\]')


JOSA = [('을', '를'), ('이', '가'), ('은', '는'), ('과', '와'), ('으로', '로')]


def _josa_rx(p):
    """칸 바로 뒤 글의 첫 조사를 짝 조사와 함께 받는다: '을 다음과' → '(?:을|를) 다음과'.
    칸에 받침 없는 말이 오면 AI는 문법대로 '를'을 쓴다 — 그래도 같은 고정 문구로 본다. 조사 뒤에 한글이 이어지면([칸]이다) 조사가 아니다."""
    for a, b in JOSA:
        for x in (a, b):
            if p.startswith(x) and (len(p) == len(x) or not re.match('[가-힣]', p[len(x)])):
                return f'(?:{re.escape(a)}|{re.escape(b)})' + re.escape(p[len(x):])
    return re.escape(p)


def _fixed_rx(t):
    parts = SLOT_RX.split(t)
    if len(parts) == 1:
        return None
    return re.compile(r'.{1,80}?'.join([re.escape(parts[0])] + [_josa_rx(p) for p in parts[1:]]), re.S)


def fixed_present(t, text):
    """고정 문구 t가 text 안에 지켜졌는가(칸은 어떤 값으로 채워져도 됨)."""
    if not t or t in text:
        return True
    rx = _fixed_rx(t)
    return bool(rx and rx.search(text))


def is_fixed_item(item_text, fixed_texts):
    """이 항목이 고정 문구(칸을 채운 것 포함)인가 — 문체 검사에서 빼는 데 쓴다."""
    s = item_text.strip()
    for t in fixed_texts:
        t = str(t or '').strip()
        if not t:
            continue
        if s == t:
            return True
        rx = _fixed_rx(t)
        if rx and rx.fullmatch(s):
            return True
    return False


def slots_of(fixed_texts):
    out = []
    for t in fixed_texts:
        for m in SLOT_RX.findall(str(t or '')):
            if m not in out:
                out.append(m)
    return out


# ───────────── 저장소에 올릴 때 — 대표 문서의 글·값이 드러나지 않게 ─────────────
def public_score(sc):
    """채점 결과를 저장소에 올릴 모양으로: 빠진 숫자·새 숫자는 값(대표 문서에서 온 숫자) 대신 건수만 남긴다."""
    return {'struct': sc.get('struct'), 'fixed': sc.get('fixed'), 'lost': len(sc.get('lost') or []), 'new': len(sc.get('new') or []),
            'grammar': list(sc.get('grammar') or [])}


def company_names(skill):
    """스킬 글(이름·구성·고정 문구·규칙)에서 회사 이름으로 보이는 글 — 등록 전에 화면에 알려 준다(막지는 않는다)."""
    import llm
    parts = [str(skill.get('name') or '')] + [str(r) for r in skill.get('rules') or []]
    for f in skill.get('forms') or []:
        parts += [str(f.get('name') or '')] + [str(h) for h in f.get('outline') or []]
    parts += [str(b.get('text') or '') for b in skill.get('blocks') or []]
    out = []
    for line in '\n'.join(parts).splitlines():
        if '가상' in line:                       # '(가상)'이라고 밝힌 줄은 알리지 않는다
            continue
        for m in llm.MASK_RX['고객사명'].finditer(line):
            if m.group(0) not in out:
                out.append(m.group(0))
    return out[:8]


def bp_text(bp):
    lines = [bp.get('title', '')]
    for s in bp.get('sections') or []:
        lines.append(s.get('heading', ''))
        for it in s.get('items') or []:
            lines.append(f"{it.get('label', '')} {it.get('text', '')}".strip())
            lines += [c.get('text', '') for c in it.get('children') or []]
        tb = s.get('table')
        if tb and tb.get('rows'):
            cols = tb.get('cols') or []
            for r in tb['rows']:
                lines.append(' '.join(f'{c} {v}' if j and j < len(cols) else str(v) for j, (c, v) in enumerate(zip([''] + cols[1:], r))))
    return '\n'.join(lines)


def html_text(path):
    s = open(path, encoding='utf-8', errors='replace').read()
    s = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', s, flags=re.S)
    s = re.sub(r'<(br|/p|/div|/li|/tr|/h\d)[^>]*>', '\n', s)
    return html.unescape(re.sub(r'<[^>]+>', ' ', s))


def skill_checks(bp, skill):
    """skill = form 행의 skill 정보(checks·glossary·fixed). 돌려주는 값: 검수 항목 목록(engines.check 형식)."""
    if not skill:
        return []
    text = bp_text(bp)
    out = []
    req = (skill.get('checks') or {}).get('required') or []
    miss = [r for r in req if r not in text]
    out.append({'id': 'required', 'name': '팩 필수 문구', 'ok': not miss, 'detail': ' / '.join(miss)[:160], 'fix': bool(miss),
                'from': 'skill'})
    banned = list(dict.fromkeys(((skill.get('checks') or {}).get('banned') or []) + ((skill.get('glossary') or {}).get('banned') or [])))
    hit = [b for b in banned if b and b in text]
    out.append({'id': 'banned', 'name': '팩 금지어', 'ok': not hit, 'detail': ', '.join(hit), 'fix': bool(hit), 'from': 'skill'})
    fixed = skill.get('fixed') or []
    lost = [f['text'] for f in fixed if f.get('text') and not fixed_present(f['text'], text)]
    out.append({'id': 'fixed', 'name': '팩 고정 문구(글자 그대로)', 'ok': not lost, 'detail': ' / '.join(lost)[:160], 'fix': bool(lost),
                'from': 'skill'})
    return out


def fix_skill(bp, skill):
    """필수·고정 문구를 맞는 장에 넣고 금지어를 지운다."""
    import json
    b = json.loads(json.dumps(bp))
    text = bp_text(b)
    secs = b['sections']
    for f in skill.get('fixed') or []:
        if f.get('text') and not fixed_present(f['text'], text):
            tgt = next((s for s in secs if f.get('heading') and f['heading'] in s['heading']), secs[-1])
            tgt['items'].append({'label': '', 'text': f['text'], 'children': []})
    text = bp_text(b)
    for r in (skill.get('checks') or {}).get('required') or []:
        if r not in text:
            secs[-1]['items'].append({'label': '유의', 'text': r, 'children': []})
    banned = list(dict.fromkeys(((skill.get('checks') or {}).get('banned') or []) + ((skill.get('glossary') or {}).get('banned') or [])))
    for s in secs:
        for it in s['items']:
            for w in banned:
                if w:
                    it['text'] = re.sub(r'\s*' + re.escape(w) + r'\s*', ' ', it['text']).strip()
    return b


def enforce_fixed(bp, fixed):
    """스킬의 고정 문구는 AI가 바꾸거나 빠뜨려도 글자 그대로 들어가게 한다(맞는 장에 넣고, 비슷하게 바꾼 문장은 교체)."""
    import difflib
    import json as _j
    b = _j.loads(_j.dumps(bp))
    secs = b.get('sections') or []
    if not secs:
        return b
    for f in fixed or []:
        t = (f.get('text') or '').strip()
        if not t or fixed_present(t, bp_text(b)):      # 칸([칸 이름])을 채운 문장은 틀이 같으면 그대로 둔다
            continue
        best, ratio = None, 0.0
        for s in secs:
            for it in s['items']:
                r = difflib.SequenceMatcher(None, it['text'], t).ratio()
                if r > ratio:
                    best, ratio = it, r
        if best is not None and ratio >= 0.6:
            best['text'] = t
            continue
        h = (f.get('heading') or '').strip()
        tgt = next((s for s in secs if h and (h in s['heading'] or s['heading'] in h)), None) or secs[-1]
        tgt['items'].append({'label': '', 'text': t, 'children': []})
    return b


if __name__ == '__main__':           # 자체검사: 원본끼리 같은 항목 값이 다르면(33.7억원 · 33.66억원) 결과가 그중 하나를 써도 다름이 아님
    r = crosscheck('부가세 포함 33.7억원\n부가세 포함 33.66억원\n사업 기간 12개월', [{'name': 'PPT', 'text': '부가세 포함 33.66억원\n사업 기간 10개월'}])
    assert [(i['kind'], i['want']) for i in r['items']] == [('missing', '33.7억원'), ('mismatch', '12개월')], r['items']
    print('checks selftest OK')
