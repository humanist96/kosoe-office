"""설치 점검: python kosoe.py doctor  (AI 실제 호출까지: python kosoe.py doctor --ping)"""
import importlib
import os
import shutil
import subprocess
import sys

for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import CFG, HOME  # noqa: E402

ok_all = True


def say(ok, name, detail=''):
    global ok_all
    ok_all &= ok in (True, None)
    mark = {True: '✅', False: '❌', None: '⚠️ '}[ok]
    print(f'{mark} {name}' + (f' — {detail}' if detail else ''))


def main():
    print(f'코쇠오피스 점검 · 데이터 폴더 {HOME}\n')
    say(sys.version_info >= (3, 10), 'Python 3.10+', sys.version.split()[0])
    for m, pkg in (('flask', 'flask'), ('pptx', 'python-pptx'), ('openpyxl', 'openpyxl'), ('fitz', 'pymupdf'), ('PIL', 'pillow'),
                   ('yaml', 'pyyaml'), ('lxml', 'lxml'), ('numpy', 'numpy'), ('fontTools', 'fonttools')):
        try:
            importlib.import_module(m)
            say(True, f'파이썬 패키지 {pkg}')
        except Exception:
            say(False, f'파이썬 패키지 {pkg}', 'pip install -r requirements.txt')
    try:
        import run_ppt_master
        run_ppt_master.patch()
        from pptx import Presentation
        Presentation()
        say(True, 'python-pptx 기본 서식(메모리 공급)')
    except Exception as e:
        say(False, 'python-pptx 기본 서식', str(e)[:120])
    pkg_tpl = os.path.join(os.path.dirname(importlib.import_module('pptx').__file__), 'templates')
    if os.path.isdir(pkg_tpl) and any(f.endswith('.pia') for f in os.listdir(pkg_tpl)):
        say(None, '사내 보호 도구가 python-pptx 기본 서식을 암호화함', '코쇠오피스는 PyPI 원본 서식을 메모리로 공급해 동작 — 조치 불필요(보호 도구는 해제하지 않음)')

    mac = sys.platform == 'darwin'
    jv = ''
    if shutil.which('java'):
        r0 = subprocess.run(['java', '-version'], capture_output=True)
        jv = (r0.stderr or r0.stdout).decode('utf-8', 'replace').splitlines()[0] if r0.returncode == 0 else ''
    say(bool(jv), 'Java 8+ (한글 엔진)', jv or ('brew install openjdk 후 안내대로 PATH 연결(예: sudo ln -sfn $(brew --prefix)/opt/openjdk/libexec/openjdk.jdk '
                                               '/Library/Java/JavaVirtualMachines/openjdk.jdk)' if mac else 'JDK/JRE 설치 필요'))
    say(bool(shutil.which('git')), 'Git', shutil.which('git') or 'Git 설치 필요')
    gh = shutil.which('gh')
    r = subprocess.run(['gh', 'auth', 'status'], capture_output=True) if gh else None
    say(bool(r and r.returncode == 0), 'GitHub CLI 로그인 (스킬 저장소·전사 스킬)', 'gh auth login' if not (r and r.returncode == 0) else '')

    import skills
    import corp
    st = skills.ensure(force=True)
    say(st['mode'] == 'github', f"스킬 저장소 {skills.SLUG}", f"{st['mode']} {st['head'][:7]} {st['error'][:120]}")
    if st['mode'] == 'github':                       # 읽기만 되는 계정이면 문서는 만들지만 스킬 등록·승인이 실패한다
        w = skills.can_push()
        say(True if w else None, '스킬 저장소 쓰기 권한 (스킬 등록·승인)',
            '' if w else ('확인하지 못함(네트워크)' if w is None
                          else f'gh 계정에 {skills.SLUG} Write 권한 없음 — 문서 만들기는 되지만 스킬 등록은 실패합니다'))
    for c in corp.status():
        try:
            corp.ensure(c['id'])
            say(True, f"전사 스킬 {c['id']}", f"{c['repo']} @ {c['short']}")
        except Exception as e:
            say(False, f"전사 스킬 {c['id']}", f"{c['repo']} — 접근 권한 확인: {str(e)[:120]}")
    if '--smoke' in sys.argv:
        import engines
        bp = {'title': '점검 문서', 'sections': [{'heading': '개요', 'items': [{'label': '목적', 'text': '설치 점검', 'children': []}], 'table': None}]}
        for fmt in ('hwp', 'ppt', 'web'):
            try:
                p, w, ms, e = engines.make(fmt, bp, {'name': '점검', 'desc': ''}, {'dept': '점검팀', '담당': '점검'}, 'doctor', 1)
                say(not w, f'{fmt} 생성 ({e["name"]})', f'{ms}ms ' + '; '.join(w))
            except Exception as ex:
                say(False, f'{fmt} 생성', str(ex)[:160])

    import llm
    if CFG['llm_kind'] == 'claude_cli':
        st = llm.cli_status(True)
        say(bool(st['path']), 'Claude Code CLI (구독)', st['path'] or '.env의 KOSOE_CLAUDE_CLI 에 경로 지정')
        say(True if st['ready'] else None, 'Claude 로그인', st['detail'] if st['ready'] else f'python kosoe.py login  (그 전엔 규칙 기반 보조 모드)')
        if st['ready'] and '--ping' in sys.argv:
            p = llm.ping()
            say(p['ok'], f"AI 호출 ({llm.display()})", f"{p.get('ms')}ms" if p['ok'] else p['error'])
    else:
        say(None, f"AI: {CFG['llm_kind']}", llm.display())
    for k, h in llm.HOSTED.items():          # 외부 API(NVIDIA · OpenRouter) — 없어도 앱은 동작
        if CFG[h['key']]:
            say(True, f"{h['tag']} 키 (AI 선택에서 전환 가능)", ', '.join(CFG[h['models']]))
            if '--ping' in sys.argv:
                keep = llm.provider()
                llm.set_provider(k)
                p = llm.ping()
                llm.set_provider(keep)
                say(True if p['ok'] else None, f"{h['tag']} 호출 ({llm.chosen_models()[k]})", f"{p.get('ms')}ms" if p['ok'] else p['error'])
        else:
            say(None, f"{h['tag']} 키 없음", f"DeepSeek 등으로 바꿔 시연하려면 .env에 {h['env']}")
    if os.name == 'nt':
        pp = [p for p in (r'C:\Program Files\Microsoft Office\Office16\POWERPNT.EXE', r'C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE') if os.path.exists(p)]
        say(True if pp else None, 'PowerPoint (PPT 미리보기 그림)', '있음' if pp else '없으면 장별 SVG로 미리보기')
    else:
        say(True, 'PPT 미리보기', '장별 SVG(같은 디자인 원본)로 보여 줍니다')
        fonts = [os.path.expanduser('~/Library/Fonts'), '/Library/Fonts', os.path.expanduser('~/.local/share/fonts'), '/usr/share/fonts']
        has = any('KoPub' in f for d in fonts if os.path.isdir(d) for f in os.listdir(d))
        say(True if has else None, 'KoPub돋움체 (PPT 글꼴)', '설치됨' if has else '없으면 PPT를 열 때 다른 글꼴로 보입니다 — 무료 KoPub돋움체 설치 권장')
        say(None, '한글(.hwp) 열어 보기', '앱의 「미리보기」가 실제 파일을 그려 보여 줌(rhwp). 최종 확인은 한컴오피스 Mac·한컴독스(웹)')
    py = 'python' if os.name == 'nt' else 'python3'
    print('\n' + (f'준비 완료 — {py} kosoe.py' if ok_all else '❌ 항목을 먼저 해결하세요'))
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main())
