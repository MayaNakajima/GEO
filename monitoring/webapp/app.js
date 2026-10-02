"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const WD = ["月","火","水","木","金","土","日"];
let MODELS = [];
let DOMAINS = {};   // 質問セット別の事業ドメイン {set1:[{code,label}], set2:[...], both:[...]}

async function api(path, opts){ const r = await fetch(path, opts); return r.json(); }

function currentSet(){ return $("#qset") ? $("#qset").value : "set1"; }

/* ---------- 初期化 ---------- */
async function init(){
  const d = await api("/api/models");
  MODELS = d.models || [];
  const dd = await api("/api/domains");
  DOMAINS = (dd && dd.domains) || {};
  renderModels();
  renderDomains();
  $("#jp-badge").textContent = d.has_jpholiday
    ? "祝日判定：日本の祝日を除外（jpholiday有効）"
    : "祝日判定：土日のみ除外（jpholiday未導入）";
  renderFreqFields();
  bindEvents();
  poll(); setInterval(poll, 1500);
  loadReports(); setInterval(loadReports, 8000);
  loadOsSchedule();
  loadAnalysisStatus(); setInterval(loadAnalysisStatus, 30000);
  initGoogleCheck();
}

function renderModels(){
  const box = $("#models"); box.innerHTML = "";
  MODELS.forEach(m => {
    const lab = document.createElement("label");
    if(!m.enabled) lab.classList.add("off");
    lab.innerHTML = `<input type="checkbox" value="${m.id}" ${m.enabled?"checked":""}>
      <span>${m.name}</span><span class="prov">${m.provider}${m.enabled?"":"・既定OFF"}</span>`;
    box.appendChild(lab);
  });
  box.addEventListener("change", updateModelCount);
  updateModelCount();
}
function updateModelCount(){
  const n = $$("#models input:checked").length;
  $("#model-count").textContent = `${n} モデル選択中`;
}
function selectedModels(){ return [...$$("#models input:checked")].map(x=>x.value); }

function renderDomains(){
  const sel = $("#domain");
  if(!sel) return;
  const prev = sel.value;
  sel.innerHTML = "";
  // 選択中の質問セットに実在する事業ドメインのみを提示（APIから動的取得）
  let doms = DOMAINS[currentSet()];
  if(!doms || !doms.length){
    // フォールバック（API未取得時）
    doms = [{code:"C1",label:"ユニフォーム"},{code:"C3",label:"メディカル"},
            {code:"C4",label:"インサイトセールス"},{code:"C5",label:"コーポレート"},
            {code:"C7",label:"ABM横断"}];
  }
  doms.forEach(d=>{ const o=document.createElement("option");
    o.value=d.code; o.textContent=`${d.code}：${d.label}`; sel.appendChild(o); });
  // 直前の選択が新しいセットにも存在すれば維持
  if(prev && doms.some(d=>d.code===prev)) sel.value = prev;
}

/* ---------- 頻度フィールド ---------- */
function renderFreqFields(){
  const kind = $("#freq-kind").value;
  const box = $("#freq-fields"); box.innerHTML = "";
  const wdBoxes = () => `<div class="wd">${WD.map((w,i)=>
      `<label><input type="checkbox" class="wd-c" value="${i}" ${i===0?"checked":""}>${w}</label>`).join("")}</div>`;
  if(kind==="every_n_days")
    box.innerHTML = `<span><input type="number" id="f-n" class="num" min="1" value="1"> 日おき</span>`;
  else if(kind==="weekly"||kind==="biweekly")
    box.innerHTML = `<span>曜日：</span>${wdBoxes()}`;
  else if(kind==="monthly_day")
    box.innerHTML = `<span>毎月 <input type="number" id="f-day" class="num" min="1" max="31" value="1"> 日</span>`;
  else if(kind==="nth_weekday")
    box.innerHTML = `<select id="f-nth">
        <option value="1">第1</option><option value="2">第2</option>
        <option value="3">第3</option><option value="4">第4</option>
        <option value="5">第5</option><option value="-1">最終</option></select>
      <select id="f-wd">${WD.map((w,i)=>`<option value="${i}">${w}曜</option>`).join("")}</select>`;
  else if(kind==="nth_business_day")
    box.innerHTML = `<span>毎月 第 <input type="number" id="f-nth" class="num" min="1" max="23" value="1"> 営業日</span>`;
  // first/last business day: フィールドなし
  previewSchedule();
}

