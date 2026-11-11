"""시험용 서버 — GitHub에 쓰지 않는 격리된 데이터 폴더(tests/_home_clone)로 앱을 띄운다.

    python tests/serve_local.py [포트]        (기본 8814)

스킬 등록(브랜치 · PR · 병합 · 태그)은 tests/_home_clone/origin.git(이 PC의 사본 저장소)에만 쌓인다. 화면의 PR 링크는 가짜 주소다.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ['KOSOE_HOME'] = os.path.join(ROOT, 'tests', '_home_clone')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(ROOT, 'tests'))
import make_local_home  # noqa: E402

make_local_home.ensure(os.environ['KOSOE_HOME'])     # 시험용 데이터 폴더가 없으면 만든다(실제 ~/.kosoe 에서 복사 — GitHub와 분리)

import app as A  # noqa: E402
import local_github  # noqa: E402

print('스킬 저장소 원격(이 PC의 사본):', local_github.install())
A.boot()
port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get('PORT') or 8814)
print(f'코쇠오피스(시험용) http://localhost:{port}')
A.app.run(host='127.0.0.1', port=port, threaded=True)
