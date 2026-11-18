# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Case đã phân tích (lấy từ trial đang fail trong report `eval_seeded_regression.json`)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run ID `E-seeded_regression-20261118-4fcf` (report `src/reports/eval_seeded_regression.json`), item `E-002` |
| Triệu chứng | Grader Lab 8 FAIL: `status resolved != denied`. Reply nói "LogiX đã hoàn 20.000đ cho đơn O-202", trong khi ledger ghi `refund_vnd=20000, refund_count=1` — nhãn yêu cầu `denied, refund_vnd=0, refund_count=0`. Đơn O-202 trễ thật 2 ngày (< 3 ngày theo SHIP-LATE-03) nên không có entitlement nào. |
| Bước sai đầu tiên | Event **3**, kind `model_override`, payload `{"delay_days": 5}` — agent thay số ngày trễ của DB (2) bằng số trong ticket của khách (5). |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` và event 2 `investigator` đúng: `lookup_order visible=true, reason=ok`, đọc được đơn O-202 với `delay_days: 2`. Sai chỉ bắt đầu khi giá trị 5 được ghi đè lên dữ liệu đã tra đúng — mọi bước sau (event 4 `quote {"amount_vnd": 20000}` thay vì 0, hoàn tiền 20.000đ, event 6 reply "đã hoàn 20.000đ") đều là hậu quả của event 3. |
| Failure mode | **FM-03** (`ticket_trust`) — xem `docs/failure_taxonomy.md`; kèm biểu hiện FM-08 (reply nói 20.000đ trong khi nhãn/điều kiện đúng là 0đ). |
| Đối chứng | Cùng `C-002@11` trên shape `fixed`: **không có event `model_override`** (trace chỉ còn 4 event), quote trả `{"amount_vnd": 0, "reason": "no_entitlement"}`, reply là mẫu từ chối, ledger 0đ, grader PASS (`ok`). |
| Regression test | Grader `DbFactKept` (metric `db_fact_kept`) bắt mọi event `model_override` → FAIL trên `seeded_regression` C-002@11, PASS trên `fixed`; đồng thời `TrialPass`/`pass_rate` bắt `status resolved != denied` và `RefundAmountCorrect` bắt ledger 20.000đ ≠ nhãn 0đ. Đã thấy trong report: `db_fact_kept` = 0.9286 (seeded) vs 1.0 (fixed); gate exit 1 với `pass_rate` Δ −0.271, CI [−0.500, −0.057]. |
| Chưa chắc chắn | Trace không chứng minh *tại sao* agent ưu tiên ticket (prompt hay do MockLLM replay); chỉ chứng minh *rằng* giá trị ticket được ghi đè ở event 3. Với seed % 5 == 0 (C-002@55), cả baseline `swarm` Day 8 gốc cũng dính cùng lỗi — đây là nhiễu đã biết của reference, không phải bug mới của PR. |

Kết quả ledger vs nhãn của hai trace (trích lệnh trên):

```
seeded_regression: refund_vnd ledger=20000 label=0   refund_count ledger=1 label=0   status=resolved label=denied
fixed            : refund_vnd ledger=0     label=0   refund_count ledger=0 label=0   status=denied   label=denied
```

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