function buildRule(){
  const kind = $("#freq-kind").value;
  const time = $("#freq-time").value || "09:00";
  const r = { kind, time };
  if(kind==="every_n_days") r.n = parseInt($("#f-n").value||"1");
  else if(kind==="weekly"||kind==="biweekly")
    r.weekdays = [...$$(".wd-c:checked")].map(x=>parseInt(x.value));
  else if(kind==="monthly_day") r.day = parseInt($("#f-day").value||"1");
  else if(kind==="nth_weekday"){ r.nth = parseInt($("#f-nth").value); r.weekday = parseInt($("#f-wd").value); }
  else if(kind==="nth_business_day") r.nth = parseInt($("#f-nth").value||"1");
  if($("#freq-holiday").checked) r.holiday_shift = "next_business_day";
  return r;
}

async function previewSchedule(){
  if(currentMode()!=="auto") return;
  const rule = buildRule();
  const offset = startOffset();
  const d = await api(`/api/preview_schedule?rule=${encodeURIComponent(JSON.stringify(rule))}&offset=${offset}`);
  $("#freq-preview").textContent = `設定：${d.desc}\n次回予定：\n  ` + (d.next||[]).join("\n  ");
}

/* ---------- 入力収集 ---------- */
function currentMode(){ return document.querySelector('input[name=mode]:checked').value; }
function startType(){ return document.querySelector('input[name=start]:checked').value; }
function startOffset(){ return startType()==="after_minutes" ? parseInt($("#start-min").value||"0") : 0; }
function repeatObj(){
  const t = document.querySelector('input[name=repeat]:checked').value;
  if(t==="interval") return {type:"interval",
     interval_minutes:parseInt($("#rep-int").value||"1"), count:parseInt($("#rep-cnt").value||"2")};
  return {type:"once"};
}
function payload(){
  const p = {
    models: selectedModels(),
    question_set: ($("#qset") ? $("#qset").value : "set1"),
    domain: $("#domain-on").checked ? $("#domain").value : null,
    mode: currentMode(),
    start: {type:startType(), minutes:startOffset()},
    repeat: repeatObj(),
    dry_run: $("#dry-run").checked,
  };
  if(currentMode()==="auto") p.frequency = buildRule();
  return p;
}

/* ---------- アクション ---------- */
async function doRun(){
  if(selectedModels().length===0){ return setMsg("モデルを1つ以上選択してください。","err"); }
  const p = payload();
  if(p.mode==="auto"){
    const d = await api("/api/schedule",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(p)});
    setMsg(d.message, d.ok?"ok":"err");
  }else{
    const d = await api("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(p)});
    setMsg(d.message, d.ok?"ok":"err");
  }
}
async function stopAuto(){ const d=await api("/api/schedule/stop",{method:"POST"}); setMsg(d.message,"ok"); }
async function cancel(){ const d=await api("/api/cancel",{method:"POST"}); setMsg(d.message,"ok"); }
function setMsg(t,cls){ const m=$("#msg"); m.textContent=t; m.className="msg "+(cls||""); }
function setOsMsg(t,cls){ const m=$("#os-msg"); m.textContent=t; m.className="msg "+(cls||""); }

/* ---------- OS自動実行（schedule.json） ---------- */
function osPayload(){
  // OS保存は常に自動実行として保存する（頻度は手動モードでも buildRule で拾う）
  const p = payload();
  p.mode = "auto";
  p.frequency = buildRule();
  return p;
}
async function saveOsSchedule(){
  if(selectedModels().length===0){ return setOsMsg("モデルを1つ以上選択してください。","err"); }
  const d = await api("/api/os_schedule/save",{method:"POST",
    headers:{"Content-Type":"application/json"},body:JSON.stringify(osPayload())});
  setOsMsg(d.message, d.ok?"ok":"err");
  renderOsStatus(d.schedule || (await api("/api/os_schedule")));
}
async function disableOsSchedule(){
  const d = await api("/api/os_schedule/disable",{method:"POST"});
  setOsMsg(d.message, d.ok?"ok":"err");
  renderOsStatus(d.schedule || (await api("/api/os_schedule")));
}
async function loadOsSchedule(){ renderOsStatus(await api("/api/os_schedule")); }
function renderOsStatus(s){
  const box = $("#os-status"); if(!box) return;
  if(!s || !s.exists){
    box.textContent = "現在の状態：未設定（OS自動実行の設定 schedule.json はまだありません）";
    return;
  }
  if(s.error){ box.textContent = "エラー："+s.error; return; }
  const lines = [];
  lines.push("現在の状態：" + (s.enabled ? "有効" : "無効（enabled:false）"));
  lines.push("頻度：" + (s.desc||""));
  const pl = s.plan||{};
  lines.push("モデル：" + ((pl.models||[]).join(", ")||"—") + "／質問セット：" + (pl.question_set||"set1")
             + (s.dry_run ? "／ドライラン":""));
  if(s.next && s.next.length){ lines.push("今後の予定："); s.next.forEach(n=>lines.push("  - "+n)); }
  const rh = s.register_hint;
  if(rh){ lines.push(""); lines.push("タスク登録：" + rh.note);
    lines.push("  → 起動時刻の既定は " + (rh.time||"09:00") + "（頻度の時刻に合わせています）"); }
  box.textContent = lines.join("\n");
}

