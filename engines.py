"""설계도(blueprint) → 한글(.hwp) · PPT(.pptx) · 웹슬라이드(.html), 그리고 검수·자동 수정.

설계도 = {'title', 'sections': [{'heading', 'items': [{'label', 'text', 'children': [{'text'}]}], 'table': {'cols', 'rows'} | None}]}
"""
import base64
import html
import io
import json
import os
import re
import subprocess
import time

import checks
import corp
from core import CFG, DATA, ROOT, today_kr

OUT = os.path.join(DATA, 'out')
JOBS = os.path.join(DATA, 'jobs')
os.makedirs(OUT, exist_ok=True)
STATIC = os.path.join(ROOT, 'static')
HWP = 'koscom-hwp-report'
HWP_TEMPLATES = ['summary_base.hwp', 'summary_catalog.properties', 'detail_base.hwp', 'detail_catalog.properties']


def out_path(doc_id, ver, ext):
    d = os.path.join(OUT, doc_id)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f'v{ver}.{ext}')


def job_dir(doc_id, ver):
    d = os.path.join(JOBS, f'{doc_id}_v{ver}')
    os.makedirs(d, exist_ok=True)
    return d


def _java_cp():
    root = corp.path(HWP)
    e = corp.ENTRY[HWP]
    return os.pathsep.join([os.path.join(root, *e['lib'].split('/')), os.path.join(root, *e['jar'].split('/'))])


def _java(*args, timeout=60):
    r = subprocess.run(['java', '-Dfile.encoding=UTF-8', '-cp', _java_cp(), *args], capture_output=True, timeout=timeout)
    return r.returncode, r.stdout.decode('utf-8', 'replace') + r.stderr.decode('utf-8', 'replace')


def hwp_ready():
    try:
        return bool(corp.info(HWP)) and os.path.exists(os.path.join(corp.path(HWP), 'scripts', 'koscom-hwp.jar'))
    except Exception:
        return False


def num(s):
    m = re.fullmatch(r'\s*([-+]?[\d,]*\.?\d+)\s*(%|건|명|억|억원|만원|원|개|점|천만원)?\s*', str(s))
    return float(m.group(1).replace(',', '')) if m else None


# ───────────── 한글 ─────────────
def to_report(bp, template, people):
    """people = {'담당','팀장','부서장','dept'}"""
    secs = []
    for s in bp['sections']:
        items = []
        if s.get('table'):
            t = s['table']
            items.append({'type': 'table', 'style': 2, 'rows': [t['cols']] + t['rows']})
        for it in s['items']:
            o = {'type': 'o', 'text': it['text']}
            if it.get('label'):
                o['label'] = it['label']
            if it.get('children'):
                o['children'] = [{'type': 'dash', 'text': c['text']} for c in it['children']]
            items.append(o)
        if not items:
            items.append({'type': 'o', 'text': '(내용 없음)'})
        secs.append({'heading': s['heading'], 'items': items})
    rep = {'type': 'summary', 'title': bp['title'], 'date': today_kr(), 'dept': people.get('dept') or '○○팀',
           'approval': {k: people.get(k, '') for k in ('담당', '팀장', '부서장')}, 'sections': secs}
    if template.get('preset'):
        rep['preset'] = template['preset']
    return rep


