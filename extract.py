"""첨부 파일 → 본문 텍스트 · 표 · 장 제목 후보. DRM(암호화) 파일은 내용을 읽지 않고 표시만 한다."""
import csv
import io
import os
import re
import zipfile
from xml.etree import ElementTree as ET

import engines

OLE = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
DRM_MARKS = (b'SCDSA', b'<## MarkAny', b'FASOO', b'DRMONE', b'MARKANY', b'Fasoo DRM', b'SoftCamp')
HEAD_RX = re.compile(r'^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.|\d{1,2}\.|[□■◆○●]|[가-하]\.)\s*(.{2,24})$')


def is_drm(path, ext):
    if ext == 'pia':
        return True
    head = open(path, 'rb').read(4096)
    if any(m in head for m in DRM_MARKS):
        return True
    if ext in ('xlsx', 'pptx', 'docx') and not head.startswith(b'PK'):
        return True
    if ext == 'hwp' and not head.startswith(OLE):
        return True
    if ext == 'pdf' and not head.startswith(b'%PDF'):
        return True
    return False


def _clean(t):
    return re.sub(r'\s+', ' ', str(t if t is not None else '')).strip()


def _xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    tables, text = [], []
    for ws in wb.worksheets:
        grid = [[_clean(c) for c in r] for r in ws.iter_rows(values_only=True)]
        grid = [r for r in grid if any(r)]
        if not grid:
            continue
        keep = [j for j in range(max(len(r) for r in grid)) if any(j < len(r) and r[j] for r in grid)]
        grid = [[r[j] if j < len(r) else '' for j in keep] for r in grid]
        tables.append({'title': ws.title, 'cols': grid[0], 'rows': grid[1:40]})
        text.append(f'[{ws.title}] ' + ' / '.join(' | '.join(r) for r in grid[:15]))
    return '\n'.join(text), tables, [t['title'] for t in tables]


def _pptx(path):
    from pptx import Presentation
    text, tables, heads = [], [], []
    for s in Presentation(path).slides:
        shapes = list(engines.pptx_shapes(s.shapes))        # 묶음 도형 안의 글까지 읽는다
        if s.shapes.title is not None and s.shapes.title.text.strip():
            heads.append(_clean(s.shapes.title.text))
        else:
            tf = [sh.text_frame.text.strip() for sh in shapes if sh.has_text_frame and sh.text_frame.text.strip()]
            for i, t in enumerate(tf):
                m = re.match(r'^\d{2}\s+(\S.{1,24})$', t)
                if m:
                    heads.append(m.group(1).strip())
                    break
                if re.match(r'^\d{2}\.\s', t) and i + 1 < len(tf) and len(tf[i + 1]) <= 24:   # 셰브론 덱: 키커 다음이 장 제목
                    heads.append(tf[i + 1])
                    break
        for sh in shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                text.append(_clean(sh.text_frame.text))
            if getattr(sh, 'has_table', False) and sh.has_table:
                g = [[_clean(c.text) for c in r.cells] for r in sh.table.rows]
                if len(g) > 1:
                    tables.append({'title': heads[-1] if heads else '표', 'cols': g[0], 'rows': g[1:]})
    return '\n'.join(text), tables, heads


W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def _docx(path):
    z = zipfile.ZipFile(path)
    root = ET.fromstring(z.read('word/document.xml'))
    body = root.find(W + 'body')
    text, tables, heads = [], [], []
    for el in body:
        if el.tag == W + 'p':
            t = ''.join(x.text or '' for x in el.iter(W + 't')).strip()
            st = el.find(f'{W}pPr/{W}pStyle')
            if t:
                text.append(t)
                if (st is not None and re.search('Heading|제목', st.get(W + 'val', ''))) or HEAD_RX.match(t):
                    heads.append(HEAD_RX.match(t).group(1) if HEAD_RX.match(t) else t)
        elif el.tag == W + 'tbl':
            g = [[_clean(''.join(x.text or '' for x in c.iter(W + 't'))) for c in r.iter(W + 'tc')] for r in el.iter(W + 'tr')]
            if len(g) > 1:
                tables.append({'title': heads[-1] if heads else '표', 'cols': g[0], 'rows': g[1:]})
                text.append(' / '.join(' | '.join(r) for r in g[:10]))
    return '\n'.join(text), tables, heads


