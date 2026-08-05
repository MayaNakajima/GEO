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
  $("#freq-fields").addEventListener("change", previewSchedule);
  $$('input[name=start]').forEach(r=>r.onchange = previewSchedule);
  $("#start-min").onchange = previewSchedule;
  $("#domain-on").onchange = ()=> $("#domain").classList.toggle("hidden-inline", !$("#domain-on").checked);
  if($("#qset")) $("#qset").onchange = renderDomains;   // 質問セット変更でドメイン候補を切替
  $("#btn-run").onclick = doRun;
  $("#btn-stop").onclick = stopAuto;
  $("#btn-cancel").onclick = cancel;
  $("#btn-dash").onclick = ()=> window.open("/api/dashboard","_blank");
  $("#btn-export-all").onclick = ()=> window.open("/api/export?scope=all","_blank");
  if($("#btn-os-save"))    $("#btn-os-save").onclick = saveOsSchedule;
  if($("#btn-os-disable")) $("#btn-os-disable").onclick = disableOsSchedule;
}

init();