def make_hwp(bp, template, people, path, jd):
    rep = to_report(bp, template, people)
    jp = os.path.join(jd, 'report.json')
    json.dump(rep, open(jp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # 기본 양식은 매번 git 객체에서 새로 꺼낸다(사내 보호 도구가 캐시 파일을 암호화해도 영향 없음)
    tdir = os.path.join(jd, 'templates')
    corp.fresh_copy(HWP, [f'templates/{n}' for n in HWP_TEMPLATES], tdir)
    code, out = _java('Renderer', jp, path, tdir)
    if code != 0 or not os.path.exists(path):
        raise RuntimeError('한글 렌더링 실패: ' + out.strip()[-300:])
    return [l[5:].strip() for l in out.splitlines() if l.startswith('WARN')]


def make_hwp_fill(bp, info, path, jd):
    """서식 채우기형 한글 스킬(목적별: 계약서·공문 등)로 만든다 — 설계도의 칸 값을 서식(.hwp)에 넣는다.
    info = 양식의 skill 정보({'corp': 전사 스킬 id, 'fill': form.yaml})."""
    import fillform
    cid, form = info['corp'], info['fill']
    values = fillform.to_values(bp, form)
    vp = os.path.join(jd, 'values.json')
    json.dump(values, open(vp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # 서식은 매번 git 객체에서 새로 꺼낸다(사내 보호 도구가 캐시 파일을 암호화해도 영향 없음)
    tpl = corp.fresh_copy(cid, [form['template']], os.path.join(jd, 'templates'))[0]
    root = corp.path(cid)
    cp = os.pathsep.join(os.path.join(root, *p.split('/')) for p in (form.get('lib') or 'lib/hwplib-1.1.9.jar', form['jar']))
    r = subprocess.run(['java', '-Dfile.encoding=UTF-8', '-cp', cp, 'FillRenderer', tpl, vp, path], capture_output=True, timeout=60)
    out = r.stdout.decode('utf-8', 'replace') + r.stderr.decode('utf-8', 'replace')
    if r.returncode != 0 or not os.path.exists(path):
        raise RuntimeError('한글 서식 채우기 실패: ' + out.strip()[-300:])
    return [l[5:].strip() for l in out.splitlines() if l.startswith('WARN')]


def make_xlsx_fill(bp, info, path, jd):
    """서식 채우기형 엑셀 스킬(목적별: 견적서 등)로 만든다 — 설계도의 칸 값을 서식(.xlsx)에 넣는다.
    스킬의 렌더러(form.yaml의 renderer, 기본 scripts/render.py)를 이 앱의 파이썬으로 돌린다: render.py values.json 결과.xlsx --template 서식.
    직인 같은 그림 자리는 채우지 않는다(값을 넘기지 않으므로 비어 나온다)."""
    import sys
    import fillform
    cid, form = info['corp'], info['fill']
    values = fillform.to_values(bp, form)
    vp = os.path.join(jd, 'values.json')
    json.dump(values, open(vp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # 서식과 렌더러는 매번 git 객체에서 새로 꺼낸다(고정된 커밋의 내용 그대로, 사내 보호 도구가 캐시 파일을 바꿔도 영향 없음)
    tpl, script = corp.fresh_copy(cid, [form['template'], form.get('renderer') or 'scripts/render.py'], os.path.join(jd, 'fill'))
    r = subprocess.run([sys.executable, script, vp, path, '--template', tpl], capture_output=True, timeout=120)
    out = r.stdout.decode('utf-8', 'replace') + r.stderr.decode('utf-8', 'replace')
    if r.returncode != 0 or not os.path.exists(path):
        raise RuntimeError('엑셀 서식 채우기 실패: ' + out.strip()[-300:])
    return [l[5:].strip() for l in out.splitlines() if l.startswith('WARN')]


def xlsx_text(path):
    """엑셀 파일의 칸 글(원본값 대조용). 숫자는 천 단위 쉼표를 붙인 모양으로도 함께 낸다."""
    from openpyxl import load_workbook
    lines = []
    for ws in load_workbook(path, data_only=True).worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = []
            for v in row:
                if isinstance(v, bool) or v is None:
                    continue
                if isinstance(v, (int, float)):
                    cells.append(f'{v:,}' if v == int(v) else f'{v:,.2f}')
                elif str(v).strip():
                    cells.append(str(v).strip())
            if cells:
                lines.append(' | '.join(cells))
    return lines


def hwp_text(path):
    """한글 파일의 문단 텍스트를 뽑는다(Inspect 출력의 따옴표 안)."""
    code, out = _java('Inspect', path)
    lines = []
    for l in out.splitlines():
        m = re.search(r'"(.*)"\s*$', l)
        if m and m.group(1).strip():
            lines.append(m.group(1).strip())
    return lines


# ───────────── PPT (Koscom Chevron) ─────────────
C = dict(orange=(0xEE, 0x6D, 0x1D), navy=(0x00, 0x33, 0x8D), navy_mid=(0x1F, 0x4B, 0x9B), ink=(0x2B, 0x2B, 0x2E),
         ink2=(0x6E, 0x6E, 0x73), grey=(0xEC, 0xEC, 0xEE), pale=(0xFD, 0xEE, 0xE4), white=(0xFF, 0xFF, 0xFF), tint=(0xED, 0xF4, 0xFB))
F_B, F_M = 'KoPub돋움체 Bold', 'KoPub돋움체 Medium'


def _kosoe_png():
    p = os.path.join(DATA, 'kosoe.png')
    if not os.path.exists(p):
        from PIL import Image
        Image.open(os.path.join(STATIC, 'kosoe.webp')).save(p)
    return p


def make_pptx(bp, template, people, path):
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.oxml.ns import qn
    from pptx.util import Emu, Pt

    rgb = lambda k: RGBColor(*C[k])
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    W, H = prs.slide_width, prs.slide_height
    px = lambda v: Emu(int(v * 12192000 / 1280))   # 1280×720 좌표계
    blank = prs.slide_layouts[6]

    def font(run, size, bold=True, color='ink'):
        run.font.size = Pt(size)
        run.font.bold = False
        run.font.color.rgb = rgb(color)
        name = F_B if bold else F_M
        run.font.name = name
        rpr = run._r.get_or_add_rPr()
        for tag in ('a:ea', 'a:cs'):
            el = rpr.find(qn(tag))
            if el is None:
                el = rpr.makeelement(qn(tag), {})
                rpr.append(el)
            el.set('typeface', name)

    def box(s, x, y, w, h, fill=None, shape=MSO_SHAPE.RECTANGLE):
        sh = s.shapes.add_shape(shape, px(x), px(y), px(w), px(h))
        sh.line.fill.background()
        if fill:
            sh.fill.solid()
            sh.fill.fore_color.rgb = rgb(fill)
        else:
            sh.fill.background()
        sh.shadow.inherit = False
        return sh

    def text(s, x, y, w, h, parts, size=16, color='ink', bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.15):
        tb = s.shapes.add_textbox(px(x), px(y), px(w), px(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = anchor
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        paras = parts if isinstance(parts, list) else [[(parts, {})]]
        for i, para in enumerate(paras):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = align
            p.line_spacing = spacing
            for t, o in para:
                r = p.add_run()
                r.text = t
                font(r, o.get('size', size), o.get('bold', bold), o.get('color', color))
            if i:
                p.space_before = Pt(o.get('gap', 6))
        return tb

    def chevrons(s, x, y, h, n=3, colors=('orange', 'orange', 'pale')):
        for i in range(n):
            box(s, x + i * h * 0.55, y, h * 0.7, h, colors[min(i, len(colors) - 1)], MSO_SHAPE.CHEVRON)

    def footer(s, n):
        box(s, 0, 708, 1280, 12, 'navy')
        text(s, 60, 676, 600, 20, [[('KOSCOM', {'bold': True, 'size': 10, 'color': 'navy'}), ('   ' + bp['title'], {'size': 10, 'color': 'ink2', 'bold': False})]])
        text(s, 1120, 676, 100, 20, f'{n:02d}', size=10, color='ink2', align=PP_ALIGN.RIGHT)

    # 1. 표지 — 흰 바탕, 오른쪽 큰 셰브런 위 코쇠
    s = prs.slides.add_slide(blank)
    box(s, 0, 0, 1280, 720, 'white')
    for i, (c, a) in enumerate((('grey', 0), ('pale', 1), ('orange', 2))):
        box(s, 700 + i * 115, 120, 300, 480, c, MSO_SHAPE.CHEVRON)
    s.shapes.add_picture(_kosoe_png(), px(930), px(255), px(180), px(180))
    box(s, 80, 210, 64, 8, 'orange')
    text(s, 80, 240, 680, 200, bp['title'], size=40, bold=True, color='ink', anchor=MSO_ANCHOR.TOP, spacing=1.05)
    text(s, 80, 470, 640, 60, [[(template['name'], {'size': 16, 'color': 'orange', 'bold': True})],
                               [(f"{people.get('dept', '')}  ·  {people.get('담당', '')}  ·  {today_kr()}", {'size': 14, 'color': 'ink2', 'bold': False, 'gap': 8})]])
    box(s, 0, 680, 1280, 40, 'navy')
    text(s, 80, 688, 300, 24, 'KOSCOM', size=14, bold=True, color='white', anchor=MSO_ANCHOR.MIDDLE)

    # 2. 목차
    s = prs.slides.add_slide(blank)
    box(s, 0, 0, 420, 720, 'navy')
    text(s, 70, 110, 300, 60, 'CONTENTS', size=34, bold=True, color='white')
    chevrons(s, 70, 190, 36, 3, ('orange', 'orange', 'navy_mid'))
    secs = bp['sections']
    step = min(90, 520 / max(1, len(secs)))
    for i, sec in enumerate(secs):
        y = 110 + i * step
        text(s, 500, y, 90, 50, f'{i + 1:02d}', size=30, bold=True, color='orange')
        text(s, 600, y + 6, 600, 50, sec['heading'], size=22, bold=True, color='ink')
        box(s, 500, y + step - 16, 700, 1.5, 'grey')

    # 3. 본문 — 장마다 한 장
    for i, sec in enumerate(secs):
        s = prs.slides.add_slide(blank)
        chevrons(s, 60, 52, 34, 2)
        text(s, 130, 46, 900, 50, [[(f'{i + 1:02d}  ', {'color': 'orange', 'size': 26, 'bold': True}), (sec['heading'], {'size': 26, 'bold': True})]])
        box(s, 60, 112, 1160, 2, 'grey')
        tb = sec.get('table')
        has_tb = bool(tb and tb.get('cols') and tb.get('rows'))
        left_w = 520 if has_tb else 1160
        y = 140
        paras = []
        for it in sec['items']:
            p = [('■ ', {'color': 'orange', 'size': 15, 'bold': True})]
            if it.get('label'):
                p.append((it['label'] + '  ', {'color': 'navy', 'size': 17, 'bold': True}))
            p.append((it['text'], {'size': 17, 'bold': False}))
            paras.append(p)
            for c in it.get('children') or []:
                paras.append([('    - ' + c['text'], {'size': 14, 'color': 'ink2', 'bold': False, 'gap': 2})])
        if paras:
            text(s, 60, y, left_w, 520, paras, size=17, spacing=1.3 if len(paras) < 5 else 1.2)
        if has_tb:
            cols, rws = tb['cols'], tb['rows'][:10]
            numeric = [j for j in range(1, len(cols)) if all(num(r[j]) is not None for r in rws if j < len(r))]
            tx, tw = (620 if paras else 60), (600 if paras else 1160)
            wordy = any(len(str(c)) > 18 for r in rws for c in r)
            th = min(46 * (len(rws) + 1), 300 if numeric else 520)
            g = s.shapes.add_table(len(rws) + 1, len(cols), px(tx), px(140), px(tw), px(th)).table
            for j, c in enumerate(cols):
                cell = g.cell(0, j)
                cell.fill.solid(); cell.fill.fore_color.rgb = rgb('navy')
                cell.text = str(c)
                font(cell.text_frame.paragraphs[0].runs[0], 13, True, 'white')
                cell.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
            for r_i, r in enumerate(rws):
                for j in range(len(cols)):
                    cell = g.cell(r_i + 1, j)
                    cell.fill.solid(); cell.fill.fore_color.rgb = rgb('tint' if r_i % 2 else 'white')
                    cell.text = str(r[j]) if j < len(r) else ''
                    runs = cell.text_frame.paragraphs[0].runs
                    if runs:
                        font(runs[0], 12 if not wordy else 11, j == 0, 'ink')
                    # 긴 문장 칸은 왼쪽 정렬, 숫자·짧은 값은 가운데
                    short = num(cell.text) is not None or len(cell.text) <= 10
                    cell.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER if (j and short) else PP_ALIGN.LEFT
            if numeric:
                cd = CategoryChartData()
                cd.categories = [str(r[0]) for r in rws]
                for j in numeric[:3]:
                    cd.add_series(str(cols[j]), [num(r[j]) or 0 for r in rws])
                ch = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, px(tx), px(160 + th), px(tw), px(640 - 160 - th), cd).chart
                ch.has_legend = len(numeric) > 1
                if ch.has_legend:
                    ch.legend.position = XL_LEGEND_POSITION.TOP
                    ch.legend.include_in_layout = False
                for k, ser in enumerate(ch.series):
                    ser.format.fill.solid()
                    ser.format.fill.fore_color.rgb = rgb(('orange', 'navy', 'ink2')[k])
                ch.value_axis.has_major_gridlines = False
                ch.font.size = Pt(10)
        footer(s, i + 3)

    # 4. 마무리
    s = prs.slides.add_slide(blank)
    box(s, 0, 0, 1280, 720, 'navy')
    for i, c in enumerate(('navy_mid', 'orange', 'orange')):
        box(s, 760 + i * 100, 180, 240, 360, c, MSO_SHAPE.CHEVRON)
    text(s, 100, 290, 700, 80, '감사합니다', size=48, bold=True, color='white')
    text(s, 100, 380, 700, 40, f"{people.get('dept', '')} {people.get('담당', '')}", size=16, color='white', bold=False)
    prs.save(path)
    return len(prs.slides)


def pptx_text(path):
    from pptx import Presentation
    out = []
    for s in Presentation(path).slides:
        for sh in s.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                out.append(sh.text_frame.text.strip())
            if sh.has_table:
                for r in sh.table.rows:
                    out.append(' | '.join(c.text for c in r.cells))
    return out


# ───────────── 웹슬라이드 ─────────────
def _b64(name):
    return base64.b64encode(open(os.path.join(STATIC, name), 'rb').read()).decode()


WEB_CSS = '''
@font-face{font-family:KoPub;font-weight:700;src:url(data:font/woff2;base64,__B__) format('woff2')}
@font-face{font-family:KoPub;font-weight:500;src:url(data:font/woff2;base64,__M__) format('woff2')}
:root{--o:#ee6d1d;--n:#00338d;--ink:#2b2b2e;--ink2:#6e6e73;--g:#ececee;--p:#fdeee4}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:#0b1830;font-family:KoPub,'Malgun Gothic',sans-serif;color:var(--ink);word-break:keep-all;overflow-wrap:break-word}
#deck{height:100%;overflow-y:auto;scroll-snap-type:y mandatory}
.s{height:100vh;scroll-snap-align:start;display:flex;align-items:center;justify-content:center;padding:3vh 3vw}
.card{position:relative;width:min(100%,calc(94vh*16/9));aspect-ratio:16/9;background:#fff;border-radius:14px;overflow:hidden;
 padding:5.5% 6%;box-shadow:0 30px 80px rgba(0,0,0,.35);transform:perspective(1400px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg));transition:transform .25s ease-out}
.card.navy{background:var(--n);color:#fff}
.chev{position:absolute;width:30%;height:70%;clip-path:polygon(0 0,62% 0,100% 50%,62% 100%,0 100%,38% 50%);transition:transform .6s cubic-bezier(.2,.8,.2,1)}
.cover .chev{top:15%;width:24%}
.cover .c1{right:30%;background:var(--g)}.cover .c2{right:20%;background:var(--p)}.cover .c3{right:10%;background:var(--o)}
.cover img{position:absolute;right:12%;top:33%;width:15%;animation:bob 3.2s ease-in-out infinite}
@keyframes bob{50%{transform:translateY(-4%) rotate(-3deg)}}
.cover .bar{width:5%;height:1.1%;background:var(--o);margin-bottom:3%}
h1{position:relative;z-index:2;font-size:clamp(20px,3.2vw,50px);line-height:1.15;max-width:46%;font-weight:700}
.meta{margin-top:3%;font-size:clamp(11px,1.15vw,18px);color:var(--ink2);font-weight:500}.meta b{color:var(--o)}
.foot{position:absolute;left:0;right:0;bottom:0;height:5.5%;background:var(--n);color:#fff;font-weight:700;font-size:clamp(9px,.9vw,14px);display:flex;align-items:center;padding:0 6%}
.hd{display:flex;align-items:baseline;gap:1.2%;border-bottom:2px solid var(--g);padding-bottom:1.6%;margin-bottom:3%}
.hd i{font-style:normal;color:var(--o);font-weight:700;font-size:clamp(16px,2.2vw,34px)}
.hd h2{font-size:clamp(16px,2.2vw,34px)}
.body{display:grid;grid-template-columns:1fr;gap:4%;height:76%}.body.two{grid-template-columns:1fr 1.1fr}
ul{list-style:none;display:flex;flex-direction:column;gap:3.5%}
li{font-size:clamp(11px,1.35vw,21px);line-height:1.5;font-weight:500;opacity:0;transform:translateY(14px);transition:.5s ease}
.on li{opacity:1;transform:none}.on li:nth-child(2){transition-delay:.1s}.on li:nth-child(3){transition-delay:.2s}.on li:nth-child(4){transition-delay:.3s}
li:before{content:'';display:inline-block;width:.55em;height:.55em;background:var(--o);margin-right:.6em;vertical-align:.1em;clip-path:polygon(0 0,60% 0,100% 50%,60% 100%,0 100%,40% 50%)}
li b{color:var(--n);margin-right:.5em}li small{display:block;margin:.3em 0 0 1.2em;color:var(--ink2);font-size:.82em}
li:hover{color:var(--n)}
table{border-collapse:collapse;width:100%;font-size:clamp(9px,1.05vw,16px)}
th{background:var(--n);color:#fff;padding:.55em .6em;font-weight:700}td{padding:.5em .6em;text-align:center;border-bottom:1px solid var(--g);font-weight:500}
td:first-child,td.l{text-align:left}td:first-child{font-weight:700}tr:hover td{background:var(--p)}
.vis{display:flex;flex-direction:column;gap:4%;min-height:0}.vis canvas{flex:1;min-height:0}
.end{display:flex;flex-direction:column;justify-content:center}.end h1{color:#fff}.end .chev{top:20%}
.end .c1{right:26%;background:#1f4b9b}.end .c2{right:16%;background:var(--o)}.end .c3{right:6%;background:var(--o)}
#nav{position:fixed;right:18px;top:50%;transform:translateY(-50%);display:flex;flex-direction:column;gap:8px}
#nav a{width:9px;height:9px;border-radius:50%;background:rgba(255,255,255,.35)}#nav a.cur{background:var(--o);height:22px;border-radius:5px}
'''

WEB_JS = '''
const deck=document.getElementById('deck'),ss=[...document.querySelectorAll('.s')],nav=document.getElementById('nav');
ss.forEach((s,i)=>{const a=document.createElement('a');a.href='#';a.onclick=e=>{e.preventDefault();s.scrollIntoView({behavior:'smooth'})};nav.appendChild(a)});
const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){const i=ss.indexOf(e.target);e.target.classList.add('on');
 [...nav.children].forEach((a,j)=>a.classList.toggle('cur',j==i));const c=e.target.querySelector('canvas');if(c&&!c._c)draw(c)}}),{threshold:.6});ss.forEach(s=>io.observe(s));
document.addEventListener('keydown',e=>{const i=[...nav.children].findIndex(a=>a.classList.contains('cur'));
 if(['ArrowDown','PageDown',' ','ArrowRight'].includes(e.key)){e.preventDefault();ss[Math.min(i+1,ss.length-1)].scrollIntoView({behavior:'smooth'})}
 if(['ArrowUp','PageUp','ArrowLeft'].includes(e.key)){e.preventDefault();ss[Math.max(i-1,0)].scrollIntoView({behavior:'smooth'})}});
document.querySelectorAll('.card').forEach(c=>{c.onmousemove=e=>{const r=c.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;
 c.style.setProperty('--ry',(x*4)+'deg');c.style.setProperty('--rx',(-y*4)+'deg');c.querySelectorAll('.chev').forEach((v,k)=>v.style.transform=`translate(${x*(k+1)*14}px,${y*(k+1)*10}px)`)};
 c.onmouseleave=()=>{c.style.setProperty('--ry','0deg');c.style.setProperty('--rx','0deg');c.querySelectorAll('.chev').forEach(v=>v.style.transform='')}});
function draw(c){if(!window.Chart)return;const d=JSON.parse(c.dataset.chart);const pal=['#ee6d1d','#00338d','#8c8c92'];
 c._c=new Chart(c,{type:'bar',data:{labels:d.labels,datasets:d.series.map((s,k)=>({label:s.name,data:s.data,backgroundColor:pal[k],borderRadius:6}))},
 options:{maintainAspectRatio:false,animation:{duration:1100,easing:'easeOutQuart'},plugins:{legend:{display:d.series.length>1}},scales:{y:{grid:{color:'#ececee'}},x:{grid:{display:false}}}}});
 c.parentElement.onmouseenter=()=>{c._c.reset();c._c.update()}}
'''


def make_web(bp, template, people, path):
    e = html.escape
    chart_js = ''
    slides = [f'''<section class="s"><div class="card cover"><div class="chev c1"></div><div class="chev c2"></div><div class="chev c3"></div>
<img alt="" src="data:image/webp;base64,{_b64('kosoe.webp')}"><div class="bar"></div><h1>{e(bp['title'])}</h1>
<p class="meta"><b>{e(template['name'])}</b> · {e(people.get('dept', ''))} · {e(people.get('담당', ''))} · {today_kr()}</p><div class="foot">KOSCOM</div></div></section>''']
    for i, sec in enumerate(bp['sections']):
        lis = ''.join(f"<li>{'<b>' + e(it['label']) + '</b>' if it.get('label') else ''}{e(it['text'])}"
                      + ''.join(f"<small>– {e(c['text'])}</small>" for c in it.get('children') or []) + '</li>' for it in sec['items'])
        vis = ''
        tb = sec.get('table')
        if tb and tb.get('cols') and tb.get('rows'):
            cols, rws = tb['cols'], tb['rows'][:10]
            vis = '<table><tr>' + ''.join(f'<th>{e(str(c))}</th>' for c in cols) + '</tr>' + ''.join(
                '<tr>' + ''.join(f'<td{" class=l" if j < len(r) and num(r[j]) is None and len(str(r[j])) > 10 else ""}>{e(str(r[j]) if j < len(r) else "")}</td>' for j in range(len(cols))) + '</tr>' for r in rws) + '</table>'
            numeric = [j for j in range(1, len(cols)) if all(num(r[j]) is not None for r in rws if j < len(r))]
            if numeric:
                d = {'labels': [str(r[0]) for r in rws], 'series': [{'name': str(cols[j]), 'data': [num(r[j]) or 0 for r in rws]} for j in numeric[:3]]}
                vis += f"<canvas data-chart='{e(json.dumps(d, ensure_ascii=False))}'></canvas>"
                chart_js = open(os.path.join(STATIC, 'chart.umd.min.js'), encoding='utf-8').read()
            vis = f'<div class="vis">{vis}</div>'
        two = ' two' if (vis and lis) else ''
        slides.append(f'''<section class="s"><div class="card"><div class="hd"><i>{i + 1:02d}</i><h2>{e(sec['heading'])}</h2></div>
<div class="body{two}">{'<ul>' + lis + '</ul>' if lis else ''}{vis}</div><div class="foot">KOSCOM &nbsp;·&nbsp; {e(bp['title'])}</div></div></section>''')
    slides.append(f'''<section class="s"><div class="card navy end"><div class="chev c1"></div><div class="chev c2"></div><div class="chev c3"></div>
<h1>감사합니다</h1><p class="meta" style="color:#fff">{e(people.get('dept', ''))} {e(people.get('담당', ''))}</p></div></section>''')
    css = WEB_CSS.replace('__B__', _b64('KoPubDotum-Bold.woff2')).replace('__M__', _b64('KoPubDotum-Medium.woff2'))
    page = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(bp["title"])}</title><style>{css}</style></head><body><main id="deck">{"".join(slides)}</main><nav id="nav"></nav>'
            f'<script>{chart_js}</script><script>{WEB_JS}</script></body></html>')
    open(path, 'w', encoding='utf-8').write(page)
    return len(slides)


# ───────────── 검수 ─────────────
BAD_END = re.compile(r'(니다|했다|한다|이다|있다|없다|된다)\.?$')   # 합니다 · 바랍니다 · 드립니다 … 모두(측정 SENT_END와 같은 범위)
DATE_RX = checks.DATE_RX


def _all_items(bp):
    for s in bp['sections']:
        for it in s['items']:
            yield it
            for c in it.get('children') or []:
                yield c


def check(bp, warns=(), style=None, fixed=()):
    """문체 검수. style이 없으면 코스콤 보고 문법, 있으면 그 스킬의 문체(대표 문서에서 잰 기준).
    fixed(스킬의 고정 문구)는 글자 그대로 넣어야 하는 글이라 문체 검사에서 뺀다."""
    st = checks.norm_style(style)
    fixed = [str(f) for f in fixed]
    slots = checks.slots_of(fixed)                       # 고정 문구의 [칸 이름] — 안 채워진 채 남으면 '확인 필요'
    all_items = list(_all_items(bp))
    items = [it for it in all_items if not checks.is_fixed_item(it['text'], fixed)]
    out = []
    if st['date'] != 'any':
        dates = [m.group(0) for it in items for m in DATE_RX.finditer(it['text']) if not checks.date_ok(m, st['date'])]
        out.append({'id': 'date', 'name': f"날짜 형식 ({checks.fmt_date(2026, 10, 28, st['date'])})", 'ok': not dates, 'detail': ', '.join(dates[:3]), 'fix': bool(dates)})
    if st['max_len']:
        long = [it['text'] for it in items if len(it['text']) > st['max_len']]
        out.append({'id': 'long', 'name': f"항목 길이 {st['max_len']}자 이내", 'ok': not long, 'detail': f'{len(long)}개 초과' if long else '', 'fix': bool(long)})
    if st['ending'] != 'any':
        bad = BAD_END if st['ending'] == 'noun' else checks.NOUN_END
        ends = [it['text'] for it in items if bad.search(it['text'].strip())]
        # 대표 문서에서 잰 명사형은 측정과 같은 비율까지 서술형을 허용한다(기안문의 결재 요청 문장 한 줄 등).
        # 코스콤 보고 문법 기본값은 그대로 0.
        allow = int(len(items) * checks.NOUN_TOLERANCE) if st['ending'] == 'noun' and not checks.is_default_style(style) else 0
        eg = f" — 예: 「…{ends[0].strip()[-30:]}」" if ends else ''          # 어느 문장이 걸렸는지 보이게
        out.append({'id': 'end', 'name': checks.ENDINGS[st['ending']], 'ok': len(ends) <= allow,
                    'detail': ((f'{len(ends)}개 문장형' if st['ending'] == 'noun' else f'{len(ends)}개 개조식(~함·~임)') + eg) if ends else '',
                    'fix': len(ends) > allow})
    todo = [it['text'] for it in all_items if '확인 필요' in it['text'] or '반영 예정' in it['text'] or any(s in it['text'] for s in slots)]
    empty = [s['heading'] for s in bp['sections'] if not s['items'] and not s.get('table')]
    return out + [
        {'id': 'empty', 'name': '빈 장 없음', 'ok': not empty, 'detail': ', '.join(empty), 'fix': False},
        {'id': 'todo', 'name': '확인 필요 표시 없음', 'ok': not todo, 'detail': f'{len(todo)}곳 — 직접 확인해 주세요' if todo else '', 'fix': False},
        {'id': 'render', 'name': '한글 쪽 넘침·서식 경고 없음', 'ok': not warns, 'detail': '; '.join(warns)[:200], 'fix': any('[제목]' in w for w in warns)},
    ]


ENDS = [('했습니다', '했음'), ('하였습니다', '하였음'), ('되었습니다', '되었음'), ('바랍니다', '바람'), ('드립니다', '드림'), ('합니다', '함'), ('됩니다', '됨'), ('입니다', '임'),
        ('습니다', '음'), ('한다', '함'), ('된다', '됨'), ('이다', '임'), ('있다', '있음'), ('없다', '없음'), ('했다', '했음')]
# 서술형 문체(계약서·공문 등)로 되돌릴 때: 개조식 → 평서문 / 존댓말
ENDS_PLAIN = [('하였음', '하였다'), ('되었음', '되었다'), ('했음', '했다'), ('있음', '있다'), ('없음', '없다'), ('함', '한다'), ('됨', '된다'), ('임', '이다')]
ENDS_POLITE = [('하였음', '하였습니다'), ('되었음', '되었습니다'), ('했음', '했습니다'), ('있음', '있습니다'), ('없음', '없습니다'), ('함', '합니다'),
               ('됨', '됩니다'), ('임', '입니다')]


def autofix(bp, shorten_fn, warns=(), style=None, fixed=()):
    st = checks.norm_style(style)
    fixed = [str(f) for f in fixed]
    b = json.loads(json.dumps(bp))
    items = [it for it in _all_items(b) if not checks.is_fixed_item(it['text'], fixed)]
    # 대표 문서 기준 명사형에서 허용치 안의 서술형(결재 요청 문장 등)은 검수가 통과시키므로 고치지 않는다 — check()와 같은 기준
    noun_fix = st['ending'] == 'noun' and (checks.is_default_style(style) or sum(1 for it in items if BAD_END.search(it['text'].strip()))
                                           > int(len(items) * checks.NOUN_TOLERANCE))
    for it in items:
        t = it['text']
        if st['date'] != 'any':
            t = DATE_RX.sub(lambda m: m.group(0) if checks.date_ok(m, st['date']) else checks.fmt_date(*checks.date_parts(m), st['date']), t)
        t = t.strip()
        if noun_fix:
            t = t.rstrip('.')
            for a, z in ENDS:
                if t.endswith(a):
                    t = t[: -len(a)] + z
                    break
        elif st['ending'] in ('plain', 'polite'):
            core = t.rstrip('.')
            for a, z in (ENDS_PLAIN if st['ending'] == 'plain' else ENDS_POLITE):
                if core.endswith(a):
                    t = core[: -len(a)] + z + '.'
                    break
        it['text'] = t
    long = [it for it in items if st['max_len'] and len(it['text']) > st['max_len']]
    meta = None
    if long:
        short, meta = shorten_fn([it['text'] for it in long])
        for it, s in zip(long, short):
            it['text'] = s
    if any('[제목]' in w for w in warns):
        b['title'] = short_title(b['title'])
    return b, meta


def short_title(t, n=22):
    """제목 칸(한 줄 약 22자)에 맞게 단어 단위로 자른다."""
    t = re.sub(r'\s+', ' ', t).strip()
    if len(t) <= n:
        return t
    out = ''
    for w in t.split(' '):
        if len((out + ' ' + w).strip()) > n:
            break
        out = (out + ' ' + w).strip()
    return out or t[:n]


def engine_of(fmt):
    """화면 표시용: 이 형식을 만드는 전사 스킬과 고정 버전."""
    cid = {'hwp': HWP, 'ppt': 'koscom-doc-pack', 'web': 'koscom-webslide'}[fmt]
    c = corp.info(cid) or {}
    name = {'hwp': 'koscom-hwp-report', 'ppt': 'ppt-master · koscom-chevron', 'web': 'koscom-webslide'}[fmt]
    return {'corp': cid, 'name': name, 'sha': (c.get('sha') or '')[:7]}


def fill_engine(cid):
    c = corp.info(cid) or {}
    return {'corp': cid, 'name': f'{cid} · 서식 채우기', 'sha': (c.get('sha') or '')[:7]}


def make(fmt, bp, template, people, doc_id, ver, theme=None):
    """theme: 문서 테마(doc_themes) — PPT·웹의 겉모습만 바꾼다. 한글은 양식 그대로."""
    t0 = time.time()
    ext = {'hwp': 'hwp', 'ppt': 'pptx', 'web': 'html', 'xlsx': 'xlsx'}[fmt]
    path = out_path(doc_id, ver, ext)
    jd = job_dir(doc_id, ver)
    warns = []
    info = template.get('skill') or {}
    if isinstance(info, str):
        info = json.loads(info or '{}') or {}
    if fmt == 'xlsx':                              # 엑셀은 서식 채우기형 전사 스킬(견적서 등)로만 만든다
        if not info.get('fill') or corp.fill_fmt(info['fill']) != 'xlsx':
            raise RuntimeError('엑셀은 엑셀 서식 채우기형 양식(견적서 등)에서만 만들 수 있습니다')
        return path, make_xlsx_fill(bp, info, path, jd), int((time.time() - t0) * 1000), fill_engine(info['corp'])
    engine = engine_of(fmt)
    if fmt == 'hwp' and info.get('fill'):          # 목적별 한글 스킬(서식 채우기형)
        engine = fill_engine(info['corp'])
        warns = make_hwp_fill(bp, info, path, jd)
    elif fmt == 'hwp':
        warns = make_hwp(bp, template, people, path, jd)
    elif fmt == 'ppt':
        try:
            if CFG['ppt_engine'] != 'ppt-master':
                raise RuntimeError('설정: 경량 PPT 엔진')
            import ppt_chevron
            ppt_chevron.make(bp, template, people, path, jd, theme)
        except Exception as e:
            import run_ppt_master
            run_ppt_master.patch()
            make_pptx(bp, template, people, path)
            warns.append(f'[PPT] 전사 ppt-master 변환 대신 경량 렌더러 사용: {str(e)[:120]}')
            engine = {**engine, 'name': '경량 Chevron 렌더러(대체)'}
    else:
        try:
            import webslide
            webslide.make(bp, template, people, path, jd, template.get('chain_names'), theme)
        except Exception as e:
            make_web(bp, template, people, path)
            warns.append(f'[웹] 전사 webslide 대신 경량 웹 렌더러 사용: {str(e)[:120]}')
            engine = {**engine, 'name': '경량 웹 렌더러(대체)'}
    return path, warns, int((time.time() - t0) * 1000), engine
