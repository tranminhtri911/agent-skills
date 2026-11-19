"""Style, scripts and interface labels for the evidence checklist and report pages (see evidence.py).

The pages are self-contained (no network): one stylesheet, one script, data embedded as JSON.
Interface text exists in Vietnamese, English and Japanese; `body[data-lang]` shows one language.
"""

from __future__ import annotations

# Interface labels rendered server-side as <span class="vi|en|ja">; the case content comes from checklist.json.
UI_LABELS: dict[str, dict[str, str]] = {
    "expand_all": {"vi": "Mở hết", "en": "Expand all", "ja": "すべて開く"},
    "collapse_all": {"vi": "Thu gọn", "en": "Collapse all", "ja": "すべて閉じる"},
    "reset": {"vi": "Xoá tick", "en": "Reset ticks", "ja": "チェックをリセット"},
    "preparation": {"vi": "Chuẩn bị", "en": "Preparation", "ja": "事前準備"},
    "environment": {"vi": "Môi trường", "en": "Environment", "ja": "環境"},
    "evidence_folder": {"vi": "Thư mục evidence", "en": "Evidence folder", "ja": "エビデンスフォルダ"},
    "preconditions": {"vi": "Điều kiện trước", "en": "Preconditions", "ja": "前提条件"},
    "test_data": {"vi": "Dữ liệu test", "en": "Test data", "ja": "テストデータ"},
    "action": {"vi": "Thao tác", "en": "Action", "ja": "操作"},
    "data": {"vi": "Dữ liệu nhập", "en": "Input data", "ja": "入力データ"},
    "expected": {"vi": "Kết quả mong đợi", "en": "Expected result", "ja": "期待結果"},
    "report": {"vi": "Báo cáo kết quả test", "en": "Test result report", "ja": "テスト結果レポート"},
    "verdict": {"vi": "Đánh giá", "en": "Verdict", "ja": "判定"},
    "cases": {"vi": "case", "en": "cases", "ja": "ケース"},
    "images": {"vi": "ảnh", "en": "images", "ja": "画像"},
    "tested_at": {"vi": "Ngày test", "en": "Tested", "ja": "実施日"},
    "tester": {"vi": "Người test", "en": "Tester", "ja": "実施者"},
    "no_summary": {"vi": "chưa có summary", "en": "no summary yet", "ja": "サマリー未作成"},
    "overview": {"vi": "Tổng quan: kết quả từng case", "en": "Overview: result of every case", "ja": "概要: ケースごとの結果"},
    "case_details": {"vi": "Chi tiết từng case", "en": "Case details", "ja": "ケース詳細"},
    "title": {"vi": "Tên case", "en": "Case", "ja": "ケース名"},
    "steps_passed": {"vi": "Step đạt", "en": "Steps passed", "ja": "合格手順"},
    "reason": {"vi": "Lý do / ghi chú", "en": "Reason / note", "ja": "理由・備考"},
    "links": {"vi": "Liên kết", "en": "Links", "ja": "リンク"},
    "details": {"vi": "chi tiết", "en": "details", "ja": "詳細"},
    "folder": {"vi": "thư mục", "en": "folder", "ja": "フォルダ"},
    "steps": {"vi": "Các step", "en": "Steps", "ja": "手順"},
    "observed": {"vi": "Thực tế (từ ảnh)", "en": "Observed (screenshot)", "ja": "実際の結果（画像）"},
    "no_record": {"vi": "chưa ghi nhận trong summary", "en": "not recorded in the summary", "ja": "サマリーに記録なし"},
    "conclusion": {"vi": "Kết luận", "en": "Conclusion", "ja": "結論"},
    "other_images": {"vi": "Ảnh bổ sung (điều kiện trước, extra)", "en": "Other screenshots (preconditions, extra)",
                     "ja": "その他の画像（前提条件・追加）"},
    "summary_info": {"vi": "Thông tin", "en": "Information", "ja": "情報"},
    "unlisted": {"vi": "Thư mục không thuộc checklist (không tính vào kết quả)",
                 "en": "Folders outside the checklist (not counted)", "ja": "チェックリスト外のフォルダ（集計対象外）"},
    "generated": {"vi": "tạo lúc", "en": "generated", "ja": "作成"},
}