/* ---------- 状態ポーリング ---------- */
function fmtCountdown(s){ if(s==null) return ""; const m=Math.floor(s/60), ss=s%60;
  return m>0 ? `あと ${m}分${ss}秒` : `あと ${ss}秒`; }

async function poll(){
  const s = await api("/api/state");
  const pill = $("#st-status");
  pill.textContent = {idle:"待機中",pending:"開始待ち",running:"実行中",scheduled:"自動実行 設定済"}[s.status]||s.status;
  pill.className = "pill "+s.status;
  $("#st-message").textContent = s.message||"";
  // 次回/カウントダウン
  let next = "";
  if(s.next_timing){ try{ next = "次回 "+new Date(s.next_timing).toLocaleString("ja-JP",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}); }catch(e){} }
  if(s.countdown_sec!=null) next += "（"+fmtCountdown(s.countdown_sec)+"）";
  $("#st-next").textContent = next;
  // 進捗バー
  const c = s.current||{}; let pct=0, detail="";
  if(c.total){ pct = Math.round(c.done/c.total*100);
    detail = `第${c.run_index}/${c.runs_total}回　${c.done}/${c.total}　${c.label||""} ${c.mark||""}`; }
  if(c.phase==="waiting" && c.wait_total_sec){ pct=Math.round(c.waited_sec/c.wait_total_sec*100);
    detail = `次の回まで待機中（第${c.next_run}回）`; }
  if(c.phase==="done"){ pct=100; }
  $("#st-bar").style.width = pct+"%";
  $("#st-detail").textContent = detail;
  $("#log").textContent = (s.log||[]).join("\n");
  $("#log").scrollTop = $("#log").scrollHeight;
  // 停止ボタン
  $("#btn-stop").classList.toggle("hidden", s.status!=="scheduled");
  // 履歴
  renderHist(s.history||[]);
}

/* ---------- レポート ---------- */
async function loadReports(){
  const d = await api("/api/reports");
  const box = $("#insights");
  box.innerHTML = (d.insights||[]).map(i=>`<div class="ins ${i.level}">${i.text}</div>`).join("")
    || '<div class="muted small">まだ示唆はありません。実行するとここに表示されます。</div>';
}
function renderHist(hist){
  const tb = $("#hist");
  tb.innerHTML = hist.map(h=>{
    const label = h.timing_label||h.timing_id;
    return `<tr><td>${label}</td><td>${h.mode||""}</td><td>${h.runs}</td>
      <td>${h.overall_mean}%</td><td>±${h.overall_sd}</td><td>${h.stability}%</td>
      <td><a class="exp" href="/api/export?scope=timing&id=${h.timing_id}">CSV</a></td></tr>`;
  }).join("") || '<tr><td colspan="7" class="muted">履歴なし</td></tr>';
}

