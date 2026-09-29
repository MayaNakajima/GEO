// Google 検索チェック用ブックマークレット（google_check.bookmarklet() が javascript: URL に変換する）
// ・Google の検索結果ページで実行すると、上位10件の表示ドメイン・タイトルと、AI による概要の有無・引用元を抜き出し、
//   定点観測 GUI（__RECEIVER__）へ移動して記録する。検索そのものはしない（人が検索した画面を読むだけ）。
// ・1行ずつ連結して使うため、各文は必ず ; で終える。行頭が // の行はコメントとして除去される。
(function(){
var q = new URLSearchParams(location.search).get("q");
if (!/(^|\.)google\.[a-z.]+$/.test(location.hostname) || !q) { alert("Google の検索結果ページで実行してください"); return; }
var txt = function(e){ return ((e && (e.innerText || e.textContent)) || "").replace(/\s+/g, " ").trim(); };
var real = function(a){ var h = a.getAttribute("href") || ""; return (/^https?:/.test(h) && !/(^|\.)google\./.test(new URL(h).hostname)) ? h : ""; };
var head = Array.prototype.find.call(document.querySelectorAll("h1,h2,[role=heading]"), function(e){ return /^(AI による概要|AI Overview)/.test(txt(e)); });
var aioBox = null;
if (head) {
  aioBox = head;
  var hasOther = function(p){ return Array.prototype.some.call(p.querySelectorAll("a h3"), function(h){ return !aioBox.contains(h); }); };
  while (aioBox.parentElement && aioBox.parentElement !== document.body && !hasOther(aioBox.parentElement)) { aioBox = aioBox.parentElement; }
}
var results = [], seen = {};
Array.prototype.forEach.call(document.querySelectorAll("#rso a h3, #search a h3"), function(h){
  if (results.length >= 10) { return; }
  var a = h.closest("a");
  if (!a || seen[a.getAttribute("href")]) { return; }
  if (a.closest("#tads,#bottomads,[data-text-ad],.related-question-pair,[data-initq]")) { return; }
  if (aioBox && aioBox.contains(a)) { return; }
  seen[a.getAttribute("href")] = 1;
  var box = a.closest("[data-hveid]") || a.parentElement;
  var cite = a.querySelector("cite") || (box && box.querySelector("cite"));
  var u = real(a);
  results.push({ host: u ? new URL(u).hostname : txt(cite).split("›")[0].trim(), title: txt(h).slice(0, 120), url: u });
});
var links = [];
if (aioBox) {
  Array.prototype.forEach.call(aioBox.querySelectorAll("a[href]"), function(a){
    var t = txt(a) || a.getAttribute("aria-label") || "";
    var u = real(a);
    var host = u ? new URL(u).hostname : (/^[a-z0-9-]+(\.[a-z0-9-]+)+$/i.test(t) ? t.toLowerCase() : "");
    if (host && !/(^|\.)google\./.test(host)) { links.push({ host: host, title: "" }); }
  });
}
var data = { q: q, results: results, aio: { present: !!head, links: links }, page: location.href.slice(0, 300), ts: new Date().toISOString() };
var json = JSON.stringify(data);
try { if (navigator.clipboard) { navigator.clipboard.writeText(json).catch(function(){}); } } catch (e) {}
location.href = "__RECEIVER__#" + encodeURIComponent(json);
})();