PAGE_STYLE = r"""
:root{--bg:#f6f7f9;--card:#fff;--ink:#1f2933;--muted:#6b7785;--line:#e3e7ec;--accent:#3b5bdb;--code:#f1f3f6;
--ok:#1b7f3b;--ok-bg:#e8f6ec;--ng:#c62828;--ng-bg:#fdecea;--part:#a15c00;--part-bg:#fff4e0;--idle:#9aa5b1}
@media (prefers-color-scheme: dark){:root{--bg:#14171c;--card:#1c2027;--ink:#e6e9ee;--muted:#93a0ae;--line:#2b313a;
--accent:#8ea2ff;--code:#242a33;--ok:#7ddc98;--ok-bg:#17301f;--ng:#ff8a80;--ng-bg:#3a1d1b;--part:#ffcc80;--part-bg:#3a2e17;--idle:#5b6672}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.5 -apple-system,"Hiragino Sans","Noto Sans JP",Segoe UI,Roboto,sans-serif}
body[data-lang="vi"] .en,body[data-lang="vi"] .ja,body[data-lang="en"] .vi,body[data-lang="en"] .ja,
body[data-lang="ja"] .vi,body[data-lang="ja"] .en{display:none!important}
a{color:var(--accent)} code{background:var(--code);padding:0 5px;border-radius:4px}
.side{position:fixed;top:0;left:0;bottom:0;width:270px;overflow:auto;background:var(--card);border-right:1px solid var(--line);padding:10px;z-index:20}
.side-head{margin-bottom:6px} .muted{color:var(--muted);font-size:12px}
.search{width:100%;font:inherit;padding:4px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);margin:4px 0}
.side-totals{font-size:12px;color:var(--muted);margin:4px 0 8px}
.menu{list-style:none;margin:0;padding:0} .menu li a{display:block;padding:3px 6px;border-radius:6px;color:var(--ink);text-decoration:none;font-size:12.5px}
.menu li a:hover,.menu li.current a{background:var(--code)} .menu li.hidden{display:none}
.menu .page-head{font-size:11px;color:var(--muted);margin:8px 0 2px;text-transform:uppercase;letter-spacing:.04em;cursor:pointer}
.main{margin-left:270px;padding:0 16px 40px;max-width:1240px} .main.wide{margin-left:0;margin:0 auto}
h1{font-size:19px;margin:8px 0 2px} h4{font-size:12.5px;margin:8px 0 2px;color:var(--muted)} .sub{color:var(--muted);margin:0 0 8px}
.toolbar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;position:sticky;top:0;background:var(--bg);padding:8px 0;z-index:10;border-bottom:1px solid var(--line)}
.toolbar button,.pager button{font:inherit;font-size:12px;padding:3px 10px;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;cursor:pointer}
.toolbar button.on{background:var(--accent);border-color:var(--accent);color:#fff} .toolbar .sep{flex:1}
.progress{font-size:12px;color:var(--muted)} .menu-toggle{display:none}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:8px 0}
.card>summary{cursor:pointer} ol,ul{margin:2px 0 2px 18px;padding:0}
table{width:100%;border-collapse:collapse;margin:4px 0} th,td{border:1px solid var(--line);padding:3px 6px;vertical-align:top;text-align:left}
th{background:var(--code);font-size:12px;color:var(--muted);font-weight:600} table.meta th,table.data th{width:180px}
.case{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:8px;padding:0 10px 8px;margin:8px 0}
.case>summary{cursor:pointer;padding:7px 0;display:flex;gap:8px;align-items:center;list-style:none}
.case>summary::-webkit-details-marker{display:none} .case>summary::before{content:'▸';color:var(--muted)} .case[open]>summary::before{content:'▾'}
.cid{color:var(--accent);white-space:nowrap} .ctitle{flex:1;font-weight:600} .cstat{font-size:12px;color:var(--muted);white-space:nowrap}
.purpose{color:var(--muted);margin:0 0 4px} .folder{font-size:12px;margin:0 0 4px}
td.n{width:64px;white-space:nowrap;font-weight:700} td.n input{margin-right:4px} tr.done td{background:var(--ok-bg)}
.exp{color:var(--ok)} pre{margin:2px 0;padding:3px 8px;border-radius:5px;background:var(--code);font:12px/1.5 ui-monospace,Menlo,monospace;white-space:pre-wrap;color:var(--ink)}
.note{margin:4px 0;padding:3px 8px;border-radius:5px;background:var(--part-bg);color:var(--part);font-size:12px}
.res{display:flex;gap:12px;align-items:center;margin-top:6px;padding-top:6px;border-top:1px dashed var(--line);flex-wrap:wrap}
.res label{cursor:pointer;font-weight:700} .res .ok{color:var(--ok)} .res .ng{color:var(--ng)}
.memo{flex:1;min-width:160px;font:inherit;padding:2px 6px;border:1px solid var(--line);border-radius:5px;background:var(--bg);color:var(--ink)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--idle);flex:none;margin-right:4px}
.dot.s-ok,.dot.r-ok{background:var(--ok)} .dot.s-ng,.dot.r-ng{background:var(--ng)} .dot.s-part,.dot.r-partial{background:var(--part)}
.dot.r-blocked{background:var(--ng);opacity:.55} .dot.r-not_run{background:var(--idle)}
.pill{font-size:11.5px;font-weight:700;padding:1px 9px;border-radius:999px;background:var(--code);white-space:nowrap}
.pill.r-ok{background:var(--ok-bg);color:var(--ok)} .pill.r-ng,.pill.r-blocked{background:var(--ng-bg);color:var(--ng)}
.pill.r-partial,.pill.r-incomplete{background:var(--part-bg);color:var(--part)}
.verdict{font-size:15px;margin:6px 0;padding:6px 12px;border-radius:8px;background:var(--code)}
.verdict.r-ok{background:var(--ok-bg);color:var(--ok)} .verdict.r-ng{background:var(--ng-bg);color:var(--ng)}
.verdict.r-partial,.verdict.r-incomplete{background:var(--part-bg);color:var(--part)}
.kpis{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0} .kpi{border:1px solid var(--line);border-radius:8px;padding:4px 12px;background:var(--card);font-size:12px}
.kpi b{display:block;font-size:18px} .kpi.r-ok b{color:var(--ok)} .kpi.r-ng b{color:var(--ng)} .kpi.r-partial b{color:var(--part)}
.page-totals{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;margin:8px 0;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card)}
.page-totals b{color:var(--ink)} .pager{display:flex;gap:8px;align-items:center;justify-content:center;margin:8px 0;font-size:12px}
.pager.single{display:none} .meta-line{font-size:12px;color:var(--muted);margin:2px 0 6px}
.summary-md table.md{font-size:12px} .summary-md h3,.summary-md h4,.summary-md h5{margin:8px 0 2px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin-top:8px}
figure{margin:0;border:1px solid var(--line);border-radius:8px;background:var(--card);padding:5px}
figure img{width:100%;height:auto;border-radius:4px;display:block} figcaption{font-size:11px;color:var(--muted);margin-top:3px;word-break:break-all}
h2{font-size:15px;margin:16px 0 6px}
table.overview td,table.overview th{font-size:12.5px} table.overview td.nowrap{white-space:nowrap}
table.overview tr.group th{background:var(--card);color:var(--ink);font-size:13px;padding-top:8px}
.case.r-ng{border-left-color:var(--ng)} .case.r-ok{border-left-color:var(--ok)} .case.r-partial{border-left-color:var(--part)}
.case.r-blocked,.case.r-not_run{border-left-color:var(--idle)}
.reason{margin:6px 0;padding:6px 10px;border-radius:6px;background:var(--part-bg);color:var(--part)}
.reason.r-ng,.reason.r-blocked{background:var(--ng-bg);color:var(--ng)}
.conclusion{margin:6px 0;padding:6px 10px;border-radius:6px;background:var(--code)} .conclusion p{margin:2px 0}
.step{border:1px solid var(--line);border-left:4px solid var(--idle);border-radius:8px;padding:6px 10px;margin:8px 0;background:var(--bg)}
.step.s-pass{border-left-color:var(--ok)} .step.s-ng{border-left-color:var(--ng)} .step.s-no_evidence{border-left-color:var(--part)}
.step-head{display:flex;gap:8px;align-items:center;margin-bottom:4px} .step-head input{transform:scale(1.15)}
.step dl{display:grid;grid-template-columns:150px 1fr;gap:3px 10px;margin:0}
.step dt{color:var(--muted);font-size:12px;font-weight:600} .step dd{margin:0;white-space:normal;overflow-wrap:anywhere}
.pill.r-pass{background:var(--ok-bg);color:var(--ok)} .pill.r-no_evidence{background:var(--part-bg);color:var(--part)}
.pill.r-not_run{background:var(--code);color:var(--muted)}
@media (max-width:800px){.step dl{grid-template-columns:1fr}}
@media (max-width:800px){.side{transform:translateX(-100%);transition:transform .15s;box-shadow:0 0 20px rgba(0,0,0,.2)}
body.menu-open .side{transform:none} .main{margin-left:0;padding:0 10px 40px} .menu-toggle{display:inline-block}
table.meta th,table.data th{width:auto}}
@media print{.side,.toolbar,.pager{display:none} .main{margin:0} .case{break-inside:avoid}}
"""

