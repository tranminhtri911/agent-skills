# task01: buildMemo ghi dòng giá cả ngày

- Estimate: 3h · Phụ thuộc: — · Plan: ../plan.html (Cách sửa → buildMemo.ts)

## Overview

- Hiện tại: `buildMemo()` ghi mỗi thiết bị một dòng giá thường.
- Sau task: thiết bị có giá cả ngày ghi `(giá cả ngày)×1` rồi `(giá thường)×(n-1)`.
- Chỉ khi booking áp dụng giá cả ngày.
- Không đổi các dòng khác của memo.

## Implementation

1. `resources/js/utils/buildMemo.ts`: thêm tham số `estimateRows: EstimateRow[]` (đã có type trong `types/estimate.ts`).
2. Với mỗi thiết bị: tìm dòng estimate cùng `equipmentId`; nếu `isAllDay` thì ghi 2 dòng như trên, giá lấy từ `unitPriceTaxIncluded`.
3. Giữ hàm format giá hiện có (`formatYen`), không thêm thư viện.

Files: `resources/js/utils/buildMemo.ts` (sửa), `resources/js/utils/buildMemo.test.ts` (thêm case).

## Unit test

- cả ngày, số lượng 1 → `・DEMO Projector(1,100円)×1`
- cả ngày, số lượng 3 → `(1,100円)×1` / `(550円)×2`
- không cả ngày, số lượng 3 → `(550円)×3`
- thiết bị không bật cả ngày → giữ một dòng giá thường

## E2E test

Checklist TC01 step 4-6 và TC02 (đổi giờ). Chạy bằng skill e2e-evidence sau task02.

## Verify

Local: tạo booking 8:00-20:00, DEMO Projector × 3, đọc memo trên form; so với chi tiết booking.

## Done criteria

Unit test pass; memo đúng ở TC01/TC02; không đổi memo khi chỉ mở màn hình sửa.
