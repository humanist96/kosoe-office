// 코쇠오피스 — 양식 · 스킬 · ★스킬 만들기 · 검수 화면 (index.html이 불러온다)

// ───────────── 양식 ─────────────
async function vTemplates() {
  const d = await api('/api/templates'); TPLS = d.templates;
  $('#main').innerHTML = `<div class="page-h"><div><h2>양식</h2><p>양식은 스킬이 만드는 문서 종류입니다. 전사 양식은 전사 공용 스킬이, 부서·개인 양식은 그 스킬을 상속한 부서·개인 스킬이 만듭니다.</p></div>
    <button class="btn o" onclick="go('register')">★ 대표 문서로 스킬 만들기</button></div>
  <div class="card" style="overflow:hidden"><table class="list"><tr><th>양식</th><th>형식 · 스킬(상속)</th><th>범위</th><th>등급</th><th>저장소 경로 · 태그</th><th>사용</th><th></th></tr>
  ${TPLS.map(t => `<tr><td><b>${esc(t.name)}</b><br><span class="small muted">${t.outline.map(esc).join(' › ')}</span></td><td>${fmtTag(t.fmt)}<br><span class="small muted">🧩 ${esc(t.skill)}</span></td>
    <td><span class="chip ${t.scope === 'corp' ? '' : 'o'}">${SCOPE[t.scope]}</span><br><span class="small muted">${esc(t.team || t.dept || '')}</span></td><td>${gradeTag(t.grade)}</td>
    <td class="small"><a href="#" onclick="showYaml('${esc(t.path)}');return false"><code>${esc(t.path)}${t.path.endsWith('.yaml') ? '' : '/'}</code></a><br><span class="muted">${t.tag ? '🏷 ' + esc(t.tag) : ''}</span></td><td>${t.uses}</td>
    <td>${t.usable ? `<button class="btn sm" onclick="PICK='${t.id}';go('new')">작성</button>` : `<span class="small" style="color:var(--bad)">${esc(t.blocked || '권한 없음')}</span>`}</td></tr>`).join('')}</table></div>`;
}
async function showYaml(path) {
  const p = path.endsWith('.yaml') ? path : path + '/kosoe-skill.yaml';
  const d = await api('/api/skills-file?path=' + encodeURIComponent(p));
  modal(`<code>${esc(p)}</code>`, `<pre class="code">${esc(d.text || '(저장소에 없음)')}</pre>`, true);
}