# Shared by both pages: language, menu, pages with totals, search, expand/collapse. Each page adds its own totals.
_COMMON_SCRIPT = r"""
var DATA = (function(){ var el = document.getElementById('checklist-data'); try { return el ? JSON.parse(el.textContent) : {cases: []}; } catch (e) { return {cases: []}; } })();
var LANG_KEY = 'devskills-evidence-lang';
var WORDS = {
  page: {vi: 'Trang', en: 'Page', ja: 'ページ'}, cases: {vi: 'case', en: 'cases', ja: 'ケース'},
  steps: {vi: 'step đã tick', en: 'steps ticked', ja: 'チェック済み手順'}, untested: {vi: 'chưa test', en: 'not tested', ja: '未実施'},
  pageTotal: {vi: 'Tổng trang này', en: 'This page', ja: 'このページ'}, all: {vi: 'Tất cả', en: 'All', ja: '全体'}
};
function store(key, value){ try { if (value === undefined) { return localStorage.getItem(key); } localStorage.setItem(key, value); } catch (e) { return null; } }
function lang(){ return document.body.getAttribute('data-lang') || 'vi'; }
function word(key){ return WORDS[key][lang()] || WORDS[key].en; }
var pageCount = 1; DATA.cases.forEach(function(c){ if (c.page > pageCount) { pageCount = c.page; } });
var currentPage = 1;
function caseBlocks(){ return Array.prototype.slice.call(document.querySelectorAll('details.case')); }
function showPage(page){
  currentPage = Math.max(1, Math.min(pageCount, page));
  caseBlocks().forEach(function(d){ d.style.display = (+d.getAttribute('data-page') === currentPage) ? '' : 'none'; });
  document.querySelectorAll('.menu li[data-page]').forEach(function(li){ li.classList.toggle('current', +li.getAttribute('data-page') === currentPage); });
  document.querySelectorAll('[data-pager]').forEach(function(p){
    p.classList.toggle('single', pageCount < 2);
    p.querySelector('[data-page-label]').textContent = word('page') + ' ' + currentPage + ' / ' + pageCount;
  });
  refresh();
}
function setLang(code){
  document.body.setAttribute('data-lang', code); document.documentElement.setAttribute('lang', code);
  document.querySelectorAll('[data-set-lang]').forEach(function(b){ b.classList.toggle('on', b.getAttribute('data-set-lang') === code); });
  store(LANG_KEY, code); buildMenuHeads(); showPage(currentPage);
}
function buildMenuHeads(){
  document.querySelectorAll('.menu .page-head').forEach(function(h){ h.remove(); });
  if (pageCount < 2) { return; }
  var seen = {};
  document.querySelectorAll('.menu li[data-page]').forEach(function(li){
    var page = +li.getAttribute('data-page');
    if (seen[page]) { return; }
    seen[page] = true;
    var head = document.createElement('li'); head.className = 'page-head'; head.textContent = word('page') + ' ' + page;
    head.addEventListener('click', function(){ showPage(page); });
    li.parentNode.insertBefore(head, li);
  });
}
function openCase(id){
  var block = document.getElementById('case-' + id);
  if (!block) { return; }
  showPage(+block.getAttribute('data-page')); block.open = true; block.scrollIntoView({block: 'start'});
  document.body.classList.remove('menu-open');
}
document.querySelectorAll('[data-set-lang]').forEach(function(b){ b.addEventListener('click', function(){ setLang(b.getAttribute('data-set-lang')); }); });
document.querySelectorAll('[data-case-link]').forEach(function(a){ a.addEventListener('click', function(ev){ ev.preventDefault(); openCase(a.getAttribute('data-case-link')); history.replaceState(null, '', '#case-' + a.getAttribute('data-case-link')); }); });
document.querySelectorAll('[data-page-prev]').forEach(function(b){ b.addEventListener('click', function(){ showPage(currentPage - 1); window.scrollTo(0, 0); }); });
document.querySelectorAll('[data-page-next]').forEach(function(b){ b.addEventListener('click', function(){ showPage(currentPage + 1); window.scrollTo(0, 0); }); });
var expandButton = document.getElementById('expandAll'), collapseButton = document.getElementById('collapseAll');
if (expandButton) { expandButton.addEventListener('click', function(){ caseBlocks().forEach(function(d){ if (d.style.display !== 'none') { d.open = true; } }); }); }
if (collapseButton) { collapseButton.addEventListener('click', function(){ caseBlocks().forEach(function(d){ d.open = false; }); }); }
var menuToggle = document.getElementById('menuToggle');
if (menuToggle) { menuToggle.addEventListener('click', function(){ document.body.classList.toggle('menu-open'); }); }
var search = document.getElementById('caseSearch');
if (search) { search.addEventListener('input', function(){
  var needle = search.value.trim().toLowerCase();
  document.querySelectorAll('.menu li[data-page]').forEach(function(li){ li.classList.toggle('hidden', !!needle && li.textContent.toLowerCase().indexOf(needle) < 0); });
}); }
"""

