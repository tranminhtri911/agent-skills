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
    # plan.html (task-spec)
    "block_overview": {"vi": "Tổng quan", "en": "Overview", "ja": "概要"},
    "block_current_flow": {"vi": "Flow hiện tại", "en": "Current flow", "ja": "現在のフロー"},
    "block_target_flow": {"vi": "Flow sau khi triển khai", "en": "Flow after the change", "ja": "対応後のフロー"},
    "block_changes": {"vi": "Cách sửa chi tiết", "en": "Changes in detail", "ja": "修正内容の詳細"},
    "block_impact": {"vi": "Ảnh hưởng tới logic / source hiện tại", "en": "Impact on current logic and source",
                     "ja": "既存ロジック・ソースへの影響"},
    "block_subtasks": {"vi": "Chia task nhỏ", "en": "Sub tasks", "ja": "サブタスク"},
    "block_verify": {"vi": "Cách verify", "en": "How to verify", "ja": "検証方法"},
    "block_test": {"vi": "Cách test (unit, E2E, thủ công)", "en": "Tests (unit, E2E, manual)", "ja": "テスト（単体・E2E・手動）"},
    "block_risks": {"vi": "Rủi ro và cách xử lý", "en": "Risks and mitigations", "ja": "リスクと対策"},
    "block_confirm": {"vi": "Vấn đề cần confirm", "en": "Questions to confirm", "ja": "要確認事項"},
    "block_estimate": {"vi": "Estimate", "en": "Estimate", "ja": "見積もり"},
    "block_deploy": {"vi": "Cách deploy", "en": "Deployment", "ja": "リリース手順"},
    "title_task": {"vi": "Nội dung", "en": "Task", "ja": "内容"},
    "estimate": {"vi": "Estimate", "en": "Estimate", "ja": "見積もり"},
    "depends_on": {"vi": "Phụ thuộc", "en": "Depends on", "ja": "依存"},
    "file": {"vi": "File", "en": "File", "ja": "ファイル"},
    "total": {"vi": "Tổng", "en": "Total", "ja": "合計"},
    "days": {"vi": "ngày công (8h/ngày)", "en": "person-days (8h)", "ja": "人日（8h/日）"},
    "requirement": {"vi": "Yêu cầu gốc", "en": "Requirement", "ja": "要求（原文）"},
    "open_questions": {"vi": "Cần confirm", "en": "Open questions", "ja": "未確認"},
    "checklist": {"vi": "Checklist", "en": "Checklist", "ja": "チェックリスト"},
    "show_all": {"vi": "Xem tất cả", "en": "Show all", "ja": "すべて表示"},
    "rules": {"vi": "Quy tắc cần kiểm tra", "en": "Rule under test", "ja": "確認するルール"},
    "steps_ticked": {"vi": "Step đã tick", "en": "Steps ticked", "ja": "チェック済み手順"},
    "untested": {"vi": "Chưa test", "en": "Not tested", "ja": "未実施"},
    "result": {"vi": "Kết quả", "en": "Result", "ja": "結果"},
    "status": {"vi": "Trạng thái", "en": "Status", "ja": "状態"},
    "remaining": {"vi": "Còn lại", "en": "Remaining", "ja": "残り"},
    "done": {"vi": "đã xong", "en": "done", "ja": "完了"},
    "not_applicable": {"vi": "Không áp dụng", "en": "Not applicable", "ja": "対象外"},
    "hint_overview": {"vi": "Mục tiêu, yêu cầu gốc ↔ phần của plan, phạm vi.", "en": "Goal, requirement ↔ plan, scope.",
                      "ja": "目的、要求とプランの対応、範囲。"},
    "hint_current_flow": {"vi": "Hệ thống chạy thế nào hôm nay (đọc từ code).", "en": "How it works today (read from the code).",
                          "ja": "現在の動作（コードから）。"},
    "hint_target_flow": {"vi": "Chạy thế nào sau khi sửa; phần mới / thay đổi được tô màu.",
                         "en": "How it works after the change; new and changed parts are coloured.",
                         "ja": "対応後の動作。新規・変更箇所を色分け。"},
    "hint_changes": {"vi": "Sửa gì ở file / module nào, vì sao.", "en": "What changes in which file or module, and why.",
                     "ja": "どのファイル・モジュールを何のために変更するか。"},
    "hint_impact": {"vi": "Logic, source, dữ liệu và chức năng khác bị ảnh hưởng; phần giữ nguyên.",
                    "en": "Logic, source, data and other features affected; what stays the same.",
                    "ja": "影響するロジック・ソース・データ・機能、変わらない部分。"},
    "hint_subtasks": {"vi": "Task nhỏ theo thứ tự làm, mỗi task có estimate và cách test.",
                      "en": "Small tasks in order, each with an estimate and its tests.", "ja": "順番どおりの小タスク、見積もりとテスト付き。"},
    "hint_verify": {"vi": "Reviewer kiểm chứng kết quả thế nào, với giá trị cụ thể.", "en": "How a reviewer proves it, with exact values.",
                    "ja": "レビュー担当者の検証方法（具体値付き）。"},
    "hint_test": {"vi": "Unit, integration, E2E / thủ công theo checklist.", "en": "Unit, integration, E2E / manual by checklist.",
                  "ja": "単体・結合・チェックリストによるE2E/手動。"},
    "hint_risks": {"vi": "Rủi ro, mức độ và cách xử lý.", "en": "Risks, severity and mitigation.", "ja": "リスク、影響度、対策。"},
    "hint_confirm": {"vi": "Câu hỏi cần người quyết định trả lời trước khi làm tiếp.", "en": "Questions an owner must answer.",
                     "ja": "判断が必要な確認事項。"},
    "hint_estimate": {"vi": "Giờ theo từng sub task, tổng và giả định.", "en": "Hours per sub task, total and assumptions.",
                      "ja": "サブタスク別の工数、合計、前提。"},
    "hint_deploy": {"vi": "Các bước release, migration, kiểm tra sau release, rollback.",
                    "en": "Release steps, migrations, post-release checks, rollback.", "ja": "リリース手順、移行、確認、切り戻し。"},
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
  function setText(id, value){ var el = document.getElementById(id); if (el) { el.textContent = value; } }
  setText('statSteps', all.done + '/' + all.steps); setText('statOk', all.ok); setText('statNg', all.ng); setText('statUntested', all.untested);
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