// ───────────── 스킬 (저장소) ─────────────
const SCOPE_K = {me: '개인', team: '팀', dept: '부서'};
async function vSkills(sync) {
  const d = await (sync ? busy('스킬 저장소를 당겨 오는 중…', () => api('/api/skills?sync=1')) : api('/api/skills'));
  const r = d.repo;
  const chainHtml = s => `<span class="chain">${['전사'].concat(s.chain.map(l => l.id)).map((x, i, a) => `<span class="cn ${i === a.length - 1 ? 'me' : i === 0 ? 'corp' : ''}">${esc(x)}${i ? '' : ''}</span>`).join('<i>›</i>')}</span>`;
  $('#main').innerHTML = `<div class="page-h"><div><h2>스킬</h2><p>정본은 Git 저장소입니다. 이 PC는 저장소를 당겨 와서 <b>승인된 최신 버전</b>으로 문서를 만듭니다. 스킬 1개 = 폴더 1개 = <code>kosoe-skill.yaml</code> 1개.</p></div>
    <div class="row">${r.mode === 'github' ? `<a class="btn ghost" href="${esc(r.url)}" target="_blank">GitHub ↗</a>` : `<span class="chip o">${esc(r.mode)} ${esc(r.error || '')}</span>`}
    <button class="btn" onclick="vSkills(true)">⟳ 당겨오기 <span class="small muted" style="margin-left:6px">${esc((r.head || '').slice(0, 7))}</span></button></div></div>
  <h3 style="margin:0 0 10px;display:flex;gap:8px;align-items:center"><i class="chev"></i>전사 공용 스킬 <span class="chip">${d.corp.length}</span><span class="small muted">registry/corp.lock.yaml 에 커밋 단위로 고정 · 잠금: ${d.locked.map(esc).join(', ')}</span></h3>
  <div class="tgrid">${d.corp.map(c => `<div class="card tpl" style="cursor:default"><div class="row sp"><b>${esc(c.id)}</b><span class="chip ${c.cached ? 'ok' : 'o'}">${c.cached ? '받아 둠' : '아직'}</span></div>
     <div class="small muted">${esc(c.repo)}</div><div class="small"><code>${esc(c.short)}</code> 고정</div></div>`).join('')}</div>
  <h3 style="margin:26px 0 10px;display:flex;gap:8px;align-items:center"><i class="chev"></i>부서 · 개인 스킬 <span class="chip">${d.skills.length}</span></h3>
  <div class="card" style="overflow:hidden"><table class="list"><tr><th>스킬</th><th>상속</th><th>범위</th><th>양식</th><th>버전 태그</th><th>검사</th><th></th></tr>
   ${d.skills.map(s => `<tr class="click" onclick="openSkill('${s.id}')"><td><b>${esc(s.name)}</b><br><span class="small muted"><code>${esc(s.id)}</code> v${esc(s.version)}</span></td>
     <td class="small">${chainHtml(s)}</td><td><span class="chip o">${SCOPE_K[s.scope]}</span><br><span class="small muted">${esc(s.org || '')}${s.share === 'corp' ? ' · 전사 공개' : ''}</span></td>
     <td class="small">${s.forms.map(f => fmtTag(f.fmt) + ' ' + esc(f.name)).join('<br>') || '<span class="muted">(상위 공통 규칙)</span>'}</td>
     <td class="small">${s.tags.slice(0, 3).map(t => `<span class="chip n">${esc(t)}</span>`).join(' ')}</td>
     <td>${s.errors.length ? `<span class="chip bad" title="${esc(s.errors.join('\n'))}">오류 ${s.errors.length}</span>` : '<span class="chip ok">통과</span>'}${forcedChip(s.verification)}</td>
     <td><button class="btn sm ghost">보기</button></td></tr>`).join('')}</table></div>`;
}
// 검증 미통과 상태로 강제 등록한 스킬 표시(스킬 파일의 verification)
const forcedChip = v => v && v.status === 'forced' ? ` <span class="chip bad" title="${esc('미통과: ' + (v.failed || []).join(' / ') + '\n사유: ' + (v.reason || ''))}">검증 미통과 등록</span>` : '';
const forcedBox = v => v && v.status === 'forced' ? `<div class="out-f small" style="border-color:var(--bad);margin-bottom:10px">⚠️ <b>검증 미통과 상태로 강제 등록된 스킬</b> — ${esc(v.by || '')} · ${esc(v.date || v.t || '')}<br>미통과: ${(v.failed || []).map(esc).join(' / ')}<br>사유: ${esc(v.reason || '')}</div>` : '';
let SK = null;
async function openSkill(id) {
  const d = await api('/api/skills/' + encodeURIComponent(id)); SK = d.skill; const s = SK;
  const lv = s.chain;
  modal(`🧩 ${esc(s.name)} <span class="small muted">${esc(s.id)} v${esc(s.version)}</span>`, `
   ${forcedBox(s.verification)}${s.forms.filter(f => f.style).map(f => `<div class="small" style="margin-bottom:8px">✍️ <b>${esc(f.name)}</b> 문체(대표 문서에서 잼): ${esc(f.style)}</div>`).join('')}
   <div class="inh">${Object.entries(s.corp).map(([k, v]) => `<div class="lv corp"><b>전사</b> ${esc(k)} <code>${esc(v)}</code></div>`).join('')}
     ${lv.map((l, i) => `<div class="lv ${i === lv.length - 1 ? 'me' : ''}"><b>${({org: (l.org || '').includes('/') ? '팀' : '본부', user: '개인'})[l.scope] || ''}</b> ${esc(l.name)} <code>v${esc(l.version)}</code> <span class="small muted">${esc(l.path)}</span></div>`).join('')}</div>
   <div class="grid2" style="margin-top:12px"><div>
     <h4>고정 문구 (상속 합침)</h4>${s.resolved_blocks.map(b => `<div class="out-f"><span class="chip">${esc(b.heading || '-')}</span> ${esc(b.text)} <span class="small muted">← ${esc(b.from)}</span></div>`).join('') || '<p class="small muted">없음</p>'}
     <h4 style="margin-top:10px">작성 규칙 · 검수</h4><ul class="small">${s.rules.map(x => `<li>${esc(x)}</li>`).join('')}</ul>
     <div class="small">필수: ${s.checks.required.map(esc).join(' / ') || '-'}<br>금지: ${s.checks.banned.concat(s.glossary.banned).map(esc).join(', ') || '-'}<br>결재라인: ${s.approval_line.map(esc).join(' → ')}</div>
     <h4 style="margin-top:10px">파일</h4>${s.files.map(f => `<div><a href="#" class="small" onclick="showFile('${esc(f)}');return false"><code>${esc(f)}</code></a></div>`).join('')}
   </div><div>
     <h4>버전 · 복구</h4>${s.tags.map((t, i) => `<div class="row sp ev"><span class="chip n">${esc(t)}</span>${i && s.can_change ? `<button class="btn sm ghost" onclick="revertSkill('${esc(s.id)}','${esc(t)}')">이 버전으로 복구 요청</button>` : i ? '' : '<span class="small muted">현재</span>'}</div>`).join('') || '<p class="small muted">태그 없음</p>'}
     <h4 style="margin-top:10px">최근 변경</h4>${s.history.slice(0, 6).map(c => `<div class="ev"><span class="t"><code>${esc(c.sha)}</code></span><span class="grow small">${esc(c.msg)}<br><span class="muted">${esc(c.t)} · ${esc(c.who)}</span></span></div>`).join('')}
     ${s.can_change ? `<h4 style="margin-top:12px">이 팩 고치기 <span class="small muted">→ v${esc(bumpMinor(s.version))} 변경 요청(PR) → 승인 후 다음 문서부터</span></h4>
       <div id="skEd">${s.blocks.map((b, i) => `<div class="row" style="margin-bottom:6px"><input class="in" style="width:110px" value="${esc(b.heading || '')}" data-k="h" data-i="${i}"><textarea class="in" rows="2" data-k="t" data-i="${i}">${esc(b.text)}</textarea></div>`).join('')}</div>
       <label class="small">이 팩의 작성 규칙(한 줄에 하나)</label><textarea class="in" id="skRules" rows="3">${esc(s.own_rules.join('\n'))}</textarea>
       <input class="in" id="skNote" placeholder="변경 사유 (PR에 남습니다)" style="margin-top:6px">
       <button class="btn o" style="margin-top:8px" onclick="changeSkill('${esc(s.id)}')">📮 변경 요청 (브랜치 · PR)</button>` : ''}
   </div></div>`, true);
}
const bumpMinor = v => { const p = String(v).split('.').map(Number); return `${p[0]}.${p[1] + 1}.0`; };
async function showFile(p) { const d = await api('/api/skills-file?path=' + encodeURIComponent(p)); modal(`<code>${esc(p)}</code>`, `<pre class="code">${esc(d.text)}</pre>`, true); }
async function changeSkill(id) {
  const blocks = SK.blocks.map((b, i) => ({id: b.id, heading: $(`#skEd [data-k=h][data-i="${i}"]`).value, text: $(`#skEd [data-k=t][data-i="${i}"]`).value}));
  const rules = $('#skRules').value.split('\n').map(x => x.trim()).filter(Boolean);
  const d = await busy('변경 내용을 브랜치에 커밋하고 PR을 여는 중…', () => api(`/api/skills/${id}/change`, {body: {blocks, rules, note: $('#skNote').value}}));
  closeModal(); toast(d.request.pr_url ? `PR #${d.request.pr_number} — ${d.request.stage_name} 대기` : `변경 요청 — ${d.request.stage_name}`); await refreshMe(); go('approve');
}
async function revertSkill(id, tag) {
  if (!confirm(`${tag} 내용으로 되돌리는 복구 요청(PR)을 만들까요? 승인되면 다음 문서부터 그 내용으로 만듭니다.`)) return;
  const d = await busy('이전 버전 내용으로 복구 PR을 여는 중…', () => api(`/api/skills/${id}/revert`, {body: {tag}}));
  closeModal(); toast(`복구 요청 — ${d.request.stage_name}`); await refreshMe(); go('approve');
}