_COMMON_START = r"""
(function(){
  var saved = store(LANG_KEY);
  var initial = (saved === 'en' || saved === 'ja') ? saved : 'vi';
  document.body.setAttribute('data-lang', initial);
  setLang(initial);
  var hash = decodeURIComponent((location.hash || '').replace(/^#case-/, ''));
  if (hash) { openCase(hash); }
})();
"""

CHECKLIST_SCRIPT = _COMMON_SCRIPT + r"""
var STATE_KEY = 'devskills-checklist:' + (DATA.task || '');
var state = (function(){ try { return JSON.parse(store(STATE_KEY) || '{}') || {}; } catch (e) { return {}; } })();
state.steps = state.steps || {}; state.result = state.result || {}; state.memo = state.memo || {};
function save(){ store(STATE_KEY, JSON.stringify(state)); }
function caseStats(id){
  var boxes = document.querySelectorAll('[data-step^="' + id + '-s"]');
  var done = 0; boxes.forEach(function(b){ if (b.checked) { done += 1; } });
  return {done: done, total: boxes.length, result: state.result[id] || ''};
}
function totalsFor(cases){
  var t = {cases: cases.length, done: 0, steps: 0, ok: 0, ng: 0, untested: 0};
  cases.forEach(function(c){ var s = caseStats(c.id); t.done += s.done; t.steps += s.total;
    if (s.result === 'OK') { t.ok += 1; } else if (s.result === 'NG') { t.ng += 1; } else { t.untested += 1; } });
  return t;
}
function totalsText(t){ return t.cases + ' ' + word('cases') + ' · ' + word('steps') + ' ' + t.done + '/' + t.steps + ' · OK ' + t.ok + ' · NG ' + t.ng + ' · ' + word('untested') + ' ' + t.untested; }
function refresh(){
  DATA.cases.forEach(function(c){
    var s = caseStats(c.id);
    var css = s.result === 'OK' ? 's-ok' : (s.result === 'NG' ? 's-ng' : (s.done ? 's-part' : ''));
    document.querySelectorAll('[data-dot="' + c.id + '"]').forEach(function(dot){ dot.className = 'dot ' + css; });
    var label = document.querySelector('[data-case-progress="' + c.id + '"]');
    if (label) { label.textContent = s.done + '/' + s.total + (s.result ? ' · ' + s.result : ''); }
  });
  var onPage = DATA.cases.filter(function(c){ return c.page === currentPage; });
  var pageTotals = document.getElementById('pageTotals');
  if (pageTotals) { pageTotals.innerHTML = '<span><b>' + word('pageTotal') + ' (' + word('page') + ' ' + currentPage + '):</b> ' + totalsText(totalsFor(onPage)) + '</span>'
    + (pageCount > 1 ? '<span><b>' + word('all') + ':</b> ' + totalsText(totalsFor(DATA.cases)) + '</span>' : ''); }
  var all = totalsFor(DATA.cases);
  document.getElementById('progress').textContent = 'Steps ' + all.done + '/' + all.steps + ' · OK ' + all.ok + ' · NG ' + all.ng;
  var side = document.getElementById('sideTotals'); if (side) { side.textContent = totalsText(all); }
}
document.querySelectorAll('[data-step]').forEach(function(box){
  var id = box.getAttribute('data-step'); box.checked = !!state.steps[id];
  box.closest('tr').classList.toggle('done', box.checked);
  box.addEventListener('change', function(){ state.steps[id] = box.checked; box.closest('tr').classList.toggle('done', box.checked); save(); refresh(); });
});
document.querySelectorAll('[data-result]').forEach(function(box){
  var id = box.getAttribute('data-result'); box.checked = state.result[id] === box.value;
  box.addEventListener('change', function(){
    document.querySelectorAll('[data-result="' + id + '"]').forEach(function(other){ if (other !== box) { other.checked = false; } });
    state.result[id] = box.checked ? box.value : ''; save(); refresh();
  });
});
document.querySelectorAll('[data-memo]').forEach(function(input){
  var id = input.getAttribute('data-memo'); input.value = state.memo[id] || '';
  input.addEventListener('input', function(){ state.memo[id] = input.value; save(); });
});
var resetButton = document.getElementById('resetChecks');
if (resetButton) { resetButton.addEventListener('click', function(){
  state = {steps: {}, result: {}, memo: {}}; save();
  document.querySelectorAll('[data-step],[data-result]').forEach(function(b){ b.checked = false; var row = b.closest('tr'); if (row) { row.classList.remove('done'); } });
  document.querySelectorAll('[data-memo]').forEach(function(i){ i.value = ''; }); refresh();
}); }
""" + _COMMON_START

