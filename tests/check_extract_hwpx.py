"""hwpx 읽기 자체검사(앱 · 네트워크 · Java 불필요): python tests/check_extract_hwpx.py
가상 hwpx를 시험 안에서 만든다. 실제 사내 문서를 시험 자료로 커밋하지 않는다(저장소가 공개다).
"""
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding='utf-8', errors='replace')
import extract  # noqa: E402

NS = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
P = lambda t: f'<hp:p><hp:run><hp:t>{t}</hp:t></hp:run></hp:p>'
cell = lambda t: f'<hp:tc><hp:subList>{P(t)}</hp:subList></hp:tc>'
TBL = (f'<hp:p><hp:run><hp:tbl><hp:tr>{cell("항목")}{cell("금액")}</hp:tr>'
       f'<hp:tr>{cell("보증금")}{cell("120만원")}</hp:tr></hp:tbl></hp:run></hp:p>')


def make(path, body, raw_section=None):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('mimetype', 'application/hwp+zip')
        z.writestr('Contents/section0.xml', raw_section if raw_section is not None else
                   f'<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="{NS}">{body}</hs:sec>')


d = tempfile.mkdtemp()
ok_f = os.path.join(d, 'ok.hwpx')
make(ok_f, P('1. 추진 배경') + P('가상 회사 A의 시험 문단입니다.') + TBL + P('2. 향후 계획'))
r = extract.read(ok_f, '시험.hwpx')
assert r['kind'] == 'hwpx' and not r['drm'], r
assert r['heads'][0] == '추진 배경' and '향후 계획' in r['heads'], r['heads']
assert '120만원' in r['text'], r['text']
assert r['text'].count('보증금') == 1, r['text']            # 표 안 글이 두 번 들어가지 않는다
assert r['tables'] == [{'title': '표', 'cols': ['항목', '금액'], 'rows': [['보증금', '120만원']]}], r['tables']

not_zip = os.path.join(d, 'drm.hwpx')                      # DRM으로 감싼 파일: ZIP 서명 없음 → 🔐
open(not_zip, 'wb').write(b'SCDSA\x00 encrypted')
assert extract.read(not_zip, 'drm.hwpx')['drm'] is True

broken = os.path.join(d, 'broken.hwpx')                    # 본문이 XML이 아님(암호 · 손상) → 이유 있는 ValueError
make(broken, '', raw_section='\x00\x01 not xml')
try:
    extract.read(broken, 'broken.hwpx')
    raise SystemExit('깨진 본문은 ValueError여야 한다')
except ValueError as e:
    assert '암호' in str(e)

empty = os.path.join(d, 'empty.hwpx')                      # ZIP이지만 본문 구역이 없음
with zipfile.ZipFile(empty, 'w') as z:
    z.writestr('mimetype', 'application/hwp+zip')
try:
    extract.read(empty, 'empty.hwpx')
    raise SystemExit('본문이 없으면 ValueError여야 한다')
except ValueError as e:
    assert 'hwpx' in str(e)

try:                                                       # 아직 못 읽는 형식의 안내에 hwpx가 들어 있다
    extract.read(ok_f, '시험.xyz')
    raise SystemExit('모르는 형식은 ValueError여야 한다')
except ValueError as e:
    assert 'hwpx' in str(e)
print('check_extract_hwpx OK')