# Extra style of plan.html (task-spec): Swiss-minimal documentation look, navy/blue accents, light and dark.
PLAN_STYLE = r"""
:root{--accent:#2563eb;--navy:#1e3a5f;--bg:#f8fafc;--card:#fff;--ink:#0f172a;--muted:#475569;--line:#e2e8f0;--code:#f1f5f9;
--new:#047857;--new-bg:#ecfdf5;--chg:#b45309;--chg-bg:#fffbeb;--rm:#b91c1c;--rm-bg:#fef2f2;--node:#fff;--edge:#64748b}
@media (prefers-color-scheme: dark){:root{--accent:#60a5fa;--navy:#93c5fd;--bg:#0b1220;--card:#111a2b;--ink:#e2e8f0;--muted:#94a3b8;
--line:#1f2a3d;--code:#16213a;--new:#34d399;--new-bg:#0c2a20;--chg:#fbbf24;--chg-bg:#2b2110;--rm:#f87171;--rm-bg:#2d1414;--node:#16213a;
--edge:#94a3b8}}
body{font:15px/1.65 "IBM Plex Sans",-apple-system,"Hiragino Sans","Noto Sans JP","Segoe UI",Roboto,sans-serif}
.main.plan{max-width:1120px;padding:0 28px 64px}
.side{width:280px;padding:16px 12px} .main{margin-left:280px}
.side-head{display:flex;flex-direction:column;gap:4px;margin-bottom:10px} .side-head b{font-size:14px;line-height:1.4}
.eyebrow{font:600 11px/1.2 ui-monospace,"JetBrains Mono",Menlo,monospace;letter-spacing:.06em;text-transform:uppercase;color:var(--accent)}
.menu li a{display:flex;gap:8px;align-items:baseline;padding:5px 8px;font-size:13px;border-radius:8px}
.menu li.current>a{background:color-mix(in srgb,var(--accent) 12%,transparent);color:var(--accent);font-weight:600}
.menu .mnum{font:600 11px ui-monospace,Menlo,monospace;color:var(--muted);min-width:18px}
.menu li.sub a{padding:3px 8px 3px 34px;font-size:12px;color:var(--muted)}
.hero{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px 24px;margin:16px 0 14px}
.hero-top{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:6px}
.hero h1{font-size:24px;line-height:1.3;margin:4px 0 6px;color:var(--ink);text-wrap:balance}
.lead{color:var(--muted);font-size:15px;margin:0 0 14px;max-width:80ch}
.chip{display:inline-block;font-size:12px;padding:2px 9px;border-radius:999px;background:var(--code);color:var(--muted);border:1px solid var(--line)}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:6px 0 12px}
.stat{display:flex;flex-direction:column;gap:2px;padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:var(--bg);
text-decoration:none;color:var(--ink);transition:border-color .2s,transform .2s}
.stat:hover,.stat:focus-visible{border-color:var(--accent)}
.slabel{font-size:12px;color:var(--muted);font-weight:600} .svalue{font:700 24px/1.2 ui-monospace,"JetBrains Mono",Menlo,monospace}
.snote{font-size:12px;color:var(--muted)}
.hero-links{display:flex;flex-wrap:wrap;gap:14px;align-items:center;font-size:13px}
.stepper{display:flex;gap:6px;overflow-x:auto;padding:4px 0 10px;margin-bottom:6px;scrollbar-width:thin}
.stepper-item{flex:none;display:flex;gap:6px;align-items:center;padding:6px 12px;border:1px solid var(--line);border-radius:999px;
background:var(--card);color:var(--muted);font-size:13px;text-decoration:none;white-space:nowrap;min-height:32px}
.stepper-item .snum{font:600 11px ui-monospace,Menlo,monospace}
.stepper-item:hover{border-color:var(--accent);color:var(--ink)}
.stepper-item.current{background:var(--accent);border-color:var(--accent);color:var(--card)}
.case.block{background:var(--card);border:1px solid var(--line);border-left:1px solid var(--line);border-radius:16px;padding:0 22px 18px;margin:10px 0}
.case.block>summary{display:flex;gap:12px;align-items:center;padding:16px 0 6px;list-style:none;cursor:pointer}
.case.block>summary::before{content:none}
.bnum{font:700 13px ui-monospace,"JetBrains Mono",Menlo,monospace;color:var(--card);background:var(--navy);border-radius:8px;padding:4px 8px}
.btitle{flex:1;font-size:19px;font-weight:700;color:var(--ink)}
.bcount{font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:1px 9px}
.bhint{margin:0 0 12px;color:var(--muted);font-size:13px}
details.item{border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:10px;margin:10px 0;background:var(--card)}
details.item.depth-2{border-left-color:color-mix(in srgb,var(--accent) 55%,var(--line));background:var(--bg)}
details.item.depth-3{border-left-color:var(--line)}
details.item>summary{display:flex;gap:10px;align-items:baseline;padding:10px 14px;cursor:pointer;list-style:none;font-weight:600}
details.item>summary::-webkit-details-marker{display:none}
details.item>summary::before{content:'▸';color:var(--muted);font-size:12px} details.item[open]>summary::before{content:'▾'}
.inum{font:600 12px ui-monospace,Menlo,monospace;color:var(--accent);min-width:22px} .ititle{flex:1}
.ibody{padding:0 16px 12px 16px}
.prose{max-width:88ch} .prose p{margin:6px 0} .prose ul,.prose ol{margin:6px 0 6px 20px} .prose li{margin:3px 0}
.prose h3,.prose h4,.prose h5{margin:14px 0 6px;font-size:14px} .prose code,.grid-table code{font-size:12.5px}
.prose pre{font-size:12.5px;padding:10px 12px;border-radius:8px;border:1px solid var(--line);overflow-x:auto}
.prose table.md,.grid-table{border-collapse:separate;border-spacing:0;width:100%;border:1px solid var(--line);border-radius:10px;overflow:hidden;margin:8px 0}
.prose table.md th,.prose table.md td,.grid-table th,.grid-table td{border:0;border-bottom:1px solid var(--line);padding:7px 10px;font-size:13.5px}
.prose table.md tr:nth-child(even) td,.grid-table tr:nth-child(even) td{background:color-mix(in srgb,var(--code) 60%,transparent)}
.grid-table tr.total th{background:var(--code);color:var(--ink);font-size:13.5px}
.table-wrap{overflow-x:auto} td.num,th.num{font-variant-numeric:tabular-nums;text-align:right}
.na{padding:10px 14px;border-radius:10px;background:var(--code);color:var(--muted)}
.lead-link{margin:4px 0 8px}
.pill.st-open{background:var(--chg-bg);color:var(--chg)} .pill.st-answered,.pill.st-done{background:var(--new-bg);color:var(--new)}
.pill.st-na,.pill.st-todo{background:var(--code);color:var(--muted)}
.pill.st-new{background:var(--new-bg);color:var(--new)} .pill.st-changed{background:var(--chg-bg);color:var(--chg)}
.pill.st-removed{background:var(--rm-bg);color:var(--rm)}
.flow-figure{margin:10px 0 6px;padding:12px;border:1px solid var(--line);border-radius:12px;background:var(--bg)}
.flow-scroll{overflow-x:auto} svg.flow{display:block;margin:0 auto;max-width:100%;height:auto}
svg.flow .node{fill:var(--node);stroke:var(--edge);stroke-width:1.4}
svg.flow .node.s-new{fill:var(--new-bg);stroke:var(--new);stroke-width:2}
svg.flow .node.s-changed{fill:var(--chg-bg);stroke:var(--chg);stroke-width:2}
svg.flow .node.s-removed{fill:var(--rm-bg);stroke:var(--rm);stroke-dasharray:5 4}
svg.flow .node.k-external{stroke-dasharray:6 4} svg.flow .node.k-start,svg.flow .node.k-end{fill:var(--code)}
svg.flow .node-line{stroke:var(--edge);stroke-width:1}
svg.flow .label{font:13px -apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;fill:var(--ink)}
svg.flow .label.s-removed{text-decoration:line-through;fill:var(--rm)}
svg.flow .edge{fill:none;stroke:var(--edge);stroke-width:1.5} svg.flow .edge.back{stroke-dasharray:5 4}
svg.flow .arrow{fill:var(--edge)} svg.flow .edge-label-bg{fill:var(--bg);stroke:var(--line)}
svg.flow .edge-label{font:11.5px -apple-system,sans-serif;fill:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:8px;font-size:12px;color:var(--muted)}
.lg{display:inline-flex;align-items:center;gap:6px} .lg::before{content:'';width:14px;height:10px;border-radius:3px;border:1.5px solid var(--edge);background:var(--node)}
.lg.s-new::before{border-color:var(--new);background:var(--new-bg)} .lg.s-changed::before{border-color:var(--chg);background:var(--chg-bg)}
.lg.s-removed::before{border-color:var(--rm);border-style:dashed;background:var(--rm-bg)}
.lg.k-decision::before{transform:skewX(-20deg)} .lg.k-data::before{border-top-width:3px} .lg.k-external::before{border-style:dashed}
.flow-text{margin-top:8px;font-size:13px} .flow-text summary{cursor:pointer;color:var(--accent)}
/* polish: quieter navigation, real code font, light nesting, wrapping step bar */
.menu li.sub{display:none} .menu li.sub.on{display:block} body.show-all .menu li.sub{display:none}
.menu li a,.menu li.sub a{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block}
.menu li a{display:flex} .menu li a>span:not(.mnum){overflow:hidden;text-overflow:ellipsis}
.menu li.sub a{border-left:2px solid var(--line);margin-left:16px;border-radius:0 6px 6px 0;padding-left:12px}
.menu li.sub a:hover{border-left-color:var(--accent)}
code,.prose code,.grid-table code,pre{font-family:ui-monospace,"SF Mono",SFMono-Regular,"JetBrains Mono",Menlo,Consolas,monospace}
.prose code,.grid-table code{font-size:.86em;padding:1px 6px;border-radius:5px;background:var(--code);border:1px solid var(--line);
color:var(--ink);white-space:normal;overflow-wrap:anywhere}
.prose{font-size:14.5px;line-height:1.7} .prose li::marker{color:var(--muted)}
.stepper{flex-wrap:wrap;overflow:visible;gap:6px 6px}
.stepper-item{min-height:30px;padding:4px 11px;font-size:12.5px}
details.item{border:1px solid var(--line);border-left:1px solid var(--line);border-radius:12px;background:var(--card);
box-shadow:0 1px 2px rgba(15,23,42,.04)}
details.item>summary{padding:12px 16px;font-size:15px}
details.item[open]>summary{border-bottom:1px solid var(--line)}
.ibody{padding:10px 18px 14px}
details.item.depth-2,details.item.depth-3{border:0;border-left:2px solid var(--line);border-radius:0;box-shadow:none;
background:transparent;margin:12px 0 4px}
details.item.depth-2[open]>summary,details.item.depth-3[open]>summary{border-bottom:0}
details.item.depth-2>summary,details.item.depth-3>summary{padding:4px 12px;font-size:14px}
details.item.depth-2>.ibody,details.item.depth-3>.ibody{padding:2px 12px 6px}
details.item.depth-2:hover,details.item.depth-3:hover{border-left-color:var(--accent)}
.inum{font-size:12px;color:var(--muted)} details.item.depth-1>summary .inum{color:var(--accent)}
.case.block{padding:4px 26px 22px}
.flow-figure{padding:16px}
body.show-all details.case{display:block!important} body.show-all .pager{display:none}
a:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
@media (max-width:1024px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:800px){.main{margin-left:0} .main.plan{padding:0 12px 48px} .hero{padding:16px} .hero h1{font-size:20px}
.case.block{padding:0 12px 12px} .btitle{font-size:16px} .ibody{padding:0 10px 10px}}
@media (prefers-reduced-motion: reduce){*{transition:none!important}}
body[data-lang="vi"] [data-legend="state-same"]::after{content:"Giữ nguyên"}
body[data-lang="en"] [data-legend="state-same"]::after{content:"Unchanged"}
body[data-lang="ja"] [data-legend="state-same"]::after{content:"変更なし"}
body[data-lang="vi"] [data-legend="state-new"]::after{content:"Mới"}
body[data-lang="en"] [data-legend="state-new"]::after{content:"New"}
body[data-lang="ja"] [data-legend="state-new"]::after{content:"新規"}
body[data-lang="vi"] [data-legend="state-changed"]::after{content:"Thay đổi"}
body[data-lang="en"] [data-legend="state-changed"]::after{content:"Changed"}
body[data-lang="ja"] [data-legend="state-changed"]::after{content:"変更"}
body[data-lang="vi"] [data-legend="state-removed"]::after{content:"Bỏ"}
body[data-lang="en"] [data-legend="state-removed"]::after{content:"Removed"}
body[data-lang="ja"] [data-legend="state-removed"]::after{content:"削除"}
body[data-lang="vi"] [data-legend="kind-decision"]::after{content:"Rẽ nhánh"}
body[data-lang="en"] [data-legend="kind-decision"]::after{content:"Decision"}
body[data-lang="ja"] [data-legend="kind-decision"]::after{content:"分岐"}
body[data-lang="vi"] [data-legend="kind-data"]::after{content:"Dữ liệu"}
body[data-lang="en"] [data-legend="kind-data"]::after{content:"Data"}
body[data-lang="ja"] [data-legend="kind-data"]::after{content:"データ"}
body[data-lang="vi"] [data-legend="kind-external"]::after{content:"Hệ thống ngoài"}
body[data-lang="en"] [data-legend="kind-external"]::after{content:"External"}
body[data-lang="ja"] [data-legend="kind-external"]::after{content:"外部システム"}
body[data-lang="vi"] [data-legend="as-text"]::after{content:"Xem dạng văn bản"}
body[data-lang="en"] [data-legend="as-text"]::after{content:"Show as text"}
body[data-lang="ja"] [data-legend="as-text"]::after{content:"テキストで表示"}
body[data-lang="vi"] [data-legend="task-todo"]::after{content:"Chưa làm"}
body[data-lang="en"] [data-legend="task-todo"]::after{content:"To do"}
body[data-lang="ja"] [data-legend="task-todo"]::after{content:"未着手"}
body[data-lang="vi"] [data-legend="task-done"]::after{content:"Đã xong"}
body[data-lang="en"] [data-legend="task-done"]::after{content:"Done"}
body[data-lang="ja"] [data-legend="task-done"]::after{content:"完了"}
"""


