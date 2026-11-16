# Interactive approval dialogs (OPS-013)

Use this when OPS-011, OPS-012 or another operation requires approval that the conversation does not already cover. Keep the operation pending until the user explicitly approves its exact actions and targets. Ordinary authorized local work does not need this dialog.

## Presentation

Use the host's supported interactive approval/question UI instead of only writing a warning in prose. On the current Codex surface, `request_user_input_async` can present this question; on other hosts use an available tool whose contract permits approval requests. Never invent a tool or use one that forbids approval requests. Native command-permission dialogs remain controlled by the host and its session policy: do not change permissions or manufacture a command failure to force one.

Give the dialog a short title in the user's language: one Unicode icon, the action and the environment when known. If the tool has no separate heading field, put that title on the first line of its question and the details below. Use its actual schema; do not invent `icon`, `logo` or `title` fields. The icon is text rendered by the host; no image download is needed.

| Action | Example short title (Vietnamese) |
| --- | --- |
| Cloud inspection | ☁️ Xem AWS · DEV |
| Database read/schema/plan | 🗄️ Đọc DB · STG |
| Data deletion | 🗑️ Xóa dữ liệu · PRD |
| Backup/export | 💾 Backup DB · STG |
| Configuration/write | ⚙️ Đổi cấu hình · DEV |
| Deployment | 🚀 Deploy · STG |

Below the title show the exact command/query or tool action, account/profile, server/environment, database/resource, purpose and risks/costs as applicable. Label unknown details; never connect to discover them before approval. Redact secrets. Keep one question for one action or an explicitly listed batch. Do not combine approval with unrelated preferences or offer blanket permission.

Offer a clear refusal and a scoped approval, such as `Từ chối` and `Cho phép đúng thao tác này`. Put refusal first when the UI preselects the first choice. Selection is not submission: only an explicit submitted answer, or a clear matching reply in chat, grants approval. Do not use a preselected approval or mark approval as recommended.

## Example tool payload

Synthetic example only; the command is not executed. For `request_user_input_async` the title belongs inside the question string:

```json
{
  "questions": [
    {
      "title": "🗄️ Đọc DB · STG\n\nThao tác: psql --host db.stg.example.invalid --dbname demo --command 'SELECT 1;'\nĐích: STG / demo, database ngoài local.\nMục đích: kiểm tra kết nối.\nRủi ro: truy cập DB STG và tiêu thụ tài nguyên.\nBạn có cho phép đúng thao tác này không?",
      "options": ["Từ chối", "Cho phép đúng thao tác này"]
    }
  ]
}
```

## Pending, denied and unavailable states

- An asynchronous question returns before the user answers. Its tool result is not approval. Keep the question pending and continue only independent offline work; if none remains, tell the user you are waiting and end the turn without executing or queuing the operation.
- A refusal, dismissed/cancelled dialog, no answer, elapsed time, unavailable tool or tool failure grants no permission. Ambiguous or edited consent must be clarified. Re-check that the answer covers the exact listed actions and targets; changes require another approval.
- If no suitable interactive tool exists, say that the popup is unavailable in this host/session, show the same icon/title and operation details in chat, and wait for explicit consent. Never silently downgrade to execution.
- A preview must say it is a preview and must not execute a real cloud/remote DB action, even if the user clicks approval in the preview. Preview approval is not authorization for later operations.

## Evidence and limitations

This reference instructs the agent to request an interactive confirmation. It does not install a deterministic command interception hook, alter the host's approval policy or customize native dialog chrome/logos. A successful question-tool call proves that a request was sent; actual rendering and user response require separate evidence. Offline package/installer checks do not prove future agent compliance or native UI behavior.