REPORT_SCRIPT = _COMMON_SCRIPT + r"""
function refresh(){
  if (!DATA.cases.length) { return; }
  var onPage = DATA.cases.filter(function(c){ return c.page === currentPage; });
  function count(list){ var t = {OK: 0, NG: 0, PARTIAL: 0, BLOCKED: 0, NOT_RUN: 0}; list.forEach(function(c){ t[c.result] = (t[c.result] || 0) + 1; }); return t; }
  function text(list){ var t = count(list); return list.length + ' ' + word('cases') + ' · OK ' + t.OK + ' · NG ' + t.NG + ' · PARTIAL ' + t.PARTIAL + ' · BLOCKED ' + t.BLOCKED + ' · NOT RUN ' + t.NOT_RUN; }
  var pageTotals = document.getElementById('pageTotals');
  if (pageTotals) { pageTotals.innerHTML = '<span><b>' + word('pageTotal') + ' (' + word('page') + ' ' + currentPage + '):</b> ' + text(onPage) + '</span>'
    + (pageCount > 1 ? '<span><b>' + word('all') + ':</b> ' + text(DATA.cases) + '</span>' : ''); }
  var progress = document.getElementById('progress'); if (progress) { progress.textContent = text(DATA.cases); }
}
""" + _COMMON_START