PLAN_SCRIPT = _COMMON_SCRIPT + r"""
// One block per page and a numbered menu: no "Page N" headings in the menu.
function buildMenuHeads(){ }
function refresh(){
  var all = document.body.classList.contains('show-all');
  var progress = document.getElementById('progress');
  if (progress) { progress.textContent = all ? '' : word('page') + ' ' + currentPage + ' / ' + pageCount; }
  document.querySelectorAll('[data-sub-page]').forEach(function(li){ li.classList.toggle('on', !all && +li.getAttribute('data-sub-page') === currentPage); });
  document.querySelectorAll('[data-step-page]').forEach(function(a){
    var current = !all && +a.getAttribute('data-step-page') === currentPage;
    a.classList.toggle('current', current);
    if (current) { a.setAttribute('aria-current', 'page'); } else { a.removeAttribute('aria-current'); }
  });
}
function items(){ return Array.prototype.slice.call(document.querySelectorAll('details.item')); }
function visible(el){ return document.body.classList.contains('show-all') || el.closest('details.case').style.display !== 'none'; }
if (expandButton) { expandButton.addEventListener('click', function(){ items().forEach(function(d){ if (visible(d)) { d.open = true; } }); }); }
if (collapseButton) { collapseButton.addEventListener('click', function(){
  caseBlocks().forEach(function(d){ d.open = true; });
  items().forEach(function(d){ d.open = false; });
}); }
document.querySelectorAll('[data-goto-page]').forEach(function(a){ a.addEventListener('click', function(ev){
  ev.preventDefault();
  if (!document.body.classList.contains('show-all')) { showPage(+a.getAttribute('data-goto-page')); }
  var target = document.querySelector(a.getAttribute('href'));
  if (target) { target.open = true; target.scrollIntoView({block: 'start'}); }
  document.body.classList.remove('menu-open');
}); });
document.querySelectorAll('a[data-open-sub]').forEach(function(a){ a.addEventListener('click', function(){
  var target = document.querySelector(a.getAttribute('href')); if (target) { target.open = true; }
}); });
var showAllButton = document.getElementById('showAll');
if (showAllButton) { showAllButton.addEventListener('click', function(){
  var on = document.body.classList.toggle('show-all');
  showAllButton.classList.toggle('on', on);
  if (!on) { showPage(currentPage); } else { refresh(); }
}); }
""" + _COMMON_START