// ───────────── ★ 스킬 만들기 ─────────────
let SB = {files: [], request: '', scope: 'me', job: null, draft: null, analysis: null, report: null, thumbs: 0, req: null};
function sbStep() { return SB.req ? 5 : SB.report ? 4 : SB.draft ? 3 : SB.files.length ? 1 : 1; }
async function vRegister() {
  const d = await api('/api/requests');
  const mine = d.requests.filter(r => r.requester === ME.user.id);
  const st = sbStep();
  $('#main').innerHTML = `<div class="page-h"><div><h2>★ 대표 문서로 스킬 만들기</h2><p>초안이나 기존 문서를 올리고 한 줄로 요청하면, <b>전사 공용 스킬을 상속한 나의 스킬</b>이 만들어집니다. 검증을 통과하면 Git 저장소에 PR로 등록합니다(개인: 자동 검사 후 병합 · 팀/부서: 관리자 승인).</p></div>
    ${SB.draft || SB.files.length ? `<button class="btn ghost" onclick="SB={files:[],request:'',scope:'me',job:null,draft:null,analysis:null,report:null,thumbs:0,req:null};vRegister()">처음부터</button>` : ''}</div>
  <div class="pipe" style="margin-bottom:14px">${['① 첨부·요청', '② 분석', '③ 상속 기반 생성', '④ 충분한 검증', '⑤ 등록(PR)'].map((x, i) => `<span class="st ${i + 1 < st ? 'done' : i + 1 === st ? 'now' : ''}">${x}</span>`).join('')}</div>
  <div class="grid2">
   <div class="card box" id="sbIn"><h3><span class="chip dark">1</span> 대표 문서 · 요청</h3>
     <div class="drop" id="drop" onclick="pickFile(sbAdd,true)">초안·기존 문서 1건 이상 (부서 스킬은 3~5건 권장)<br><span class="small">hwp · hwpx · pptx · docx · html · pdf · txt — DRM 문서는 자동 차단 · 끌어 놓아도 됩니다</span></div>
     <button class="btn ghost sm" style="margin-top:8px" onclick="demoPick(us => { SB.files.push(...us); sbFiles(); }, n => n.startsWith('대표문서/'))">📂 시연 자료(대표 문서 3건)</button>
     <div id="sbf" style="margin-top:10px"></div>
     <input class="in" id="sbReq" style="margin-top:10px" placeholder='예) "영업팀 제안서 팩 만들어줘"' value="${esc(SB.request)}" oninput="SB.request=this.value">
     <div class="row" style="margin-top:8px"><span class="small">범위</span><select class="in" style="width:auto" onchange="SB.scope=this.value">${[['me', '나만 (개인 스킬 · 자동 등록)'], ['team', '우리 팀 (팀장 승인)'], ['dept', '우리 본부 (부서 관리자 승인)']].map(([k, v]) => `<option value="${k}" ${k === SB.scope ? 'selected' : ''}>${v}</option>`).join('')}</select>
     <button class="btn o" id="sbGo" onclick="sbAnalyze()" ${SB.files.filter(f => !f.drm).length ? '' : 'disabled'}>🔎 ② 분석</button></div>
     <div id="sbAna" style="margin-top:12px"></div></div>
   <div class="card box" id="sbDraft"><h3><span class="chip dark">3</span> 상속 기반 스킬 초안</h3><p class="muted small">분석하면 전사 공용 스킬(과 가장 가까운 상위 부서 스킬)을 상속한 스킬 폴더 초안이 여기에 나옵니다.</p></div>
  </div>
  <div class="card box" id="sbEval" style="margin-top:14px"><h3><span class="chip dark">4</span> 충분한 검증 <span class="small muted">— 모두 통과해야 등록 버튼이 열립니다</span></h3><p class="muted small">초안이 생기면 대표 문서에서 만든 검증 과제(메모 → 기대 구성·고정 문구·숫자)로 스킬 사용/미사용을 채점합니다.</p></div>
  <h3 style="margin:26px 0 10px;display:flex;gap:8px;align-items:center"><i class="chev"></i>이전 작업 이어서 하기 <span class="small muted">분석·검증을 미리 돌려 둔 작업</span></h3>
  <div id="sbJobs" class="row wrap"></div>
  <h3 style="margin:26px 0 10px;display:flex;gap:8px;align-items:center"><i class="chev"></i>내 등록·변경 요청</h3>
  ${mine.length ? mine.map(reqCard).join('') : '<div class="card empty small">아직 없습니다.</div>'}`;
  api('/api/skillgen/jobs').then(j => { const e = $('#sbJobs'); if (e) e.innerHTML = j.jobs.filter(x => x.stage !== 'submitted').map(x => `<button class="btn ghost sm" onclick="sbResume('${x.id}')">${esc(x.name || x.request || x.id)} · ${x.stage === 'evaluated' ? (x.auto_pass ? '검증 통과' : '검증 미통과') : '분석됨'} · ${esc(x.created)}</button>`).join('') || '<span class="small muted">없음</span>'; });
  // 끌어 놓기는 index.html의 document 위임(DROPS · #sbIn)이 맡는다 — 여기서 또 걸면 같은 파일이 두 번 올라간다
  sbFiles(); if (SB.analysis) sbAnaHtml(); if (SB.draft) sbDraftHtml(); if (SB.report) sbEvalHtml(); else if (SB.draft) sbEvalIntro();
}
async function sbResume(id) {
  const d = await api('/api/skillgen/' + id);
  SB = {files: d.job.files, request: '', scope: d.job.scope, job: d.job.id, draft: d.job.draft, analysis: d.job.analysis, report: d.job.report, thumbs: 0, req: null};
  vRegister(); toast('미리 돌려 둔 작업을 불러왔습니다');
}
async function sbAdd(f) { SB.files.push(await upload(f)); sbFiles(); }
function sbFiles() {
  $('#sbf').innerHTML = SB.files.map((u, i) => `<div class="out-f row"><span>${u.drm ? '🔐' : '📄'}</span><div class="grow"><b>${esc(u.name)}</b><br><span class="small ${u.drm ? '' : 'muted'}" style="${u.drm ? 'color:var(--bad)' : ''}">${u.drm ? 'DRM — 내용을 읽지 않았습니다' : `장 제목 ${u.heads.length}개: ${u.heads.slice(0, 6).map(esc).join(' · ')}`}</span></div><button class="x" onclick="SB.files.splice(${i},1);sbFiles()">✕</button></div>`).join('');
  const b = $('#sbGo'); if (b) b.disabled = !SB.files.filter(r => !r.drm).length;
}
async function sbAnalyze() {
  const d = await busy('대표 문서에서 공통 목차·고정 문구·용어를 뽑고 상속할 스킬을 찾는 중…', () => api('/api/skillgen/analyze', {body: {upload_ids: SB.files.filter(r => !r.drm).map(r => r.id), request: SB.request, scope: SB.scope}}));
  Object.assign(SB, {job: d.job.id, draft: d.job.draft, analysis: d.job.analysis, report: null, thumbs: 0, req: null});
  vRegister();
}
function sbAnaHtml() {
  const a = SB.analysis;
  $('#sbAna').innerHTML = `<h4><span class="chip dark">2</span> 분석 결과 <span class="small muted">${aiMeta(a.meta)}</span></h4>
   <div class="small">기반 전사 양식: <b>${a.base ? esc(a.base.name) + ` (${esc(a.base.id)}, 유사도 ${a.base.similarity})` : '-'}</b> · 상속할 상위 스킬: <b>${a.parent ? esc(a.parent.name) + ' v' + esc(a.parent.version) : '없음(전사 공용 스킬만)'}</b></div>
   ${a.style ? `<div class="small out-f" style="margin-top:6px">✍️ 문체: <b>${esc(a.style.label)}</b> ${a.style.default ? '<span class="chip">전사 보고 문법 그대로</span>' : '<span class="chip o">이 문서 기준</span>'}<br><span class="muted">${esc(a.style.basis || '')}${a.style.default ? '' : ' — 보고서가 아닌 문서로 보여, 전사 보고 문법 대신 이 문서의 문체로 쓰고 검증합니다.'}</span></div>` : ''}
   <div class="hl-legend small"><span class="hl fixed">고정 문구</span><span class="hl head">공통 목차</span><span class="hl var">바뀌는 칸(숫자·날짜)</span></div>
   ${a.highlights.map(h => `<details class="hl-doc"><summary>📄 ${esc(h.name)}</summary><div class="hl-body">${h.lines.map(l => `<div class="hl ${l.k}">${esc(l.t)}</div>`).join('')}</div></details>`).join('')}`;
}
function sbDraftHtml() {
  const D = SB.draft, f = D.forms[0];
  const lst = (arr, path, ph) => `<div class="lst-ed">${arr.map((x, i) => `<div class="li"><input class="in" value="${esc(x)}" placeholder="${ph}" oninput="${path}[${i}]=this.value;sbYaml()"><button class="x" onclick="${path}.splice(${i},1);sbDraftHtml()">✕</button></div>`).join('')}<button class="btn ghost sm" onclick="${path}.push('');sbDraftHtml()">+ 추가</button></div>`;
  $('#sbDraft').innerHTML = `<h3><span class="chip dark">3</span> 상속 기반 스킬 초안 <span class="small muted">${esc(D.id)} v${esc(D.version)}</span></h3>
   <div class="inh">${D.extends.map(e => `<div class="lv ${String(e).startsWith('corp:') ? 'corp' : ''}"><b>상속</b> ${esc(e)}</div>`).join('')}<div class="lv me"><b>새 스킬</b> ${esc(D.name)}</div></div>
   <div class="col" style="margin-top:10px"><label class="small">스킬 이름</label><input class="in" value="${esc(D.name)}" oninput="SB.draft.name=this.value;sbYaml()">
   <div class="grid3"><div><label class="small">양식 이름</label><input class="in" value="${esc(f.name)}" oninput="SB.draft.forms[0].name=this.value;sbYaml()"></div>
     <div><label class="small">형식</label><select class="in" onchange="SB.draft.forms[0].fmt=this.value;sbYaml()">${Object.entries(FMT).filter(([k]) => k !== 'xlsx').map(([k, v]) => `<option value="${k}" ${k === f.fmt ? 'selected' : ''}>${v}</option>`).join('')}</select></div>
     <div><label class="small">범위</label><input class="in" disabled value="${D.scope === 'user' ? '개인' : esc(D.org)}"></div></div>
   <label class="small">구성(장 제목, 순서대로)</label>${lst(f.outline, 'SB.draft.forms[0].outline', '장 제목')}
   <label class="small">고정 문구 (글자 그대로 들어감)</label><div class="lst-ed">${D.blocks.map((b, i) => `<div class="li"><input class="in" style="max-width:110px" value="${esc(b.heading)}" placeholder="장" oninput="SB.draft.blocks[${i}].heading=this.value;sbYaml()"><textarea class="in" rows="${Math.min(4, 1 + Math.floor(b.text.length / 70))}" oninput="SB.draft.blocks[${i}].text=this.value;sbYaml()">${esc(b.text)}</textarea><button class="x" onclick="SB.draft.blocks.splice(${i},1);SB.draft.forms[0].blocks=SB.draft.blocks.map(x=>x.id);sbDraftHtml()">✕</button></div>`).join('')}
     <button class="btn ghost sm" onclick="const n='b'+(SB.draft.blocks.length+1);SB.draft.blocks.push({id:n,heading:'',text:''});SB.draft.forms[0].blocks.push(n);sbDraftHtml()">+ 추가</button></div>
   <label class="small">작성 규칙</label>${lst(D.rules, 'SB.draft.rules', '예) 결론을 먼저 쓴다')}
   <label class="small">금지어 (쉼표로)</label><input class="in" value="${esc((D.checks.banned || []).join(', '))}" oninput="SB.draft.checks.banned=this.value.split(',').map(x=>x.trim()).filter(Boolean);sbYaml()">
   <details><summary class="small">📁 만들어질 스킬 폴더 미리보기</summary><div class="small muted" style="margin:6px 0"><code>${D.scope === 'user' ? `skills/user/${esc(D.owner)}/${esc(D.id)}/` : `skills/org/${esc(D.org)}/${esc(D.id)}/`}</code> — kosoe-skill.yaml · SKILL.md · evals/case-N/(prompt.md · case.yaml)</div><pre class="code" id="sbY"></pre></details>
   </div>`;
  sbYaml();
}
function yamlOf(o, ind = '') {
  if (Array.isArray(o)) return o.length ? o.map(x => (typeof x === 'object' && x !== null) ? `${ind}- ${yamlOf(x, ind + '  ').trimStart()}` : `${ind}- ${x}`).join('\n') : `${ind}[]`;
  if (typeof o === 'object' && o !== null) return Object.entries(o).map(([k, v]) => (typeof v === 'object' && v !== null) ? (Array.isArray(v) && !v.length ? `${ind}${k}: []` : Object.keys(v).length ? `${ind}${k}:\n${yamlOf(v, ind + '  ')}` : `${ind}${k}: {}`) : `${ind}${k}: ${v}`).join('\n');
  return ind + String(o);
}
function sbYaml() { const e = $('#sbY'); if (e) e.textContent = yamlOf(SB.draft); }
function sbEvalIntro() {
  $('#sbEval').innerHTML = `<h3><span class="chip dark">4</span> 충분한 검증 <span class="small muted">— 모두 통과해야 등록 버튼이 열립니다</span></h3>
   <p class="small muted">대표 문서마다 과제(메모 → 기대 구성·고정 문구·숫자)를 만들어 <b>이 스킬을 쓸 때</b>와 <b>안 쓸 때</b> 초안을 각각 만들고 7개 기준으로 채점합니다. 대표 문서 ${SB.files.filter(f => !f.drm).length}건 × 2회 AI 호출.</p>
   <button class="btn o" onclick="sbEvaluate()">🧪 ④ 검증 실행</button>`;
}
async function sbEvaluate() {
  const d = await busy('검증 과제를 스킬 사용/미사용으로 채점하는 중… (AI 여러 번 호출)', () => api(`/api/skillgen/${SB.job}/evaluate`, {body: {draft: SB.draft}}));
  SB.report = d.report; SB.draft = d.draft; if (d.analysis) SB.analysis = d.analysis; SB.thumbs = 0; vRegister();
}
function sbEvalHtml() {
  const R = SB.report, need = R.criteria.find(c => c.id === 'human').human;
  const humanOk = SB.thumbs >= need, all = R.auto_pass && humanOk;
  $('#sbEval').innerHTML = `<h3><span class="chip dark">4</span> 검증 리포트 <span class="chip ${R.auto_pass ? 'ok' : 'bad'}">${R.auto_pass ? '자동 기준 통과' : '자동 기준 미통과'}</span></h3>
   <div class="grid2"><div>${R.criteria.map(c => {
      const pass = c.id === 'human' ? humanOk : c.pass;
      return `<div class="check"><span class="i ${pass ? 'ok' : 'no'}">${pass ? '✓' : '!'}</span><span class="grow"><b>${esc(c.name)}</b>${c.detail ? `<br><span class="small muted">${esc(c.id === 'human' ? `${SB.thumbs}/${need}건 확인` : c.detail)}</span>` : ''}</span></div>`;
    }).join('')}
    ${R.errors.length ? `<div class="small" style="color:var(--bad);margin-top:6px">${R.errors.map(esc).join('<br>')}</div>` : ''}</div>
   <div><div class="kpis" style="grid-template-columns:1fr 1fr;margin:0"><div class="card kpi"><div class="l">스킬 사용</div><div class="v">${R.with_score}<small>/${R.full}</small></div></div><div class="card kpi"><div class="l">스킬 미사용</div><div class="v">${R.without_score}<small>/${R.full}</small></div></div></div>
    ${R.tasks.map((t, i) => `<details class="hl-doc"><summary class="small">과제 ${i + 1} · ${esc(t.doc)} · 구성 ${(t.with.struct * 100).toFixed(0)}% vs ${(t.without.struct * 100).toFixed(0)}% · ${t.mode === 'llm' ? 'AI' : '규칙'}</summary><pre class="code small">${esc(t.memo)}</pre></details>`).join('')}
    <div style="margin-top:10px"><b class="small">사람 확인 — 담당자 시범 작성 ${need}건</b><div class="row wrap" style="margin-top:6px">${Array.from({length: need}, (_, i) => `<button class="btn sm ${i < SB.thumbs ? '' : 'ghost'}" onclick="SB.thumbs=${i + 1};sbEvalHtml()">${i < SB.thumbs ? '👍' : '○'} 시범 ${i + 1}</button>`).join('')}</div></div></div></div>
   <div class="row wrap" style="margin-top:12px"><button class="btn ghost" onclick="sbEvaluate()">↻ 다시 검증</button>
     <button class="btn o" ${all && R.upload?.writable !== false ? '' : 'disabled'} onclick="sbSubmit()">📮 ⑤ 등록 요청 (브랜치 · PR${SB.draft.scope === 'user' ? ' · 자동 검사 후 병합' : ' · 관리자 승인'})</button>
     ${all ? '' : `<span class="small muted">모든 기준을 통과해야 열립니다</span>
       <button class="btn red" ${R.can_force === false || R.upload?.writable === false ? 'disabled' : ''} onclick="sbForce()" title="미통과 항목과 사유를 PR·스킬 파일에 남기고 등록합니다">⚠️ 미통과 항목이 있어도 등록</button>
       ${R.can_force === false ? '<span class="small" style="color:var(--bad)">스킬 파일 검사 오류·보안(개인정보) 미통과는 강제 등록할 수 없습니다</span>' : ''}`}</div>
   ${sbUploadNote(R.upload)}`;
}
// 등록하면 저장소에 무엇이 올라가는지(공개 저장소인지, 스킬 글에 회사 이름으로 보이는 글이 있는지) 미리 알려 준다
function sbUploadNote(u) {
  if (!u) return '';
  const pub = u.visibility === 'public';
  return `<div class="out-f small" style="margin-top:10px;${pub ? 'border-color:var(--o)' : ''}">
    <b>등록하면 올라가는 곳</b> <code>${esc(u.repo)}</code> ${pub ? '<span class="chip o">공개 저장소 — 누구나 볼 수 있음</span>' : u.visibility ? '<span class="chip">비공개 저장소</span>' : ''}<br>
    올라가는 것: ${u.files.map(esc).join(' · ')}<br>
    <b>올라가지 않는 것</b>: ${esc(u.not_uploaded)} — 이 PC에만 남습니다.
    ${u.writable === false ? `<br><span style="color:var(--bad)">⛔ 이 PC의 GitHub 계정은 <code>${esc(u.repo)}</code>에 쓸 권한이 없어 등록할 수 없습니다 — 저장소 관리자에게 Write 권한을 요청하거나 .env의 KOSOE_SKILLS_REPO를 쓸 수 있는 저장소로 바꿔 주세요.</span>` : ''}
    ${u.names.length ? `<br><span style="color:var(--bad)">스킬 글에 회사 이름으로 보이는 글이 있습니다: <b>${u.names.map(esc).join(', ')}</b></span> — 실제 고객사라면 위 ③에서 <code>[고객사명]</code> 같은 칸으로 바꾼 뒤 다시 검증하세요.` : ''}
    ${pub ? '<br><span class="muted">고정 문구와 작성 규칙은 스킬의 내용이라 그대로 올라갑니다. 실제 문서의 문장이 들어 있지 않은지 ③에서 확인하세요.</span>' : ''}</div>`;
}
// 검증 미통과 강제 등록: 미통과 항목을 보여 주고 사유를 받아, PR 본문 · 스킬 파일(verification) · SKILL.md에 남긴다
function sbForce() {
  const R = SB.report, need = R.criteria.find(c => c.id === 'human').human;
  const failed = R.criteria.filter(c => c.id === 'human' ? SB.thumbs < need : !c.pass);
  modal('⚠️ 검증 미통과 상태로 등록', `
    <p class="small">아래 기준을 통과하지 못했습니다. 그래도 등록하면 <b>미통과 항목과 사유가 PR · 스킬 파일 · SKILL.md에 남고</b>, 스킬 목록에 「검증 미통과 등록」으로 표시됩니다.${SB.draft.scope === 'user' ? ' 개인 스킬이라 자동 검사(스키마 · 상속 · 잠금 · 보안)만 통과하면 바로 병합됩니다.' : ' 승인권자가 이 내용을 보고 승인 여부를 정합니다.'}</p>
    ${failed.map(c => `<div class="check"><span class="i no">!</span><span class="grow"><b>${esc(c.name)}</b>${c.detail && c.id !== 'human' ? `<br><span class="small muted">${esc(c.detail)}</span>` : ''}</span></div>`).join('')}
    <label class="small" style="display:block;margin-top:10px">강제 등록 사유 (5자 이상, 개인정보는 적지 마세요)</label>
    <textarea class="in" id="sbWhy" rows="2" placeholder="예) 계약서 양식이라 보고 문법 기준이 맞지 않음. 구성과 고정 조항 재현은 확인함"></textarea>
    <div class="row" style="margin-top:10px"><button class="btn red" onclick="sbSubmit(true)">미통과 상태로 등록 요청</button><button class="btn ghost" onclick="closeModal()">취소</button></div>`);
}
async function sbSubmit(force) {
  const body = {thumbs: SB.thumbs};
  if (force) {
    body.force = true; body.reason = ($('#sbWhy')?.value || '').trim();
    if (body.reason.length < 5) return toast('강제 등록 사유를 5자 이상 적어 주세요', true);
    closeModal();
  }
  const d = await busy('스킬 폴더를 브랜치에 커밋하고 PR을 여는 중…', () => api(`/api/skillgen/${SB.job}/submit`, {body}));
  SB.req = d.request;
  toast(d.request.stage === 'done' ? (force ? '⚠️ 검증 미통과 상태로 개인 스킬을 등록했습니다 — 저장소에 병합·태그' : '🎉 개인 스킬 등록 완료 — 저장소에 병합·태그, 바로 쓸 수 있습니다') : `PR #${d.request.pr_number} — ${d.request.stage_name} 대기`);
  SB = {files: [], request: '', scope: 'me', job: null, draft: null, analysis: null, report: null, thumbs: 0, req: null};
  await refreshMe(); vRegister();
}
function pipe(r) {
  const names = {ci: '자동 검사', lead: '팀장', dept: '부서', corp: '전사'};
  const idx = r.stages.indexOf(r.stage);
  return `<div class="pipe"><span class="st done">요청</span>${r.stages.map((s, i) => `<span class="st ${r.stage === 'done' || i < idx ? 'done' : r.stage === 'rejected' ? (i === 0 ? 'rej' : '') : i === idx ? 'now' : ''}">${names[s]}</span>`).join('')}<span class="st ${r.stage === 'done' ? 'done' : r.stage === 'rejected' ? 'rej' : ''}">${r.stage === 'rejected' ? '반려' : '병합 · 태그'}</span></div>`;
}
function reqCard(r) {
  return `<div class="card box" style="margin-bottom:10px"><div class="row sp wrap"><div><span class="chip dark">${esc(r.kind_name)}</span> <b style="font-size:15px">${esc(r.name)}</b> <span class="chip n">v${esc(r.note.version || '')}</span> <span class="chip o">${SCOPE[r.scope]}</span> <span class="small muted">${esc(r.requester_name)} · ${esc(r.created)}</span></div>
    <div class="row">${r.pr_url ? `<a class="btn ghost sm" href="${esc(r.pr_url)}" target="_blank">GitHub PR #${r.pr_number} ↗</a>` : `<span class="chip">🌿 ${esc(r.branch)}</span>`}</div></div>
    ${pipe(r)}${forcedBox(r.note.report && r.note.report.forced ? {status: 'forced', ...r.note.report.forced} : null)}<div class="small muted">양식: ${r.outline.map(esc).join(' · ') || '-'} · 경로 <code>${esc(r.path)}/</code></div>
    <div style="margin-top:8px">${r.history.map(h => `<div class="ev"><span class="t">${esc(h.t)}</span><span class="grow"><b>${esc(h.who)}</b> ${esc(h.act)}${h.note ? ` — “${esc(h.note)}”` : ''}</span></div>`).join('')}</div>
    ${r.can_decide ? `<div class="row" style="margin-top:10px"><input class="in" id="n-${r.id}" placeholder="의견 (PR 댓글로 남습니다)"><button class="btn" onclick="decide('${r.id}',true)">승인 → 병합·태그</button><button class="btn red" onclick="decide('${r.id}',false)">반려</button></div>` : ''}</div>`;
}
async function decide(id, approve) {
  const note = $('#n-' + id)?.value || '';
  if (!approve && !note) return toast('반려 사유를 적어 주세요', true);
  const d = await busy(approve ? '승인 기록 → PR 병합 → 버전 태그…' : '반려 처리 중…', () => api(`/api/requests/${id}/decide`, {body: {approve, note}}));
  toast(d.request.stage === 'done' ? '🎉 승인 — 저장소에 병합하고 태그를 붙였습니다. 다음 문서부터 반영됩니다' : approve ? `승인 — 다음: ${d.request.stage_name}` : '반려했습니다');
  await refreshMe(); vApprove();
}

// ───────────── 검수 (사람이 쓴 문서 · 원본값 대조 · 재검사) ─────────────
let IN = {src: [], tgt: [], doc: '', tpl: '', text: '', last: null, prev: null};
async function vInspect() {
  const [dd, tt] = await Promise.all([api('/api/docs'), TPLS.length ? Promise.resolve({templates: TPLS}) : api('/api/templates')]);
  TPLS = tt.templates;
  $('#main').innerHTML = `<div class="page-h"><div><h2>검수</h2><p>원본 자료(메모·엑셀)와 결과 파일의 <b>값을 대조</b>해 수정 누락을 찾고, 보고 문법·팩 규칙을 함께 봅니다. 사람이 고친 파일을 올려도 됩니다. 고친 뒤 다시 올리면 <b>재검사</b>합니다.</p></div></div>
  <div class="grid2"><div class="card box"><h3><span class="chip dark">1</span> 원본 자료</h3>
     <textarea class="in" rows="5" id="inTxt" placeholder="원본 메모를 붙여 넣거나 파일을 첨부하세요" oninput="IN.text=this.value">${esc(IN.text)}</textarea>
     <div class="row wrap" id="inSrc" style="margin-top:6px"><button class="btn ghost sm" onclick="pickFile(async f=>{IN.src.push(await upload(f));vInspect()},true)">📎 원본 파일</button><button class="btn ghost sm" onclick="demoPick(us=>{IN.src.push(...us);vInspect()}, n => n.endsWith('.txt'))">📂 시연 메모</button>${IN.src.map((f, i) => `<span class="chip">${esc(f.name)} <a href="#" onclick="IN.src.splice(${i},1);vInspect();return false">✕</a></span>`).join('')}</div>
     <label class="small" style="margin-top:10px;display:block">또는 내 문서(원본 자료 + 최신 결과 파일을 함께 검사)</label>
     <select class="in" onchange="IN.doc=this.value"><option value="">— 고르지 않음 —</option>${dd.docs.map(x => `<option value="${x.id}" ${x.id === IN.doc ? 'selected' : ''}>${esc(x.title)} v${x.ver}</option>`).join('')}</select></div>
   <div class="card box"><h3><span class="chip dark">2</span> 검사할 파일 <span class="small muted">사람이 고친 PPT·한글 등</span></h3>
     <div class="drop" id="inTgt" onclick="pickFile(async f=>{IN.tgt.push(await upload(f));vInspect()},true)">파일 올리기 (pptx · hwp · hwpx · html · docx · pdf) · 끌어 놓아도 됩니다</div>
     <button class="btn ghost sm" style="margin-top:6px" onclick="demoPick(us=>{IN.tgt.push(...us);vInspect()}, n => n.startsWith('검수시연'))">📂 시연 자료(사람이 고친 PPT)</button>
     <div style="margin-top:8px">${IN.tgt.map((f, i) => `<div class="out-f row"><span>${f.drm ? '🔐' : '📄'}</span><b class="grow">${esc(f.name)}</b><button class="x" onclick="IN.tgt.splice(${i},1);vInspect()">✕</button></div>`).join('')}</div>
     <label class="small" style="margin-top:10px;display:block">팩 규칙도 함께(선택)</label>
     <select class="in" onchange="IN.tpl=this.value"><option value="">— 보고 문법만 —</option>${TPLS.filter(t => t.skill_info?.id).map(t => `<option value="${t.id}" ${t.id === IN.tpl ? 'selected' : ''}>${esc(t.name)} · ${esc(t.skill_info.id)}</option>`).join('')}</select>
     <button class="btn o" style="margin-top:12px" onclick="runInspect()">🔍 검사${IN.last ? ' (재검사)' : ''}</button></div></div>
  <div id="inRes" style="margin-top:14px"></div>`;
  if (IN.last) inResHtml();
}
async function runInspect() {
  const d = await busy('원본과 결과 파일의 값을 대조하는 중…', () => api('/api/inspect', {body: {source_text: IN.text, source_ids: IN.src.map(f => f.id), target_ids: IN.tgt.map(f => f.id), doc_id: IN.doc, template_id: IN.tpl}}));
  IN.prev = IN.last; IN.last = d; inResHtml();
}
function inResHtml() {
  const r = IN.last.result, p = IN.prev?.result;
  const K = {mismatch: ['불일치', 'bad'], missing: ['원본 값 없음(참고)', ''], unknown: ['판정 불가', 'o']};
  $('#inRes').innerHTML = `<div class="card box"><h3>결과 ${p ? `<span class="small muted">재검사 — 이전 불일치 ${p.mismatch} → 지금 ${r.mismatch}</span>` : ''}</h3>
   <div class="row wrap" style="margin-bottom:8px"><span class="chip">대조한 원본 값 ${r.checked}</span><span class="chip ${r.mismatch ? 'bad' : 'ok'}">불일치 ${r.mismatch}</span><span class="chip">빠진 값 ${r.missing}</span><span class="chip ${r.unknown ? 'o' : ''}">판정 불가 ${r.unknown}</span>
     ${!r.mismatch && !r.unknown ? '<span class="chip ok">✓ 값 대조 통과</span>' : ''}</div>
   <table class="list"><tr><th>파일</th><th>결과</th><th>항목</th><th>원본</th><th>파일 값</th><th>내용</th></tr>
   ${r.items.sort((a, b) => (a.kind === 'mismatch' ? 0 : 1) - (b.kind === 'mismatch' ? 0 : 1)).map(i => `<tr><td class="small">${esc(i.target)}</td><td><span class="chip ${K[i.kind][1]}">${K[i.kind][0]}</span></td><td>${esc(i.key || '')}</td><td>${esc(i.want || '')}</td><td><b>${esc(i.got || '')}</b></td><td class="small muted">${esc(i.ctx || i.detail)}</td></tr>`).join('') || '<tr><td colspan="6" class="small muted">차이 없음</td></tr>'}</table>
   ${IN.last.rules.map(x => `<div style="margin-top:10px"><b class="small">${esc(x.target)} — 보고 문법·팩 규칙</b>${x.checks.map(c => `<div class="check"><span class="i ${c.ok ? 'ok' : 'no'}">${c.ok ? '✓' : '!'}</span><span class="grow">${esc(c.name)}${c.ok ? '' : `<br><span class="small muted">${esc(c.detail)}</span>`}</span></div>`).join('')}</div>`).join('')}
   <p class="small muted" style="margin-top:8px">파일을 고쳐 저장한 뒤 [2]에서 지우고 다시 올려 <b>재검사</b>하세요. 화면 배치(넘침·겹침)는 파일을 열어 확인해야 하며, 이 검사는 파일에서 읽은 값만 봅니다.</p></div>`;
}

// ───────────── 시연 도우미 ─────────────
async function demoPick(onPick, filter) {
  const d = await api('/api/demo/files');
  if (!d.ready) {
    if (!confirm('시연용 가상 자료가 아직 없습니다. 지금 만들까요? (한글·PPT 몇 건, 20초 안팎)')) return;
    await busy('시연용 가상 자료를 만드는 중…', () => api('/api/demo/seed', {body: {}}));
    return demoPick(onPick, filter);
  }
  const fs = d.files.filter(f => !filter || filter(f.name));
  modal('📂 시연 자료 고르기 <span class="small muted">seed/out — 모두 가상</span>', `
    ${fs.map((f, i) => `<label class="out-f row" style="cursor:pointer"><input type="checkbox" value="${esc(f.name)}" ${filter && !f.name.includes('수정본') ? 'checked' : ''}><span class="grow">${esc(f.name)}</span><span class="small muted">${kb(f.size)}</span></label>`).join('')}
    <div class="row" style="margin-top:10px"><button class="btn o" id="dpGo">첨부</button><button class="btn ghost" onclick="demoMake()">자료 다시 만들기</button></div>`);
  $('#dpGo').onclick = async () => {
    const names = [...document.querySelectorAll('#mb input:checked')].map(i => i.value);
    if (!names.length) return toast('파일을 골라 주세요', true);
    const r = await busy('시연 자료를 읽는 중…', () => api('/api/demo/attach', {body: {names}}));
    closeModal(); onPick(r.uploads);
  };
}
async function demoMake() { await busy('시연용 가상 자료를 만드는 중…', () => api('/api/demo/seed', {body: {}})); closeModal(); toast('시연 자료를 다시 만들었습니다'); }

const SCENES = [
  ['0:00', '입력과 문제', 'u1', 'new', '홈에서 「📂 시연 자료」로 고객 세미나 메모를 붙이고 무엇을 만들지 한 줄로 적는다. 상단 띠: 지금 AI(구독 CLI)·지금 망'],
  ['0:20', '한글 제작', 'u1', 'new', '「기획 요약보고(경영기획팀 기준)」 → 초안 → 한글만 생성 → 미리보기로 □ㅇ- 단계 확인, 받아서 한컴 뷰어로 열기'],
  ['0:50', 'PPT·웹 제작', 'u1', 'new', '같은 메모로 「영업1팀 고객 제안서」 → PPT·웹 동시 생성 → PPT 미리보기·웹슬라이드 미리보기(회사 소개·서비스 제안 고정 문구)'],
  ['1:20', '팩 변경 반영', 'u2', 'skills', '김철수 팀장: 스킬 → 영업 팩 → 서비스 제안 문구 고치기 → 변경 요청(PR) → 승인함에서 승인(병합·태그) → 홍길동 문서 「검수 자동 수정」으로 새 문구 반영 → 이전 버전 복구 요청'],
  ['1:50', '검수·재검사', 'u1', 'inspect', '원본 메모 + 「사람이 고친 PPT(예산 오류)」 → 불일치 120만원≠100만원 → 수정본으로 바꿔 재검사 → 0건'],
  ['2:15', '★ 팩 스킬 생성', 'u1', 'register', '대표 문서 3건 + "영업팀 제안서 팩 만들어줘" → 분석(하이라이트·상속 사슬) → 검증(사용/미사용) → 👍 → 등록(PR·자동 검사·병합) → 새 문서 화면에 내 양식'],
  ['2:40', '운영 검증', 'u4', 'skills', '스킬 화면: 전사 공용 스킬 4종이 커밋으로 고정, 잠금 항목. 상단 띠: 본선=구독 CLI, 사내 GPU·Bedrock은 설정 한 줄(승인된 환경에서 검증)'],
  ['2:50', '마무리', 'u1', 'docs', '문서함: 세 형식 파일·버전·스킬 버전·검수 내역 → 대시보드'],
];
let DEMO_T = null;
async function vDemo() {
  $('#main').innerHTML = `<div class="page-h"><div><h2>시연 3분 (기획서 19장)</h2><p>장면 버튼을 누르면 그 장면의 사용자로 바꾸고 화면을 엽니다. 시간은 위 초시계로 잽니다.</p></div>
    <div class="row"><span class="chip dark" id="dmT">0:00</span><button class="btn" onclick="demoTimer()">${DEMO_T ? '■ 멈춤' : '▶ 시작'}</button>
    <button class="btn" onclick="demoWarm()">🔥 예열</button><button class="btn red" onclick="demoReset()">⟲ 시연 초기화</button></div></div>
  <div class="card" style="overflow:hidden"><table class="list"><tr><th>시각</th><th>장면</th><th>누가</th><th>할 일</th><th></th></tr>
  ${SCENES.map(([t, n, u, v, w], i) => `<tr><td><b>${t}</b></td><td><b>${esc(n)}</b></td><td class="small">${esc(({u1: '홍길동 대리', u2: '김철수 팀장', u4: '박지원 부장'})[u])}</td><td class="small">${esc(w)}</td>
    <td><button class="btn sm o" onclick="demoGo('${u}','${v}')">열기</button></td></tr>`).join('')}</table></div>
  <p class="small muted" style="margin-top:10px">초기화는 이 PC의 문서·첨부·요청·로그를 비우고 스킬 저장소의 열린 PR을 닫습니다. 병합된 스킬 이력·태그는 남습니다.</p>`;
}
async function demoGo(uid, view) { if (ME.user.id !== uid) { await api('/api/login', {body: {uid}}); ME = await api('/api/me'); renderTop(); } go(view); }
function demoTimer() {
  if (DEMO_T) { clearInterval(DEMO_T.iv); DEMO_T = null; return vDemo(); }
  const t0 = Date.now(); DEMO_T = {iv: setInterval(() => { const s = Math.round((Date.now() - t0) / 1000), e = document.getElementById('dmT'); if (e) e.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }, 500)};
  vDemo();
}
async function demoWarm() {
  const d = await busy('엔진 3종과 AI를 한 번씩 돌려 예열하는 중…', () => api('/api/demo/warm?ai=1', {body: {}}));
  toast(`예열 완료 — 한글 ${d.sec.hwp}초 · PPT ${d.sec.ppt}초 · 웹 ${d.sec.web}초` + (d.ai.ok ? ` · AI ${(d.ai.ms / 1000).toFixed(1)}초` : ''));
}
async function demoReset() {
  if (!confirm('시연을 초기화할까요? 이 PC의 문서·첨부·요청·로그를 비우고 열린 PR을 닫습니다.')) return;
  const us = confirm('시연 중 만든 개인 스킬(skills/user/*)도 저장소에서 정리할까요? (새 커밋으로 지움, 이력·태그는 남음)');
  await busy('시연 초기화 중… (열린 PR 닫기 포함)', () => api('/api/demo/reset', {body: {user_skills: us}}));
  ATT = []; SB = {files: [], request: '', scope: 'me', job: null, draft: null, analysis: null, report: null, thumbs: 0, req: null}; IN = {src: [], tgt: [], doc: '', tpl: '', text: '', last: null, prev: null};
  toast('초기화했습니다'); VIEW = 'demo'; showLogin();
}
