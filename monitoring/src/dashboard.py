"""
HTMLダッシュボード生成
────────────────────────────────────────────────
data/reports/ の集計結果（index.json / timing_*.json / trend.json）を読み込み、
単一の自己完結HTML（data/dashboard.html）を生成する。
サーバがなくてもブラウザで直接開ける（グラフは Chart.js CDN を使用）。
────────────────────────────────────────────────
"""

import json
from pathlib import Path


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def render(reports_dir: Path, out_path: Path) -> Path:
    reports_dir = Path(reports_dir)
    index = _load(reports_dir / "index.json", [])
    trend = _load(reports_dir / "trend.json", {})
    timings = {}
    for p in sorted(reports_dir.glob("timing_*.json")):
        t = _load(p, None)
        if t:
            timings[t["timing_id"]] = t

    data = {"index": index, "trend": trend, "timings": timings}
    payload = json.dumps(data, ensure_ascii=False)

    html = _TEMPLATE.replace("/*__DATA__*/", payload)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI出現モニタリング ダッシュボード</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root{--bg:#0f172a;--card:#1e293b;--ink:#e2e8f0;--sub:#94a3b8;--accent:#38bdf8;
        --good:#34d399;--warn:#fbbf24;--bad:#f87171;--line:#334155;}
  *{box-sizing:border-box}
  body{margin:0;font-family:"Segoe UI","Hiragino Kaku Gothic ProN",Meiryo,sans-serif;
       background:var(--bg);color:var(--ink);}
  header{padding:20px 28px;border-bottom:1px solid var(--line);}
  header h1{margin:0;font-size:20px;}
  header .sub{color:var(--sub);font-size:13px;margin-top:4px;}
  .tabs{display:flex;gap:8px;padding:14px 28px 0;}
  .tab{padding:9px 16px;border-radius:8px 8px 0 0;background:transparent;color:var(--sub);
       cursor:pointer;border:1px solid transparent;font-size:14px;}
  .tab.active{background:var(--card);color:var(--ink);border-color:var(--line);border-bottom:none;}
  main{padding:20px 28px 60px;}
  .grid{display:grid;gap:16px;}
  .kpis{grid-template-columns:repeat(auto-fit,minmax(160px,1fr));}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;}
  .kpi .v{font-size:30px;font-weight:700;}
  .kpi .l{color:var(--sub);font-size:12px;margin-top:2px;}
  .kpi .d{font-size:12px;margin-top:6px;}
  .up{color:var(--good)} .down{color:var(--bad)} .flat{color:var(--sub)}
  h2{font-size:15px;margin:24px 0 10px;border-left:3px solid var(--accent);padding-left:8px;}
  table{width:100%;border-collapse:collapse;font-size:13px;}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);}
  th{color:var(--sub);font-weight:600;}
  select{background:var(--card);color:var(--ink);border:1px solid var(--line);
         border-radius:8px;padding:8px 10px;font-size:14px;}
  .ins{border-left:4px solid var(--line);padding:10px 14px;margin:8px 0;border-radius:6px;background:#0b1220;}
  .ins.high{border-color:var(--bad)} .ins.medium{border-color:var(--warn)}
  .ins.info{border-color:var(--accent)}
  .pill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;background:#0b1220;color:var(--sub);border:1px solid var(--line);}
  .muted{color:var(--sub);font-size:13px;}
  canvas{max-height:340px;}
  .hidden{display:none;}
  /* ★v8 追加スタイル ---------------------------------------------------- */
  /* 1文サマリーバナー */
  .summary{margin:4px 0 16px;padding:14px 18px;border-radius:12px;font-size:15px;
           line-height:1.7;background:#0b1220;border:1px solid var(--line);border-left:5px solid var(--accent);}
  .summary.good{border-left-color:var(--good);} .summary.bad{border-left-color:var(--bad);}
  .summary.flat{border-left-color:var(--sub);}
  .summary b{color:var(--ink);}
  .summary .tagup{color:var(--good);font-weight:700;} .summary .tagdown{color:var(--bad);font-weight:700;}
  .summary .tagflat{color:var(--sub);font-weight:700;}
  /* 「この画面の見方」折りたたみ */
  details.howto{margin:0 0 16px;background:#0b1220;border:1px solid var(--line);border-radius:10px;}
  details.howto>summary{cursor:pointer;padding:10px 14px;color:var(--accent);font-size:13px;list-style:none;}
  details.howto>summary::-webkit-details-marker{display:none;}
  details.howto>summary::before{content:"▸ ";}
  details.howto[open]>summary::before{content:"▾ ";}
  details.howto .body{padding:2px 16px 14px;color:var(--sub);font-size:13px;line-height:1.8;}
  /* 表の上の「見方」注記 */
  .tablenote{color:var(--sub);font-size:12px;margin:0 0 8px;}
  /* 用語ツールチップ（❓） */
  .term{position:relative;display:inline-block;margin-left:5px;width:15px;height:15px;line-height:15px;
        text-align:center;border-radius:50%;background:#0b1220;border:1px solid var(--line);
        color:var(--sub);font-size:10px;cursor:help;vertical-align:middle;font-weight:400;}
  .term .tip{visibility:hidden;opacity:0;position:absolute;z-index:20;left:50%;bottom:150%;
        transform:translateX(-50%);width:240px;padding:9px 11px;border-radius:8px;background:#020617;
        border:1px solid var(--line);color:var(--ink);font-size:12px;line-height:1.6;font-weight:400;
        text-align:left;transition:opacity .12s;box-shadow:0 6px 20px rgba(0,0,0,.5);}
  .term:hover .tip{visibility:visible;opacity:1;}
  h2 .term{vertical-align:1px;}
  /* Set比較タブ */
  .interp{border-left:4px solid var(--warn);background:#0b1220;padding:12px 16px;border-radius:8px;
          margin:14px 0;font-size:14px;line-height:1.8;}
  .interp .lead{font-size:15px;font-weight:700;color:var(--ink);}
  .actions{border:1px solid var(--line);background:var(--card);border-radius:10px;padding:12px 16px 12px 34px;
           margin:12px 0;font-size:14px;line-height:1.9;}
  .actions li{margin:2px 0;}
  .badge-cliff{display:inline-block;padding:2px 8px;border-radius:6px;background:rgba(248,113,113,.18);
               color:var(--bad);border:1px solid var(--bad);font-size:11px;font-weight:700;}
</style>
</head>
<body>
<header>
  <h1>🔍 AI出現モニタリング ダッシュボード</h1>
  <div class="sub">株式会社オンワードコーポレートデザイン｜GEO定点観測</div>
</header>
<div class="tabs">
  <div class="tab active" data-t="trend">時系列トレンド</div>
  <div class="tab" data-t="timing">タイミング詳細（ブレ）</div>
  <div class="tab" data-t="setcompare">Set比較・崖の分析</div>
</div>
<main>
  <section id="tab-trend">
    <div id="trend-summary"></div>
    <details class="howto">
      <summary>この画面の見方</summary>
      <div class="body">
        ① まず上のサマリーで前回からの増減（改善／低下）を確認 →
        ② 「全体出現率の推移」グラフで山・谷を見る →
        ③ 「事業ドメイン別」で伸びた／落ちた事業を特定 →
        ④ 「施策への示唆」で次にやることを確認。<br>
        ※ <b>出現率</b>＝質問（＝AIへの問いかけ）のうち、回答に当社が言及された割合。高いほど良い。
      </div>
    </details>
    <div class="grid kpis" id="trend-kpis"></div>
    <h2>全体出現率の推移（平均±SD<span class="term">?<span class="tip"><b>SD（標準偏差）</b>：同じ条件を複数回実行したときの“ブレ”幅。小さいほど毎回同じ結果＝安定。</span></span>）</h2>
    <div class="card"><canvas id="chart-overall"></canvas></div>
    <h2>モデル別 出現率の推移</h2>
    <div class="card"><canvas id="chart-model"></canvas></div>
    <h2>事業ドメイン別 出現率の推移</h2>
    <div class="card"><canvas id="chart-domain"></canvas></div>
    <h2>特異度ティア別 出現率の推移（Set2：D1→D4<span class="term">?<span class="tip"><b>特異度（D1〜D4）</b>：質問の“当社の指名度・具体度”。D1=社名指名／D2=業種・実績／D3=非指名の高特異度／D4=一般需要。</span></span>）</h2>
    <div class="card"><canvas id="chart-tier"></canvas><p class="muted" id="tier-empty"></p></div>
    <h2>質問セット別 出現率の推移（Set1／Set2）</h2>
    <div class="card"><canvas id="chart-set"></canvas><p class="muted" id="set-empty"></p></div>
    <h2>施策への示唆</h2>
    <div id="insights"></div>
    <h2>前回比の変動（事業ドメイン）</h2>
    <p class="tablenote">＝前回から出現率が動いた事業。プラス（<span class="up">緑</span>）は改善、マイナス（<span class="down">赤</span>）は低下。0%横ばいは前回から変化なし。</p>
    <div class="card"><table id="movers"><thead><tr><th>ドメイン</th><th>前回</th><th>最新</th><th>変動</th></tr></thead><tbody></tbody></table></div>
  </section>

  <section id="tab-timing" class="hidden">
    <details class="howto">
      <summary>この画面の見方</summary>
      <div class="body">
        1つの「タイミング（同じ日時に連続実行した1セット）」を選び、同じ質問を複数回投げたときに
        結果がどれだけ<b>ブレる（毎回同じ答えにならない）</b>かを見ます。
        安定性スコアが高いほど、出た／出ないの判定が毎回一致していて信頼できます。
      </div>
    </details>
    <div class="card" style="margin-bottom:16px">
      <label class="muted">タイミングを選択：</label>
      <select id="timing-select"></select>
    </div>
    <div class="grid kpis" id="timing-kpis"></div>
    <h2>回ごとの全体出現率（同一タイミング内）</h2>
    <div class="card"><canvas id="chart-runs"></canvas></div>
    <h2>モデル別 平均±SD</h2>
    <div class="card"><canvas id="chart-tmodel"></canvas></div>
    <h2>特異度ティア別 出現率（Set2：D1→D4・崖の可視化）</h2>
    <div class="card"><canvas id="chart-ttier"></canvas><p class="muted" id="ttier-empty"></p></div>
    <h2>質問セット別 出現率（Set1／Set2）</h2>
    <div class="card"><canvas id="chart-tset"></canvas><p class="muted" id="tset-empty"></p></div>
    <h2>出現が安定していない質問（ブレあり<span class="term">?<span class="tip"><b>安定性スコア</b>：毎回同じ判定（出た／出ない）だったセルの割合。100%＝完全に安定。ここに並ぶのは複数回のうち一部でしか出なかった質問。</span></span>）</h2>
    <div class="card"><table id="unstable"><thead><tr><th>質問ID</th><th>モデル</th><th>ドメイン</th><th>出現回数</th><th>質問</th></tr></thead><tbody></tbody></table></div>
    <p class="muted" id="stability-note"></p>
  </section>

  <section id="tab-setcompare" class="hidden">
    <details class="howto">
      <summary>この画面の見方</summary>
      <div class="body">
        Set2の<b>特異度カーブ</b>で「どの具体度から当社が消えるか＝<b>崖</b>」を見ます。<br>
        指名（D1）→業種・実績（D2）→高特異度・非指名（D3）→一般需要（D4）の順に、
        質問が“当社名を出さない一般的な問い”へ移るにつれ出現率がどこで落ちるかを確認し、
        その手前が最優先で埋めるべきGEOギャップです。
      </div>
    </details>
    <div id="sc-summary"></div>
    <h2>特異度カーブ（D1→D4）<span class="term">?<span class="tip"><b>特異度（D1〜D4）</b>：質問の“当社の指名度・具体度”。D1=社名指名／D2=業種・実績／D3=非指名の高特異度／D4=一般需要。右へ行くほど一般的な問い。</span></span></h2>
    <div class="card"><canvas id="chart-curve"></canvas><p class="muted" id="curve-empty"></p></div>
    <div id="sc-interp"></div>
    <div id="sc-actions"></div>
    <h2>Set1×Set2 サマリー</h2>
    <div class="card"><table id="sc-table"><thead><tr><th>指標</th><th>Set1（78問・理想ターゲット）</th><th>Set2（60問・診断用）</th><th>見方</th></tr></thead><tbody></tbody></table></div>
  </section>
</main>
<script>
const DATA = /*__DATA__*/;
const C = {ink:'#e2e8f0',sub:'#94a3b8',accent:'#38bdf8',good:'#34d399',warn:'#fbbf24',bad:'#f87171',line:'#334155'};
Chart.defaults.color = C.sub; Chart.defaults.borderColor = C.line;
const PALETTE=['#38bdf8','#34d399','#fbbf24','#f87171','#a78bfa','#f472b6','#22d3ee','#facc15'];
let charts={};
function destroy(id){ if(charts[id]){charts[id].destroy(); delete charts[id];} }

function kpi(v,l,d){ const dd = d? `<div class="d ${d.cls}">${d.txt}</div>`:'';
  return `<div class="card kpi"><div class="v">${v}</div><div class="l">${l}</div>${dd}</div>`; }

/* 配列の末尾（最新）の非null値を返す ★v8 */
function lastVal(arr){ if(!arr) return null;
  for(let i=arr.length-1;i>=0;i--){ if(arr[i]!==null&&arr[i]!==undefined) return arr[i]; } return null; }

/* 1文サマリーバナー（過去回比較を言葉と色で明示）★v8 */
function buildSummary(t){
  const el=document.getElementById('trend-summary'); if(!el) return;
  const series=t.series||[]; if(!series.length){ el.innerHTML=''; return; }
  const latest=t.latest||series[series.length-1];
  const d=t.deltas||{};
  const tag=(v)=> (v===undefined||v===null)? '' :
      v>0? `<span class="tagup">▲+${v}pt 改善</span>` :
      v<0? `<span class="tagdown">▼${v}pt 低下</span>` :
           `<span class="tagflat">±${v}pt 横ばい</span>`;
  let cls='flat'; if(d.vs_prev>0) cls='good'; else if(d.vs_prev<0) cls='bad';
  const ts=t.tier_series||{};
  const D1=lastVal(ts.D1), D2=lastVal(ts.D2);
  let tierMsg='';
  if(D1!==null){
    if(D1>0 && (D2===0||D2===null)) tierMsg='ヒットは<b>指名質問（D1）</b>に集中。業種・実績質問（D2）以下は0%のままです。';
    else if(D1===0)                 tierMsg='指名質問（D1）でも出現しておらず、学習記憶に当社情報が薄い可能性。';
    else                            tierMsg='非指名（D2以下）でも出現が確認できています。';
  }
  const cmp=[ (d.vs_prev!==undefined?`前回比 ${tag(d.vs_prev)}`:''),
              (d.vs_baseline!==undefined?`初回比 ${tag(d.vs_baseline)}`:'') ].filter(Boolean).join('／');
  el.className='summary '+cls;
  el.innerHTML=`最新は<b>全体${latest.overall_mean}%</b>${cmp?`（${cmp}）`:''}。${tierMsg}`;
}

/* ---------- トレンド ---------- */
function renderTrend(){
  const t = DATA.trend||{}; const series=t.series||[];
  buildSummary(t);
  const kp = document.getElementById('trend-kpis');
  if(!series.length){ kp.innerHTML='<div class="card muted">まだデータがありません。実行するとここに表示されます。</div>'; return; }
  const latest=t.latest||series[series.length-1];
  const d=t.deltas||{};
  const dcell=(val)=> val===undefined? null : {cls: val>0?'up':(val<0?'down':'flat'),
      txt:(val>0?'▲+'+val+'pt 改善':val<0?'▼'+val+'pt 低下':'±'+val+'pt 横ばい')};
  kp.innerHTML =
    kpi(latest.overall_mean+'%','最新 全体出現率(平均)') +
    kpi('±'+latest.overall_sd+'pt','最新 SD（ブレ）') +
    kpi(latest.stability+'%','最新 安定性スコア') +
    kpi((d.vs_prev!==undefined?d.vs_prev+'pt':'—'),'前回比', dcell(d.vs_prev)) +
    kpi((d.vs_baseline!==undefined?d.vs_baseline+'pt':'—'),'初回比', dcell(d.vs_baseline)) +
    kpi(t.timing_count||series.length,'タイミング数');

  const labels=series.map(s=>s.label);
  // overall + SD band
  const means=series.map(s=>s.overall_mean);
  const upper=series.map(s=>Math.round((s.overall_mean+s.overall_sd)*10)/10);
  const lower=series.map(s=>Math.round((s.overall_mean-s.overall_sd)*10)/10);
  destroy('overall');
  charts.overall=new Chart(document.getElementById('chart-overall'),{type:'line',
    data:{labels,datasets:[
      {label:'+SD',data:upper,borderColor:'transparent',backgroundColor:'rgba(56,189,248,.15)',pointRadius:0,fill:'+1'},
      {label:'-SD',data:lower,borderColor:'transparent',backgroundColor:'rgba(56,189,248,.15)',pointRadius:0,fill:false},
      {label:'全体出現率(平均)',data:means,borderColor:C.accent,backgroundColor:C.accent,tension:.25,pointRadius:4},
    ]},
    options:{plugins:{legend:{labels:{filter:i=>i.text.indexOf('SD')<0}}},
      scales:{y:{beginAtZero:true,max:100,ticks:{callback:v=>v+'%'}}}}});

  drawMulti('model', t.model_series, labels);
  drawMulti('domain', t.domain_series, labels);
  drawOrdered('tier', t.tier_series, labels, ['D1','D2','D3','D4'],
              {D1:'D1 指名',D2:'D2 業種・実績',D3:'D3 高特異度・非指名',D4:'D4 一般需要'},
              'tier-empty','特異度ティア別のデータは、Set2（または両方）を実行すると表示されます。');
  drawOrdered('set', t.set_series, labels, ['set1','set2'],
              {set1:'Set1 理想ターゲット78問',set2:'Set2 診断用60問'},
              'set-empty','質問セット別のデータは、実行後に表示されます。');

  // insights
  const ins=document.getElementById('insights');
  ins.innerHTML=(t.insights||[]).map(i=>`<div class="ins ${i.level}">${i.text}</div>`).join('')
    || '<div class="muted">示唆はありません。</div>';

  // movers
  const mb=document.querySelector('#movers tbody');
  mb.innerHTML=(t.movers||[]).map(m=>{const cls=m.delta>0?'up':(m.delta<0?'down':'flat');
    const s=(m.delta>0?'+':'')+m.delta+'pt';
    return `<tr><td>${m.domain}</td><td>${m.previous}%</td><td>${m.current}%</td><td class="${cls}">${s}</td></tr>`;}).join('')
    || '<tr><td colspan="4" class="muted">前回比データは2タイミング以降で表示されます。</td></tr>';
}

function drawMulti(id, seriesObj, labels){
  destroy(id);
  const names=Object.keys(seriesObj||{});
  const ds=names.map((n,i)=>({label:n,data:seriesObj[n],borderColor:PALETTE[i%PALETTE.length],
     backgroundColor:PALETTE[i%PALETTE.length],tension:.25,pointRadius:3,spanGaps:true}));
  charts[id]=new Chart(document.getElementById('chart-'+id),{type:'line',
    data:{labels,datasets:ds},
    options:{scales:{y:{beginAtZero:true,max:100,ticks:{callback:v=>v+'%'}}}}});
}

/* 指定順（例 D1→D4）で系列を描く折れ線。データが無ければメッセージ表示。★v7 */
function drawOrdered(id, seriesObj, labels, order, nameMap, emptyId, emptyMsg){
  destroy(id);
  const so=seriesObj||{};
  const keys=order.filter(k=>k in so);
  const emp=document.getElementById(emptyId);
  const cv=document.getElementById('chart-'+id);
  if(!keys.length){ if(cv) cv.style.display='none'; if(emp) emp.textContent=emptyMsg; return; }
  if(cv) cv.style.display=''; if(emp) emp.textContent='';
  const ds=keys.map((k,i)=>({label:(nameMap&&nameMap[k])||k,data:so[k],
     borderColor:PALETTE[i%PALETTE.length],backgroundColor:PALETTE[i%PALETTE.length],
     tension:.25,pointRadius:3,spanGaps:true}));
  charts[id]=new Chart(cv,{type:'line',data:{labels,datasets:ds},
    options:{scales:{y:{beginAtZero:true,max:100,ticks:{callback:v=>v+'%'}}}}});
}

/* 単一タイミングの棒グラフ（mean、SDはツールチップ）。指定順・空表示対応。★v7 */
function drawBar(id, statsObj, order, nameMap, emptyId, emptyMsg){
  destroy(id);
  const so=statsObj||{};
  const keys=order.filter(k=>k in so);
  const emp=document.getElementById(emptyId);
  const cv=document.getElementById('chart-'+id);
  if(!keys.length){ if(cv) cv.style.display='none'; if(emp) emp.textContent=emptyMsg; return; }
  if(cv) cv.style.display=''; if(emp) emp.textContent='';
  charts[id]=new Chart(cv,{type:'bar',
    data:{labels:keys.map(k=>(nameMap&&nameMap[k])||k),
      datasets:[{label:'平均出現率',data:keys.map(k=>so[k].mean),
        backgroundColor:keys.map((_,i)=>PALETTE[i%PALETTE.length])}]},
    options:{plugins:{tooltip:{callbacks:{afterLabel:(c)=>'SD ±'+so[keys[c.dataIndex]].sd+'pt'}}},
      scales:{y:{beginAtZero:true,max:100,ticks:{callback:v=>v+'%'}}}}});
}

/* ---------- タイミング詳細 ---------- */
function renderTimingSelector(){
  const sel=document.getElementById('timing-select');
  const ids=Object.keys(DATA.timings||{}).sort().reverse();
  sel.innerHTML=ids.map(id=>`<option value="${id}">${DATA.timings[id].timing_label}（${DATA.timings[id].runs}回）</option>`).join('');
  if(ids.length){ sel.value=ids[0]; renderTiming(ids[0]); }
  else { document.getElementById('timing-kpis').innerHTML='<div class="card muted">まだデータがありません。</div>'; }
  sel.onchange=()=>renderTiming(sel.value);
}
function renderTiming(id){
  const t=DATA.timings[id]; if(!t) return;
  const o=t.overall, st=t.stability;
  document.getElementById('timing-kpis').innerHTML=
    kpi(o.mean+'%','全体出現率(平均)') +
    kpi('±'+o.sd+'pt','SD（ブレ）') +
    kpi(o.min+'〜'+o.max+'%','最小〜最大') +
    kpi(t.runs+'回','実行回数') +
    kpi(st.score+'%','安定性スコア') +
    kpi(st.unstable_cells,'ブレたセル数');

  destroy('runs');
  charts.runs=new Chart(document.getElementById('chart-runs'),{type:'bar',
    data:{labels:o.per_run.map((_,i)=>'第'+(i+1)+'回'),
      datasets:[{label:'全体出現率',data:o.per_run,backgroundColor:C.accent}]},
    options:{scales:{y:{beginAtZero:true,max:100,ticks:{callback:v=>v+'%'}}}}});

  const ms=t.model_stats||{}; const names=Object.keys(ms);
  destroy('tmodel');
  charts.tmodel=new Chart(document.getElementById('chart-tmodel'),{type:'bar',
    data:{labels:names,datasets:[{label:'平均出現率',data:names.map(n=>ms[n].mean),
      backgroundColor:names.map((_,i)=>PALETTE[i%PALETTE.length])}]},
    options:{plugins:{tooltip:{callbacks:{afterLabel:(c)=>'SD ±'+ms[names[c.dataIndex]].sd+'pt'}}},
      scales:{y:{beginAtZero:true,max:100,ticks:{callback:v=>v+'%'}}}}});

  drawBar('ttier', t.tier_stats, ['D1','D2','D3','D4'],
          {D1:'D1 指名',D2:'D2 業種・実績',D3:'D3 高特異度・非指名',D4:'D4 一般需要'},
          'ttier-empty','特異度ティア別は、Set2（または両方）を実行すると表示されます。');
  drawBar('tset', t.set_stats, ['set1','set2'],
          {set1:'Set1 理想ターゲット78問',set2:'Set2 診断用60問'},
          'tset-empty','質問セット別は、実行後に表示されます。');

  const ub=document.querySelector('#unstable tbody');
  ub.innerHTML=(st.unstable_list||[]).map(u=>
    `<tr><td>${u.question_id}</td><td>${u.model_name}</td><td>${u.domain_label||''}</td><td>${u.hits}/${u.runs}回</td><td class="muted">${u.question||''}</td></tr>`).join('')
    || '<tr><td colspan="5" class="muted">ブレは検出されませんでした。</td></tr>';
  document.getElementById('stability-note').textContent = st.note || '';
}

/* ---------- Set比較・崖の分析 ★v8 ---------- */
function renderSetCompare(){
  const timings=DATA.timings||{};
  const ids=Object.keys(timings).sort();
  // 最新で tier_stats（特異度ティア）を持つタイミングを採用
  let t=null;
  for(let i=ids.length-1;i>=0;i--){
    const x=timings[ids[i]];
    if(x && x.tier_stats && Object.keys(x.tier_stats).length){ t=x; break; }
  }
  const cv=document.getElementById('chart-curve');
  const curveEmpty=document.getElementById('curve-empty');
  const summ=document.getElementById('sc-summary');
  const interp=document.getElementById('sc-interp');
  const actions=document.getElementById('sc-actions');
  const tb=document.querySelector('#sc-table tbody');
  if(!t){
    if(cv) cv.style.display='none';
    if(curveEmpty) curveEmpty.textContent='Set2（特異度ティア付き）を実行すると、崖の分析が表示されます。';
    summ.innerHTML=''; interp.innerHTML=''; actions.innerHTML='';
    tb.innerHTML='<tr><td colspan="4" class="muted">Set1／Set2を実行すると表示されます。</td></tr>';
    return;
  }
  if(cv) cv.style.display=''; if(curveEmpty) curveEmpty.textContent='';
  const order=['D1','D2','D3','D4'];
  const nameMap={D1:'D1 指名',D2:'D2 業種・実績',D3:'D3 高特異度・非指名',D4:'D4 一般需要'};
  const ts=t.tier_stats||{};
  const present=order.filter(k=>k in ts);
  const vals=present.map(k=>ts[k].mean);
  // 崖ティア＝出現率が10%未満に落ちる最初のティア
  let cliff=null;
  for(const k of present){ if(ts[k].mean<10.0){ cliff=k; break; } }
  const idx=cliff?present.indexOf(cliff):-1;
  const prevTier=(cliff&&idx>0)?present[idx-1]:null;
  const set1mean=(t.set_stats&&t.set_stats.set1)?t.set_stats.set1.mean:null;
  const set2mean=(t.set_stats&&t.set_stats.set2)?t.set_stats.set2.mean:null;

  // グラフ：棒（崖ティアを赤で「崖」を明示）＋折れ線＋Set1平均の点線基準
  destroy('curve');
  const barColors=present.map(k=>(cliff&&k===cliff)?'rgba(248,113,113,.85)':'rgba(56,189,248,.75)');
  const datasets=[
    {type:'bar',label:'Set2 出現率',data:vals,backgroundColor:barColors,order:2},
    {type:'line',label:'特異度カーブ',data:vals,borderColor:C.accent,backgroundColor:C.accent,tension:.2,pointRadius:4,order:1,fill:false},
  ];
  if(set1mean!==null){
    datasets.push({type:'line',label:'Set1平均（D4相当の基準線）',data:present.map(()=>set1mean),
      borderColor:C.warn,borderDash:[6,4],pointRadius:0,order:0,fill:false});
  }
  charts.curve=new Chart(cv,{data:{labels:present.map(k=>nameMap[k]),datasets},
    options:{plugins:{tooltip:{callbacks:{afterLabel:(c)=> c.datasetIndex===0? 'SD ±'+ts[present[c.dataIndex]].sd+'pt':''}}},
      scales:{y:{beginAtZero:true,max:100,ticks:{callback:v=>v+'%'}}}}});

  // サマリー（崖の位置バッジ）
  const cliffLabel = cliff? (cliff==='D1'?'D1（指名）で既に弱い':`${prevTier}→${cliff}`) : 'なし（全ティアで出現）';
  summ.className='summary '+(cliff?'bad':'good');
  summ.innerHTML=`崖の位置：<span class="badge-cliff">${cliffLabel}</span>　`+
    present.map(k=>`${k} ${ts[k].mean}%`).join(' ／ ');

  // 解釈文
  let interpText;
  if(cliff&&cliff!=='D1'){
    interpText=`<div class="lead">崖は ${prevTier}→${cliff}。</div>`+
      `指名（${prevTier}）では${ts[prevTier].mean}%出るが、業種・実績を問う${cliff}以下では${ts[cliff].mean}%に落ちます。`+
      `埋めるべきギャップは <b>${cliff}（業種特化・実績）</b>。該当業種の実績ページの権威性・被引用の強化が優先です。`;
  } else if(cliff==='D1'){
    interpText=`<div class="lead">指名（D1）でも出現が弱い（${ts.D1.mean}%）。</div>`+
      `AIの学習記憶に当社情報が薄い可能性。まず社名・ブランド名での基本情報整備と、グラウンディング型モデルでの再測定を検討します。`;
  } else {
    interpText=`<div class="lead">明確な崖は検出されていません。</div>`+
      `非指名でも出現が確認できており、勝てる非指名クエリの拡大余地があります。有効ページの横展開を推奨。`;
  }
  interp.className='interp'; interp.innerHTML=interpText;

  // 次アクション（崖の位置で出し分け）
  let acts;
  if(cliff&&cliff!=='D1'){
    acts=['D2で問うている業種（航空・鉄道・建設・大学病院・映画館 等）の実績ページを、社名・ブランド名と業種名がセットで書かれた形に強化',
          '事例ページに構造化データ（会社名・実績）を付与',
          '再測定でD2が0%→数%に動くかを確認'];
  } else if(cliff==='D1'){
    acts=['社名・ブランド名での会社概要・実績ページを整備し、AIが参照しやすい形にする',
          'グラウンディング型モデル（Perplexity等）でD1の想起・正確性を再測定',
          'D1が安定して出るようになってからD2以下の強化に進む'];
  } else {
    acts=['出現している非指名クエリの有効ページを他ドメイン・他業種へ横展開',
          'D3/D4で勝てているテーマの被引用元を分析し、勝ち筋を再現'];
  }
  actions.innerHTML='<h2 style="border:none;margin:16px 0 6px;padding:0">次アクション</h2>'+
    '<ol class="actions">'+acts.map(a=>`<li>${a}</li>`).join('')+'</ol>';

  // Set1×Set2 サマリー表
  const rows=[
    ['全体出現率', set1mean!==null?set1mean+'%':'—', set2mean!==null?set2mean+'%':'—', '母集団に対する当社言及率'],
    ['出現の中心', '指名質問が中心', cliff?'指名（D1）中心':'複数ティアで出現', '実際にヒットしている具体度'],
    ['読み取り', '一般需要では未出現', cliff?`崖 = ${cliffLabel}`:'崖なし',
     'Set1＝出したいが出ない質問／Set2＝どこから消えるかを測る診断'],
  ];
  tb.innerHTML=rows.map(r=>`<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td class="muted">${r[3]}</td></tr>`).join('');
}

/* ---------- タブ ---------- */
document.querySelectorAll('.tab').forEach(tab=>{
  tab.onclick=()=>{
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
    tab.classList.add('active');
    const t=tab.dataset.t;
    document.getElementById('tab-trend').classList.toggle('hidden',t!=='trend');
    document.getElementById('tab-timing').classList.toggle('hidden',t!=='timing');
    document.getElementById('tab-setcompare').classList.toggle('hidden',t!=='setcompare');
    // 非表示中に生成したグラフはサイズ0になり得るため、表示時に再描画 ★v8
    if(t==='setcompare') renderSetCompare();
    if(t==='timing'){ const sel=document.getElementById('timing-select'); if(sel&&sel.value) renderTiming(sel.value); }
  };
});
renderTrend();
renderTimingSelector();
renderSetCompare();
</script>
</body>
</html>"""