/* ---------- 分析ダッシュボード（GEO-analysis） ---------- */
const ANALYSIS_LABEL = "🔎 分析ダッシュボードを開く（関係者向け）";
let ANALYSIS = null;       // /api/analysis_status の結果
let analysisBusy = false;
async function loadAnalysisStatus(){
  const btn = $("#btn-analysis"), box = $("#analysis-status");
  if(!btn) return;
  try{ ANALYSIS = await api("/api/analysis_status"); }
  catch(e){ ANALYSIS = {available:false, reason:"状態を取得できませんでした"}; }
  if(analysisBusy) return;
  const a = ANALYSIS;
  btn.disabled = !a.available;
  if(!a.available){
    btn.title = "利用できません：" + (a.reason||"");
    box.textContent = "分析ダッシュボード：無効（" + (a.reason||"") + "）";
    return;
  }
  const src = {local:"ローカル（GEO-analysis）", box:"Box 共有版"}[a.source] || "未生成";
  btn.title = a.can_regenerate && a.regenerate_on_open
    ? "最新の結果で analysis.html を再生成してから開きます（数十秒かかることがあります）"
    : "Box 上の analysis.html を開きます（このPCでは生成しません）";
  box.textContent = "分析ダッシュボード：最終生成 " + (a.mtime||"—") + "／表示：" + src
    + (a.can_regenerate ? "" : "（このPCでは生成しません）");
}
function openAnalysis(){
  if(analysisBusy || !ANALYSIS || !ANALYSIS.available) return;
  const btn = $("#btn-analysis");
  const w = window.open("/api/analysis","_blank");
  analysisBusy = true;
  btn.disabled = true;
  btn.textContent = "⏳ 生成中…（新しいタブに表示されます）";
  const started = Date.now();
  const done = ()=>{ clearInterval(t); analysisBusy = false;
    btn.textContent = ANALYSIS_LABEL; loadAnalysisStatus(); };
  const t = setInterval(()=>{
    let loaded = false;
    try{ loaded = !w || w.closed ||
      (w.location.pathname==="/api/analysis" && w.document.readyState!=="loading"); }
    catch(e){ loaded = true; }
    if(loaded || Date.now()-started > 5*60*1000) done();
  }, 700);
}

/* ---------- イベント ---------- */
function bindEvents(){
  $("#sel-all").onclick = ()=>{ $$("#models input").forEach(x=>x.checked=true); updateModelCount(); };
  $("#sel-none").onclick = ()=>{ $$("#models input").forEach(x=>x.checked=false); updateModelCount(); };
  $$('input[name=mode]').forEach(r=>r.onchange = ()=>{
    const auto = currentMode()==="auto";
    $("#freq-block").classList.toggle("hidden", !auto);
    $("#start-now-label").textContent = auto ? "すぐ1回目を実行" : "すぐ実行";
    $("#btn-run").textContent = auto ? "▶ 自動実行を設定" : "▶ 実行する";
    previewSchedule();
  });
  $("#freq-kind").onchange = renderFreqFields;
  $("#freq-time").onchange = previewSchedule;
  $("#freq-holiday").onchange = previewSchedule;
  $("#freq-fields").addEventListener("change", previewSchedule);
  $$('input[name=start]').forEach(r=>r.onchange = previewSchedule);
  $("#start-min").onchange = previewSchedule;
  $("#domain-on").onchange = ()=> $("#domain").classList.toggle("hidden-inline", !$("#domain-on").checked);
  if($("#qset")) $("#qset").onchange = renderDomains;   // 質問セット変更でドメイン候補を切替
  $("#btn-run").onclick = doRun;
  $("#btn-stop").onclick = stopAuto;
  $("#btn-cancel").onclick = cancel;
  $("#btn-dash").onclick = ()=> window.open("/api/dashboard","_blank");
  if($("#btn-insight")) $("#btn-insight").onclick = ()=> window.open("/api/insights","_blank");
  if($("#btn-analysis")) $("#btn-analysis").onclick = openAnalysis;
  $("#btn-export-all").onclick = ()=> window.open("/api/export?scope=all","_blank");
  if($("#btn-os-save"))    $("#btn-os-save").onclick = saveOsSchedule;
  if($("#btn-os-disable")) $("#btn-os-disable").onclick = disableOsSchedule;
}