# Extra style of checklist.html on top of PLAN_STYLE: the same look as plan.html, plus case cards with steps.
CHECKLIST_STYLE = r"""
.stats.stats-5{grid-template-columns:repeat(5,minmax(0,1fr))}
/* a page holds many cases: no 'current' background for all of them, the dot shows each case's state */
body:has(main.checklist) .menu li.current>a{background:transparent;color:var(--ink);font-weight:400}
body:has(main.checklist) .menu li a:hover{background:var(--code)}
.stat.st-ok .svalue{color:var(--new)} .stat.st-ng .svalue{color:var(--rm)}
.env{display:flex;flex-direction:column;gap:6px;margin-top:4px;padding:10px 14px;border-radius:10px;background:var(--bg);
border:1px solid var(--line);font-size:13.5px}
.env-row{display:grid;grid-template-columns:120px 1fr;gap:10px} .env-row b{color:var(--muted);font-weight:600}
.doc-list{display:flex;flex-wrap:wrap;gap:6px} .doc-list code{font-size:12px;padding:1px 6px;border-radius:5px;background:var(--code);
border:1px solid var(--line);overflow-wrap:anywhere}
.checklist details.item.depth-1{margin:10px 0}
.cl-case>summary{flex-wrap:wrap}
.cl-case .btitle{font-size:17px} .cl-case .cid{font:600 13px ui-monospace,"SF Mono",Menlo,monospace;color:var(--accent);margin-right:6px}
.cl-case>summary .dot{width:10px;height:10px}
.case-meta{margin:0 0 10px} .case-meta code{font-size:12px}
.cl-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin:0 0 12px}
.cl-panel{border:1px solid var(--line);border-radius:12px;padding:10px 14px;background:var(--bg)}
.cl-panel h4{margin:0 0 6px;font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
.cl-panel ul{margin:0 0 0 18px} .cl-panel li{margin:3px 0}
.grid-table.kv th{width:38%;background:transparent;color:var(--muted);font-weight:600}
.grid-table.steps td{vertical-align:top} .grid-table.steps td.n{width:64px;white-space:nowrap}
.grid-table.steps td.n label{display:flex;gap:8px;align-items:center;cursor:pointer;font:600 12.5px ui-monospace,Menlo,monospace}
.grid-table.steps input[type=checkbox]{width:18px;height:18px;accent-color:var(--accent)}
.grid-table.steps tr.done td{background:color-mix(in srgb,var(--new) 10%,transparent)!important}
.grid-table.steps td.exp{color:var(--ink)} .grid-table.steps td.exp>span:first-child,.grid-table.steps td.exp{border-left:0}
.grid-table.steps pre{margin:6px 0 0;font-size:12.5px;padding:8px 10px;border-radius:8px;background:var(--code);
border:1px solid var(--line);white-space:pre-wrap;color:var(--ink)}
.checklist .note{margin:10px 0 0;padding:8px 12px;border-radius:10px;background:var(--chg-bg);color:var(--chg)}
.res{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-top:14px;padding-top:12px;border-top:1px dashed var(--line)}
.res-label{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.toggle{position:relative;cursor:pointer} .toggle input{position:absolute;opacity:0;width:1px;height:1px}
.toggle span{display:inline-block;min-width:64px;text-align:center;padding:6px 14px;border-radius:999px;border:1px solid var(--line);
font-weight:700;color:var(--muted);background:var(--card)}
.toggle input:focus-visible+span{outline:2px solid var(--accent);outline-offset:2px}
.toggle.ok input:checked+span{background:var(--new-bg);border-color:var(--new);color:var(--new)}
.toggle.ng input:checked+span{background:var(--rm-bg);border-color:var(--rm);color:var(--rm)}
.res .memo{flex:1;min-width:200px;padding:7px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink);font:inherit}
.page-totals{border-radius:12px;padding:8px 14px}
.dot.s-ok{background:var(--new)} .dot.s-ng{background:var(--rm)} .dot.s-part{background:var(--chg)}
@media (max-width:1024px){.stats.stats-5{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:800px){.stats.stats-5{grid-template-columns:repeat(2,minmax(0,1fr))} .env-row{grid-template-columns:1fr}
.grid-table.steps{min-width:640px}}
"""


