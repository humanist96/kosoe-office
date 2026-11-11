"""PPT 어댑터 — 전사 스킬 ppt-master의 koscom-chevron 덱으로 설계도를 편집 가능한 PPTX로 만든다.

1) 표지·목차·챕터·맺음: 셰브론 템플릿 SVG의 {{빈칸}}을 채운다.
2) 본문: 같은 템플릿의 머리말·꼬리말(06_card_grid) 위에 항목·카드·표·막대그래프를 셰브론 디자인 규칙(색·서체·간격)으로 그린다.
3) ppt-master `svg_to_pptx.py`로 네이티브 DrawingML PPTX로 변환한다(도형·글자 단위 편집 가능).
"""
import html
import os
import re
import subprocess
import sys

import corp
from core import ROOT, today_kr

CHEVRON = '.claude/skills/ppt-master/templates/decks/koscom-chevron/templates'
FB = "'KoPub돋움체 Bold', 'KoPubDotum Bold', Pretendard, 'Malgun Gothic', sans-serif"
FM = "'KoPub돋움체 Medium', 'KoPubDotum Medium', Pretendard, 'Malgun Gothic', sans-serif"
ORANGE, INK, INK2, LINE, TINT, PALE = '#ee6d1d', '#2b2b2e', '#6e6e73', '#dcdce0', '#fad3bb', '#f4f4f6'
BRAND = 'koscom'
E = html.escape


def _w(ch, fs):
    o = ord(ch)
    if ch == ' ':
        return fs * 0.3
    if 0xAC00 <= o <= 0xD7A3 or 0x3130 <= o <= 0x318F or 0x4E00 <= o <= 0x9FFF or 0xFF00 <= o <= 0xFFEF:
        return fs * 0.98
    if ch in 'il.,:;|!\'"·()[]':
        return fs * 0.3
    return fs * 0.56


def wrap(text, width, fs, max_lines=99):
    """단어 단위 줄바꿈(한국어 keep-all). 넘치면 마지막 줄을 …으로."""
    words = str(text).split(' ')
    lines, cur, cw = [], '', 0
    for w in words:
        ww = sum(_w(c, fs) for c in w)
        add = ww + (_w(' ', fs) if cur else 0)
        if cur and cw + add > width:
            lines.append(cur)
            cur, cw = w, ww
        else:
            cur, cw = (cur + ' ' + w) if cur else w, cw + add
        while cw > width and len(cur) > 1:          # 한 단어가 폭보다 길면 글자 단위로
            cut = ''
            acc = 0
            for c in cur:
                if acc + _w(c, fs) > width:
                    break
                cut += c
                acc += _w(c, fs)
            lines.append(cut)
            cur = cur[len(cut):]
            cw = sum(_w(c, fs) for c in cur)
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip()[:-1] + '…'
    return lines or ['']          # 빈 글(표의 빈 칸 등)도 빈 줄 하나 — 첫 줄([0])을 쓰는 곳이 넘어지지 않게


def text(x, y, s, fs=16, fill=INK, bold=False, anchor='start'):
    return (f'<text x="{x:.0f}" y="{y:.0f}" font-family="{FB if bold else FM}" font-size="{fs}" fill="{fill}"'
            + (f' text-anchor="{anchor}"' if anchor != 'start' else '') + f'>{E(str(s))}</text>')


def lines_svg(x, y, lines, fs, fill=INK, bold=False, lh=1.45):
    return ''.join(text(x, y + i * fs * lh, l, fs, fill, bold) for i, l in enumerate(lines)), y + len(lines) * fs * lh


def fill(svg, vals):
    return re.sub(r'\{\{([A-Z_0-9]+)\}\}', lambda m: E(str(vals.get(m.group(1), ''))), svg)


def num(s):
    m = re.fullmatch(r'\s*([-+]?[\d,]*\.?\d+)\s*(%|건|명|억|억원|만원|원|개|점|천만원|시간|분)?\s*', str(s))
    return float(m.group(1).replace(',', '')) if m else None