/* ---------- Google 検索チェック ---------- */
let GC = null;
const gcEsc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
async function copyText(t, btn){
  try { await navigator.clipboard.writeText(t); const o = btn.textContent; btn.textContent = "コピーしました"; setTimeout(()=>btn.textContent = o, 1500); }
  catch(e){ prompt("コピーしてください", t); }
}
function initGoogleCheck(){
  if(!$("#gc-panel")) return;
  $("#gc-reload").onclick = ()=> loadGoogleCheck();
  $("#gc-month").onchange = ()=> loadGoogleCheck($("#gc-month").value);
  $("#gc-only-todo").onchange = renderGoogleCheck;
  $("#gc-bm-copy").onclick = e => GC && copyText(GC.bookmarklet, e.target);
  $("#gc-start-copy").onclick = e => GC && copyText(GC.start_url, e.target);
  $("#gc-raw-save").onclick = async ()=>{
    let d; try { d = JSON.parse($("#gc-raw").value); } catch(e){ $("#gc-raw-msg").textContent = "貼り付けた内容を読み取れません"; return; }
    const r = await api("/api/gc/save", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(d)});
    $("#gc-raw-msg").textContent = r.ok ? `記録しました：${r.term}（自社 ${r.own_rank}）` : (r.message || "記録できませんでした");
    if(r.ok){ $("#gc-raw").value = ""; loadGoogleCheck(); }
  };
  $("#gcc-save").onclick = saveCompetitor;
  $("#gc-comp").addEventListener("toggle", ()=>{ if($("#gc-comp").open) loadCompetitors(); });
  loadGoogleCheck(); setInterval(()=> loadGoogleCheck(GC && GC.month), 15000);
  loadCompetitors();
}
/* 競合辞書（検索結果の競合判定） */
let GCC = null;
async function loadCompetitors(){
  try { GCC = await api("/api/gc/competitors" + (GC && GC.month ? `?month=${encodeURIComponent(GC.month)}` : "")); } catch(e){ return; }
  const nMedia = GCC.competitors.filter(c => c.kind === "media").length;
  $("#gc-comp-count").textContent = `（競合 ${GCC.competitors.length - nMedia} 社・媒体 ${nMedia} 件）`;
  $("#gc-sugg").innerHTML = GCC.suggestions.length
    ? GCC.suggestions.map(s => `<span class="sugg" title="クリックでドメイン欄に入れる" onclick="gcSuggest('${gcEsc(s.domain)}')">${gcEsc(s.domain)} ×${s.count}</span>`).join("")
    : "候補はありません（検索チェックを記録すると、上位10件によく出るドメインがここに出ます）";
  $("#gc-comp-table").innerHTML = `<thead><tr><th>種類</th><th>名前</th><th>ドメイン</th><th>区分</th><th>AI 回答の辞書</th><th>メモ</th><th></th></tr></thead><tbody>`
    + GCC.competitors.map((c, i) => `<tr><td class="small">${c.kind === "media" ? "媒体" : "競合"}</td><td>${gcEsc(c.canonical)}</td><td class="small">${gcEsc((c.domains||[]).join(", "))}</td>
        <td class="small">${gcEsc({A:"既存",B:"Claude の回答から",C:"検索結果から",手動:"手動"+(c.added?`（${c.added}）`:""),媒体:"媒体"+(c.added?`（${c.added}）`:"")}[c.group] || c.group || "")}</td>
        <td class="small">${c.in_ai ? "登録あり" : "–"}</td><td class="small">${gcEsc(c.note||"")}</td>
        <td style="white-space:nowrap"><button class="mini" onclick="gcEditComp(${i})">編集</button>
          <button class="mini" onclick="gcDeleteComp(${i})">削除</button></td></tr>`).join("") + `</tbody>`;
}
function gcSuggest(d){ const el = $("#gcc-domains"); el.value = el.value ? el.value + ", " + d : d; $("#gcc-name").focus(); }
function gcEditComp(i){ const c = GCC.competitors[i];
  $("#gcc-kind").value = c.kind || "comp";
  $("#gcc-name").value = c.canonical; $("#gcc-domains").value = (c.domains||[]).join(", "); $("#gcc-note").value = c.note || "";
  $("#gcc-name").scrollIntoView({behavior:"smooth", block:"center"}); }
