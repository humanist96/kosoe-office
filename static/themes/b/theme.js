// 코쇠오피스 화면 테마 B — 기본 index.html 의 함수 중 이 테마가 바꾼 것만 덮어쓴다.
// 기본 화면 스크립트 다음, boot() 전에 한 번 실린다(index.html 의 테마 로더).

function renderTop() {
  const u = ME.user, inet = ME.inet;
  $('#top').innerHTML = `
   <div class="logo"><img src="/static/kosoe.webp" alt=""><span>코쇠오피스</span></div>
   <div class="net" title="인터넷망은 팀장 승인 기간에만">
     <button class="${ME.net === 'closed' ? 'on' : ''}" onclick="setNet('closed')"><svg class="top-ic" viewBox="0 0 24 24"><rect x="5" y="10" width="14" height="10" rx="1"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>폐쇄망</button>
     <button class="${ME.net === 'internet' ? 'on i' : ''}" onclick="setNet('internet')"><svg class="top-ic" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4c2.3 2.2 3.4 4.9 3.4 8S14.3 17.8 12 20M12 4C9.7 6.2 8.6 8.9 8.6 12s1.1 5.8 3.4 8"/></svg>인터넷망${inet ? '' : ' · 승인 필요'}</button>
   </div>
   <span class="small muted">${inet ? `인터넷 승인 ~${inet.until}` : '인터넷망: 승인 필요'}</span>
   <span class="grow"></span>
   <button class="chip ${ME.ai.connected ? 'n' : 'o'}" style="cursor:pointer" onclick="aiModal()" title="눌러서 AI 바꾸기 (Claude Code CLI ↔ NVIDIA API · OpenRouter)">${aiChipText()} ▾</button>
   <span class="chip" title="스킬 저장소 ${esc(ME.repo.url || '')} ${esc(ME.repo.error || '')}" onclick="go('skills')" style="cursor:pointer"><svg class="top-ic" viewBox="0 0 24 24"><path d="M8 4h8l3 3v10l-3 3H8l-3-3V7z"/><path d="M9 12h6M12 9v6"/></svg>${ME.repo.mode === 'github' ? '스킬 저장소 ' + esc(ME.repo.head) : ME.repo.mode === 'local' ? '로컬 스킬 저장소' : '스킬 저장소'}</span>
   <button class="row" onclick="logout()" title="사용자 바꾸기"><span class="av" style="width:32px;height:32px;background:${u.color};font-size:13px">${esc(u.name[0])}</span>
     <span style="text-align:left;line-height:1.25"><b>${esc(u.name)} ${esc(u.title)}</b><br><span class="small muted">${esc(u.team)} · ${esc(u.role_name)}</span></span></button>`;
}

const NAV_ICONS = {
  new:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h11l5 5v11H4z"/><path d="M15 4v5h5M8 14h8M12 10v8"/></svg>',
  docs:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3h10l4 4v14H5z"/><path d="M15 3v5h4M8 12h8M8 16h6"/></svg>',
  templates:'<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16"/><path d="M8 9h8M8 13h8M8 17h5"/></svg>',
  skills:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 4h8l3 3v10l-3 3H8l-3-3V7z"/><path d="M9 12h6M12 9v6"/></svg>',
  register:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 19h14M7 16l9-9 2 2-9 9-3 1z"/></svg>',
  inspect:'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="5.5"/><path d="m15 15 4 4M8 10.5l1.6 1.6 3-3"/></svg>',
  approve:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h14v16H5z"/><path d="m8 12 2.3 2.3L16 8.7"/></svg>',
  inet:'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4c2.3 2.2 3.4 4.9 3.4 8S14.3 17.8 12 20M12 4C9.7 6.2 8.6 8.9 8.6 12s1.1 5.8 3.4 8"/></svg>',
  dash:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 19V9M12 19V5M19 19v-7"/></svg>',
  audit:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h12v16H6z"/><path d="M9 9h6M9 13h6M9 17h4"/></svg>',
  demo:'<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="14"/><path d="m10 9 5 3-5 3z"/></svg>'
};

const navIcon = k => NAV_ICONS[k] || NAV_ICONS.docs;

function renderSide() {
  const r = ME.user.role;
  const show = k => k === 'audit' ? ['security', 'corpAdmin'].includes(r) : k === 'dash' ? r !== 'user' : true;
  $('#side').innerHTML = NAV.filter(n => show(n[0])).map(([k, ic, t]) =>
    `<a href="#" class="${VIEW === k || (VIEW === 'ws' && k === 'new') ? 'on' : ''}" onclick="go('${k}');return false"><span class="ic">${navIcon(k)}</span>${t}${k === 'approve' && ME.pending ? `<span class="badge">${ME.pending}</span>` : ''}</a>`).join('')
    + `<div class="grow"></div><div class="sec">이 PC에서만 · localhost</div><div class="small muted" style="padding:0 12px">가상 조직 · 가상 데이터</div>`;
}

async function vNew() {
  const d = await api('/api/templates'); TPLS = d.templates;
  const mine = TPLS.filter(t => t.scope !== 'corp'), corp = TPLS.filter(t => t.scope === 'corp');
  $('#main').innerHTML = `
  <div class="page-h"><div><h2>무엇을 만들까요?</h2><p>하고 싶은 말을 적고 자료를 붙이면, 맞는 양식(스킬)을 골라 초안을 만듭니다.</p></div>
    <span class="chip ${ME.net === 'internet' ? 'o' : 'n'}">${ME.net === 'internet' ? '🌐 인터넷망 — 대외비 템플릿 제외 · 마스킹 적용' : '🔒 폐쇄망 — 모든 등급 사용 가능'}</span></div>
  <div class="new-banner"><i class="ride" aria-hidden="true"><i class="k"></i></i><strong>정확한 문서, 일관된 기준으로.</strong><span>코스콤의 문서 기준과 업무 맥락을 반영해 초안을 구성합니다.</span></div>
  <div class="ask">
    <textarea id="req" placeholder="예) 3분기 금융영업1팀 실적 결과 보고서 만들어줘. 첨부한 엑셀 숫자를 성과 표에 넣고, 향후 계획은 B증권 제안 중심으로."></textarea>
    <div class="row sp wrap" style="margin-top:8px">
      <div class="row wrap"><button class="btn ghost sm" onclick="pickFile(f => addAtt(f))">📎 자료 첨부</button><button class="btn ghost sm" onclick="demoPick(us => { ATT.push(...us); renderAtt(); })">📂 시연 자료</button><div class="files" id="att"></div></div>
      <div class="row"><button class="btn ghost" onclick="recommend()">🧭 양식 추천</button><button class="btn o" id="go" onclick="startCompose()" disabled>초안 만들기 →</button></div>
    </div>
  </div>
  <div id="rec"></div>
  <h3 style="margin:26px 0 10px;display:flex;gap:8px;align-items:center"><i class="chev"></i>우리 팀·부서·나의 스킬 양식 <span class="chip">${mine.length}</span></h3>
  <div class="tgrid">${mine.map(tplCard).join('') || '<div class="muted small">아직 없습니다. [★ 스킬 만들기]에서 대표 문서로 만들어 보세요.</div>'}</div>
  <h3 style="margin:26px 0 10px;display:flex;gap:8px;align-items:center"><i class="chev"></i>전사 공통 양식 <span class="chip">${corp.length}</span></h3>
  <div class="tgrid">${corp.map(tplCard).join('')}</div>`;
  renderAtt(); if (PICK) selTpl(PICK);
}