# Extra style of report.html (e2e-evidence) on top of PLAN_STYLE + CHECKLIST_STYLE: verdict, step cards, screenshots.
REPORT_STYLE = r"""
.stats.stats-6{grid-template-columns:repeat(6,minmax(0,1fr))}
.stat.r-ok .svalue{color:var(--new)} .stat.r-ng .svalue,.stat.r-blocked .svalue{color:var(--rm)}
.stat.r-partial .svalue{color:var(--chg)} .stat.r-not_run .svalue{color:var(--muted)}
.verdict-pill{margin-left:auto;font-weight:700;font-size:13px;padding:4px 14px;border-radius:999px;border:1px solid var(--line);
background:var(--code);color:var(--ink)}
.verdict-pill.r-ok{background:var(--new-bg);border-color:var(--new);color:var(--new)}
.verdict-pill.r-ng{background:var(--rm-bg);border-color:var(--rm);color:var(--rm)}
.verdict-pill.r-partial,.verdict-pill.r-incomplete{background:var(--chg-bg);border-color:var(--chg);color:var(--chg)}
.pill{font-size:12px;font-weight:700;padding:2px 10px;border-radius:999px;background:var(--code);color:var(--muted);white-space:nowrap}
.pill.r-ok,.pill.r-pass{background:var(--new-bg);color:var(--new)} .pill.r-ng{background:var(--rm-bg);color:var(--rm)}
.pill.r-blocked{background:var(--rm-bg);color:var(--rm)} .pill.r-partial,.pill.r-no_evidence{background:var(--chg-bg);color:var(--chg)}
.pill.r-not_run{background:var(--code);color:var(--muted)}
.rp-overview .grid-table tr.group th{background:var(--bg);text-align:left;padding:10px 10px 6px}
.rp-overview .cid,.rp-case .cid{font:600 13px ui-monospace,"SF Mono",Menlo,monospace;color:var(--accent)}
.rp-section{font-size:16px;margin:22px 0 4px}
.rp-case>summary .pill{margin-left:auto}
.rp-case.r-ng{border-left:4px solid var(--rm)} .rp-case.r-ok{border-left:4px solid var(--new)}
.rp-case.r-partial{border-left:4px solid var(--chg)} .rp-case.r-blocked,.rp-case.r-not_run{border-left:4px solid var(--line)}
.case-meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:0 0 12px}
.case-meta .links{margin-left:auto;font-size:13px}
.reason{display:flex;gap:10px;margin:0 0 10px;padding:10px 14px;border-radius:12px;background:var(--chg-bg);color:var(--chg)}
.reason.r-ng,.reason.r-blocked{background:var(--rm-bg);color:var(--rm)} .reason b{white-space:nowrap}
.conclusion{margin:0 0 12px;padding:10px 14px;border-radius:12px;background:var(--bg);border:1px solid var(--line)}
.conclusion b{display:block;font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin-bottom:2px}
.conclusion .prose p{margin:2px 0}
.rp-h{margin:16px 0 8px;font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
.rp-steps{display:flex;flex-direction:column;gap:10px}
.rp-step{border:1px solid var(--line);border-left:4px solid var(--line);border-radius:12px;background:var(--card);padding:10px 14px}
.rp-step.s-pass{border-left-color:var(--new)} .rp-step.s-ng{border-left-color:var(--rm);background:color-mix(in srgb,var(--rm-bg) 45%,var(--card))}
.rp-step.s-no_evidence{border-left-color:var(--chg)}
.rp-step header{display:flex;gap:10px;align-items:center;margin-bottom:8px}
.rp-step header input{width:17px;height:17px;accent-color:var(--new)}
.rp-step .snum{font:700 13px ui-monospace,"SF Mono",Menlo,monospace}
.kv{display:flex;flex-direction:column;gap:4px}
.kv-row{display:grid;grid-template-columns:170px 1fr;gap:12px;padding:4px 0;border-top:1px dashed var(--line)}
.kv-row:first-child{border-top:0} .kv-row .k{color:var(--muted);font-size:13px;font-weight:600}
.kv-row .v{overflow-wrap:anywhere} .kv-row.observed .v{font-weight:500}
.kv-row pre{margin:6px 0 0;font-size:12.5px;padding:8px 10px;border-radius:8px;background:var(--code);border:1px solid var(--line);
white-space:pre-wrap;color:var(--ink)}
.shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin-top:10px}
.shots figure{margin:0;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--bg);padding:0}
.shots img{display:block;width:100%;height:150px;object-fit:cover;object-position:top;transition:transform .2s}
.shots a:hover img{transform:scale(1.02)} .shots figcaption{font-size:11.5px;color:var(--muted);padding:6px 8px;
overflow-wrap:anywhere;border-top:1px solid var(--line)}
@media (max-width:1024px){.stats.stats-6{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:800px){.stats.stats-6{grid-template-columns:repeat(2,minmax(0,1fr))} .kv-row{grid-template-columns:1fr;gap:2px}
.case-meta .links{margin-left:0} .verdict-pill{margin-left:0}}
@media (max-width:640px){.rp-overview .grid-table tr.head{display:none}
.rp-overview .grid-table,.rp-overview .grid-table tbody{display:block}
.rp-overview .grid-table tr.group,.rp-overview .grid-table tr.group th{display:block}
.rp-overview .grid-table tr.row{display:grid;grid-template-columns:1fr auto;gap:4px 10px;padding:10px 12px;
border-top:1px solid var(--line)}
.rp-overview .grid-table tr.row td{display:block;padding:0;border:0;white-space:normal;background:transparent}
.rp-overview .c-steps{grid-column:2;grid-row:1}
.rp-overview .c-title,.rp-overview .c-reason,.rp-overview .c-links{grid-column:1/-1}
.rp-overview .c-reason{color:var(--muted)} .reason{flex-direction:column;gap:2px}}
"""