def _pdf(path):
    import fitz
    doc = fitz.open(path)
    text, tables = [], []
    for page in doc:
        text.append(page.get_text())
        try:
            for tb in page.find_tables().tables[:3]:
                g = [[_clean(c) for c in r] for r in tb.extract()]
                if len(g) > 1:
                    tables.append({'title': f'{page.number + 1}쪽 표', 'cols': g[0], 'rows': g[1:]})
        except Exception:
            pass
    t = '\n'.join(text)
    return t, tables, [m.group(1) for l in t.splitlines() if (m := HEAD_RX.match(l))]


def _hwp_tables(path, heads):
    """한글 문서의 표를 행·열로 읽는다(맨 위 단계 표, 머리글 칸이 2개 이상인 것 — 표지·결재란처럼 배치용 표는 뺀다)."""
    import clone
    try:
        code, out = engines._java('Inspect', path)
        nodes = clone.parse(out.splitlines())
    except Exception:
        return []
    tables, head, grids = [], '', iter(clone.tables_of(nodes))
    for n in nodes:
        if n['kind'] == 'p' and n['ind'] == 0:
            t = clone.PUA.sub('', n['text']).strip()
            if t in heads:
                head = t
        elif n['kind'] == 'table' and n['ind'] == 2:
            g = next(grids, None)
            if g and len(g) > 1 and sum(1 for c in g[0] if c) >= 2:
                tables.append({'title': head or '표', 'cols': g[0], 'rows': g[1:40]})
    return tables


def _hwp(path):
    raw = engines.hwp_text(path)
    pua = re.compile('[\ue000-\uf8ff]')
    lines = [pua.sub('', l).strip() for l in raw]
    marked = [pua.sub('', l).strip() for l in raw if pua.match(l)]
    if marked:   # 코스콤 서식의 장 제목은 기호 글꼴 문자로 시작한다
        return '\n'.join(lines), _hwp_tables(path, marked), marked
    heads = []
    for l in lines:
        m = HEAD_RX.match(l)
        if m:
            heads.append(m.group(1))
        elif len(l) <= 14 and not re.search(r'[:/()\d]', l) and l.strip():
            heads.append(l.strip())
    return '\n'.join(lines), _hwp_tables(path, heads), heads


def _csv(path):
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'cp949'):
        try:
            s = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    g = [r for r in csv.reader(io.StringIO(s)) if any(r)]
    return s[:5000], ([{'title': os.path.basename(path), 'cols': g[0], 'rows': g[1:40]}] if len(g) > 1 else []), []


def _txt(path):
    raw = open(path, 'rb').read()
    try:
        s = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        s = raw.decode('cp949', 'replace')
    return s, [], [m.group(1) if (m := HEAD_RX.match(l)) else l.lstrip('# ').strip() for l in s.splitlines() if HEAD_RX.match(l) or l.startswith('#')]


def _html(path):
    import checks
    raw = open(path, encoding='utf-8', errors='replace').read()
    heads = [re.sub(r'<[^>]+>', '', h).strip() for h in re.findall(r'<h2[^>]*>(.*?)</h2>', raw, flags=re.S)]
    return checks.html_text(path), [], [h for h in heads if h and h != '목차']


READERS = {'xlsx': _xlsx, 'xlsm': _xlsx, 'pptx': _pptx, 'docx': _docx, 'pdf': _pdf, 'hwp': _hwp, 'csv': _csv, 'txt': _txt, 'md': _txt, 'html': _html, 'htm': _html}


def read(path, name):
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if is_drm(path, ext):
        return {'kind': ext, 'drm': True, 'text': '', 'tables': [], 'heads': []}
    fn = READERS.get(ext)
    if not fn:
        raise ValueError(f'.{ext} 파일은 아직 읽을 수 없습니다 (xlsx·pptx·docx·pdf·hwp·html·csv·txt)')
    text, tables, heads = fn(path)
    seen, hs = set(), []
    for h in heads:
        if h not in seen:
            seen.add(h)
            hs.append(h)
    return {'kind': ext, 'drm': False, 'text': text[:20000], 'tables': tables[:6], 'heads': hs[:12]}