async function saveCompetitor(){
  const split = v => v.split(/[,、\s]+/).map(x=>x.trim()).filter(Boolean);
  const body = {kind: $("#gcc-kind").value, canonical: $("#gcc-name").value.trim(), domains: split($("#gcc-domains").value),
                note: $("#gcc-note").value.trim(), also_ai: $("#gcc-ai").checked, aliases: split($("#gcc-aliases").value)};
  const r = await api("/api/gc/competitors/save", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
  $("#gcc-msg").textContent = r.message || "";
  if(r.ok){ ["#gcc-name","#gcc-domains","#gcc-note","#gcc-aliases"].forEach(s=>$(s).value=""); $("#gcc-ai").checked=false;
    loadCompetitors(); loadGoogleCheck(GC && GC.month); }
}
async function gcDeleteComp(i){ const c = GCC.competitors[i];
  if(!confirm(`「${c.canonical}」を辞書（検索結果の判定用）から削除しますか？（AI 回答の辞書 competitors.json からは削除しません）`)) return;
  const r = await api("/api/gc/competitors/delete", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({canonical: c.canonical, kind: c.kind})});
  $("#gcc-msg").textContent = r.message || ""; loadCompetitors(); loadGoogleCheck(GC && GC.month);
}
async function loadGoogleCheck(month){
  try { GC = await api("/api/gc/state" + (month ? `?month=${encodeURIComponent(month)}` : "")); } catch(e){ return; }
  const sel = $("#gc-month");
  sel.innerHTML = GC.months.map(m => `<option value="${m}">${m}</option>`).join("");
  sel.value = GC.month;
  $("#gc-progress").textContent = `記録済み ${GC.done} / ${GC.total} 件（設問文とキーワード。重複する語は1件）`;
  $("#gc-bar").style.width = (GC.total ? Math.round(GC.done / GC.total * 100) : 0) + "%";
  $("#gc-bm").setAttribute("href", GC.bookmarklet);
  $("#gc-port").textContent = GC.port;
  $("#gc-start").textContent = GC.start_url;
  renderGoogleCheck();
}
function renderGoogleCheck(){
  if(!GC) return;
  const only = $("#gc-only-todo").checked;
  const rows = GC.items.map((it, i) => ({it, i})).filter(x => !only || !x.it.done);
  $("#gc-table").innerHTML = `<thead><tr><th>状態</th><th>検索語</th><th>設問ID</th><th>自社順位</th><th>AI による概要</th>
      <th>上位10件内の競合</th><th>記録</th><th></th></tr></thead><tbody>`
    + rows.map(({it, i}) => `<tr>
      <td class="${it.done ? "done" : "todo"}">${it.done ? "✔ 記録済み" : "未記録"}</td>
      <td>${gcEsc(it.term)}<div class="kind">${gcEsc(it.kinds.join("・"))}｜${gcEsc(it.domain_label)}</div></td>
      <td class="small">${gcEsc(it.qids.join(" "))}</td>
      <td>${it.done ? (it.own_rank === "圏外" ? "圏外" : gcEsc(it.own_rank) + " 位") : "–"}</td>
      <td>${it.done ? gcEsc(it.aio) + (it.aio === "あり" ? `（自社引用 ${gcEsc(it.aio_own)}）` : "") : "–"}</td>
      <td class="small">${gcEsc(it.competitors || (it.done ? "なし" : "–"))}</td>
      <td class="small">${gcEsc(it.observed_at)}${it.method ? `<br>${gcEsc(it.method)}` : ""}</td>
      <td style="white-space:nowrap"><a class="exp" href="${gcEsc(it.url)}" target="_blank" rel="noopener">検索を開く</a>
        <button class="mini" onclick="gcManual(${i})">手入力</button>
        ${it.done && GC.month ? `<button class="mini" onclick="gcDelete(${i})">取消</button>` : ""}</td></tr>`).join("")
    + `</tbody>`;
}
function gcManual(i){
  const it = GC.items[i], box = $("#gc-manual");
  box.classList.remove("hidden");
  box.innerHTML = `<b>手入力：</b>${gcEsc(it.term)}
    <div class="row" style="margin-top:8px">
      <label>自社の最高順位 <input type="text" id="gm-rank" size="4" placeholder="1〜10 / 圏外"></label>
      <label class="chk"><input type="checkbox" id="gm-aio"> AI による概要あり</label>
      <label class="chk"><input type="checkbox" id="gm-aio-own"> 概要に自社の引用あり</label></div>
    <div class="row" style="margin-top:6px">
      <label>上位10件内の競合 <input type="text" id="gm-comp" size="30" placeholder="例：ナガイレーベン;フォーク"></label>
      <label>メモ <input type="text" id="gm-memo" size="30"></label>
      <button class="primary" id="gm-save">記録</button> <button class="ghost" id="gm-cancel">閉じる</button></div>`;
  $("#gm-cancel").onclick = ()=> box.classList.add("hidden");
  $("#gm-save").onclick = async ()=>{
    const body = {q: it.term, own_rank: $("#gm-rank").value.trim() || "圏外", aio: $("#gm-aio").checked,
                  aio_own: $("#gm-aio-own").checked, competitors: $("#gm-comp").value, memo: $("#gm-memo").value};
    const r = await api("/api/gc/manual", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
    if(r.ok){ box.classList.add("hidden"); loadGoogleCheck(GC.month); } else alert(r.message || "記録できませんでした");
  };
  box.scrollIntoView({behavior:"smooth", block:"center"});
}
async function gcDelete(i){
  const it = GC.items[i];
  if(!confirm(`「${it.term}」の ${GC.month} の記録を取り消しますか？（もう一度検索して記録し直せます）`)) return;
  await api("/api/gc/delete", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({term: it.term, month: GC.month})});
  loadGoogleCheck(GC.month);
}

init();