class Deck:
    def __init__(self):
        self.tpl = {}

    def t(self, name):
        if name not in self.tpl:
            self.tpl[name] = corp.read_text('koscom-doc-pack', f'{CHEVRON}/{name}')
        return self.tpl[name]

    # ── 앵커 페이지 ──
    def cover(self, bp, form, people):
        title = bp['title']
        return fill(self.t('01_cover.svg'), {'BRAND_MARK': BRAND, 'KICKER': form, 'TITLE': title if len(title) <= 22 else title[:21] + '…',
                                              'SUBTITLE': people.get('subtitle', ''), 'META_LINE': f"{today_kr()} | {people.get('dept', '')} {people.get('담당', '')}".strip(),
                                              'PAGE_LABEL': '01'})

    def agenda(self, secs, page):
        svg = self.t('02_agenda.svg')
        vals = {'BRAND_MARK': BRAND, 'KICKER': 'CONTENTS', 'TITLE': '목 차', 'SUBTITLE': 'Table of Contents', 'PAGE_LABEL': f'{page:02d}'}
        for i in range(1, 6):
            if i <= len(secs):
                s = secs[i - 1]
                tag = ' · '.join(it.get('label') for it in s['items'] if it.get('label'))[:40]
                vals.update({f'ITEM_{i}_NO': f'{i:02d}', f'ITEM_{i}_TITLE': s['heading'], f'ITEM_{i}_TAG': tag})
            else:
                svg = re.sub(rf'<g id="agenda-item-{i}">.*?</g>', '', svg, flags=re.S)
        return fill(svg, vals)

    def section(self, no, title, lead, page):
        return fill(self.t('03_section.svg'), {'BRAND_MARK': BRAND, 'SECTION_NO': f'{no:02d}', 'KICKER': 'CHAPTER', 'TITLE': title,
                                                'LEAD': lead, 'PAGE_LABEL': f'{page:02d}'})

    def closing(self, line, contact, page):
        return fill(self.t('10_closing.svg'), {'BRAND_MARK': BRAND, 'CLOSING_LINE': line, 'CONTACT_LINE': contact, 'PAGE_LABEL': f'{page:02d}'})

    # ── 본문 페이지 ──
    def body(self, no, sec, form, page):
        items = sec.get('items') or []
        tb = sec.get('table') if sec.get('table') and sec['table'].get('cols') and sec['table'].get('rows') else None
        base = self.t('06_card_grid.svg')
        head = {'BRAND_MARK': BRAND, 'KICKER': f'{no:02d}. {form}', 'TITLE': sec['heading'], 'PAGE_LABEL': f'{page:02d}'}
        cardable = (not tb and 2 <= len(items) <= 3 and all(len(it['text']) <= 80 for it in items))
        if cardable:
            head['LEAD'] = ''
            svg = base
            for i in range(1, 4):
                if i > len(items):
                    svg = re.sub(rf'<g id="card-{i}">.*?</g>', '', svg, flags=re.S)
                    continue
                it = items[i - 1]
                head[f'CARD_{i}_TITLE'] = it.get('label') or wrap(it['text'], 280, 18, 1)[0]
                head[f'CARD_{i}_BODY'] = '__BODY%d__' % i
            svg = fill(svg, head)
            for i, it in enumerate(items, 1):
                x = 108 + (i - 1) * 384
                if it.get('label'):
                    body = it['text']
                else:
                    first = wrap(it['text'], 280, 18, 1)[0]
                    body = it['text'][len(first):].strip()
                parts, y = lines_svg(x, 358, wrap(body, 296, 16, 7), 16, INK2) if body else ('', 358 - 16)
                for c in (it.get('children') or [])[:2]:
                    cl, y = lines_svg(x, y + 8, wrap('– ' + c['text'], 296, 14, 3), 14, INK2)
                    parts += cl
                svg = re.sub(rf'<text[^>]*>__BODY{i}__</text>', lambda m: parts, svg)
            return svg
        # 일반 본문: 카드 묶음을 지우고 직접 그린다
        svg = re.sub(r'<g id="card-\d">.*?</g>\s*', '', base, flags=re.S)
        lead_item = None
        if items and (tb or len(items) > 3) and len(items[0]['text']) <= 70 and not items[0].get('children'):
            lead_item, items = items[0], items[1:]
        head['LEAD'] = (lead_item['label'] + ' ' if lead_item and lead_item.get('label') else '') + (lead_item['text'] if lead_item else '')
        svg = fill(svg, head)
        parts = []
        top, bottom = 256, 640
        if tb:
            bx, bw = (80, 470) if items else (None, 0)
            tx, tw = (590, 610) if items else (80, 1120)
            if items:
                parts.append(self.bullets(items, bx, top, bw, bottom, 17))
            y = self.table(parts, tb, tx, top, tw)
            self.bars(parts, tb, tx, y + 24, tw, bottom)
        else:
            if len(items) > 5:
                half = (len(items) + 1) // 2
                parts.append(self.bullets(items[:half], 80, top, 540, bottom, 17))
                parts.append(self.bullets(items[half:], 660, top, 540, bottom, 17))
            else:
                parts.append(self.bullets(items, 80, top, 1120, bottom, 19))
        return svg.replace('</svg>', '\n'.join(parts) + '\n</svg>')

    def bullets(self, items, x, y, w, bottom, fs):
        out = []
        for it in items:
            if y > bottom - fs:
                break
            out.append(f'<rect x="{x}" y="{y - fs * 0.62:.0f}" width="8" height="8" fill="{ORANGE}"/>')
            tx = x + 22
            if it.get('label'):
                out.append(text(tx, y, it['label'], fs, INK, True))
                lw = sum(_w(c, fs) for c in it['label']) + fs * 0.8
                first = wrap(it['text'], w - 22 - lw, fs)[0]
                out.append(text(tx + lw, y, first, fs, INK))
                rest = it['text'][len(first):].strip()
                ls = wrap(rest, w - 22, fs, 3) if rest else []
                s, y = lines_svg(tx, y + fs * 1.45, ls, fs, INK)
                out.append(s)
            else:
                s, y = lines_svg(tx, y, wrap(it['text'], w - 22, fs, 4), fs, INK)
                out.append(s)
            for c in (it.get('children') or [])[:3]:
                s, y = lines_svg(tx + 6, y + 2, wrap('– ' + c['text'], w - 28, fs - 3, 2), fs - 3, INK2)
                out.append(s)
            y += fs * 0.9
        return ''.join(out)

    def table(self, parts, tb, x, y, w):
        cols, rws = [str(c) for c in tb['cols']], [[str(c) for c in r] for r in tb['rows'][:9]]
        n = len(cols)
        lens = [max([len(cols[j])] + [len(r[j]) if j < len(r) else 0 for r in rws]) + 2 for j in range(n)]
        tot = sum(lens)
        ws = [w * l / tot for l in lens]
        fs = 14 if n <= 4 else 12
        hh, rh = 40, 34
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{hh}" fill="{TINT}"/>')
        cx = x
        for j, c in enumerate(cols):
            parts.append(text(cx + 12, y + 26, wrap(c, ws[j] - 16, fs, 1)[0], fs, INK, True))
            cx += ws[j]
        yy = y + hh
        for r in rws:
            cx = x
            for j in range(n):
                v = r[j] if j < len(r) else ''
                if num(v) is not None and j:
                    parts.append(text(cx + ws[j] - 12, yy + 22, v, fs, INK, False, 'end'))
                else:
                    parts.append(text(cx + 12, yy + 22, wrap(v, ws[j] - 16, fs, 1)[0], fs, INK, j == 0))
                cx += ws[j]
            yy += rh
            parts.append(f'<line x1="{x}" y1="{yy}" x2="{x + w}" y2="{yy}" stroke="{LINE}" stroke-width="1"/>')
        parts.append(f'<line x1="{x}" y1="{y}" x2="{x + w}" y2="{y}" stroke="{INK}" stroke-width="1"/>')
        return yy

    def bars(self, parts, tb, x, y, w, bottom):
        cols, rws = tb['cols'], tb['rows'][:9]
        numeric = [j for j in range(1, len(cols)) if rws and all(num(r[j]) is not None for r in rws if j < len(r))]
        h = bottom - y
        if not numeric or h < 110 or len(rws) < 2:
            return
        j = numeric[0]
        vals = [num(r[j]) or 0 for r in rws]
        mx = max(vals) or 1
        n = len(vals)
        gap = 18
        bw = (w - gap * (n - 1)) / n
        base = y + h - 22
        parts.append(text(x, y + 2, f'{cols[j]}', 13, INK2))
        for i, v in enumerate(vals):
            bh = max(2, (h - 56) * v / mx)
            bx = x + i * (bw + gap)
            parts.append(f'<rect x="{bx:.1f}" y="{base - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{ORANGE if v == mx else LINE}"/>')
            parts.append(text(bx + bw / 2, base - bh - 6, rws[i][j], 12, INK, True, 'middle'))
            parts.append(text(bx + bw / 2, base + 16, wrap(str(rws[i][0]), bw + gap, 12, 1)[0], 12, INK2, False, 'middle'))
        parts.append(f'<line x1="{x}" y1="{base}" x2="{x + w}" y2="{base}" stroke="{INK}" stroke-width="1"/>')


def make(bp, template, people, path, job_dir, theme=None):
    """설계도 → PPTX. 돌려주는 값: 장 수. theme: 문서 테마(doc_themes) — 색·서체·표지 바탕만 바뀐다."""
    import doc_themes
    d = Deck()
    form = template['name']
    secs = bp['sections']
    proj = os.path.join(job_dir, 'ppt')
    out_dir = os.path.join(proj, 'svg_output')
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, f))
    with open(os.path.join(proj, 'spec_lock.md'), 'w', encoding='utf-8') as f:
        f.write('# spec_lock\n\n## pptx_structure\n- mode: flat\n')
    pages, kinds = [d.cover(bp, form, {**people, 'subtitle': template.get('desc', '')})], ['cover']
    if len(secs) >= 3:
        pages.append(d.agenda(secs, len(pages) + 1))
        kinds.append('agenda')
    for i, s in enumerate(secs, 1):
        pages.append(d.body(i, s, form, len(pages) + 1))
        kinds.append('body')
    pages.append(d.closing('감사합니다', f"{people.get('dept', '')} {people.get('담당', '')} · {today_kr()}", len(pages) + 1))
    kinds.append('closing')
    for i, svg in enumerate(pages, 1):
        svg = doc_themes.ppt_apply(svg, theme, kinds[i - 1])        # 문서 테마(색·서체·표지 바탕)
        svg = re.sub(r'\s(data-pptx-[a-z-]+)="[^"]*"', '', svg)      # flat 구조
        with open(os.path.join(out_dir, f'{i:02d}.svg'), 'w', encoding='utf-8') as f:
            f.write(svg)
    pm = corp.path('koscom-doc-pack', '.claude/skills/ppt-master')
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'run_ppt_master.py'), os.path.join(pm, 'scripts', 'svg_to_pptx.py'),
                        proj, '-s', 'output', '-q', '-o', path], capture_output=True, timeout=300)
    if r.returncode != 0 or not os.path.exists(path):
        raise RuntimeError('PPT 변환 실패(ppt-master): ' + (r.stdout + r.stderr).decode('utf-8', 'replace')[-400:])
    return len(pages)


if __name__ == '__main__':           # 자체검사: 표의 빈 칸 → 경량 렌더러로 넘어가던 IndexError
    assert wrap('', 100, 16, 1) == [''] and wrap('가 나', 100, 16) == ['가 나']
    print('ppt_chevron selftest OK')
