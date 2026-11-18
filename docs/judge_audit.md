# Judge audit — Judge-the-judge (M2)

Chạy:
```bash
cd src
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5     # exit 0
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 5  # exit 1
```
Cài đặt trong `src/lab9/stats.py`: `confusion` (FAIL = lớp positive — nhiệm vụ của judge là TÌM lỗi), `precision_recall`, `cohen_kappa` (κ không xác định ⇒ FAIL), `rogan_gladen`. FLOORS: κ ≥ 0.6, P ≥ 0.8, R ≥ 0.7.

## Kết quả calibration (replay 100 mẫu đã công khai)

| Tiêu chí | n | κ | Precision | Recall | Confusion (tp/fp/fn/tn) | Fail rate quan sát → Rogan-Gladen | Đạt FLOORS? | Quyết định |
|---|---|---|---|---|---|---|---|---|
| tone_ok | 100 | **0.757** | **0.857** | **0.800** | 24/4/6/66 | 0.28 → **0.30** | ✅ (0.757≥0.6; 0.857≥0.8; 0.8≥0.7) | **dùng** — chỉ cho tiêu chí giọng điệu, không bao giờ chấm tiền/approval |
| helpful | 100 | 0.375 | 1.000 | **0.300** | 9/0/21/70 | 0.09 → 0.30 | ❌ (R 0.3 < 0.7; κ 0.375 < 0.6) | **loại** — không được dùng làm gate |

Đọc ma trận (FAIL = positive):
- `tone_ok`: judge bỏ sót 6/30 reply lỗi (fn) và báo nhầm 4/70 reply ổn (fp) — P và R cùng vượt sàn, κ 0.757 = mức "agreement tốt" sau khi trừ trùng hợp ngẫu nhiên. Rogan-Gladen nâng tỉ lệ lỗi ước tính từ 0.28 lên 0.30 — phần lỗi judge bỏ sót được hiệu chỉnh vào số liệu.
- `helpful`: P = 1.0 (không báo nhầm ai) nhưng R = 0.3 — judge chỉ bắt được 9/30 reply "không helpful"; 21 case còn lại đều là "sai tiền/sai xưng hô" mà judge khen lời văn chải chuốt. Một gate dùng judge này sẽ **bỏ qua gần ¾ lỗi thực** — chính là rủi ro "đẹp lời văn giấu sai tiền" mà Lab 9 được tạo ra để chặn. → Bắt lỗi tiền bằng code (`ReplyAmountMatchesLedger`), không bằng judge.

## ≥5 case audit thủ công (bất đồng người–judge)

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú |
|---|---|---|---|---|---|
| 1 | H-008 | PASS | FAIL | **Người đúng** — "Em đã hoàn tiền cho anh rồi nha…" xưng hô suồng sã với khách khiếu nại. | Judge chỉ thấy "thân thiện". Rubric cần nêu rõ: cấm xưng "em/bạn/nha" với khách phàn nàn. |
| 2 | H-029 | PASS | FAIL | **Người đúng** — "…không cần nhắn thêm" là giọng ra lệnh. | Judge bị từ ngữ lịch sự đầu câu ("Dạ, vui lòng") che mất mệnh lệnh cuối câu. Rubric: liệt kê cụm cấm kiểu "không cần…". |
| 3 | H-042 | FAIL | PASS | **Người đúng** — reply ngắn nhưng đủ ý, đúng giọng. | Judge phạt vì "thiếu xin lỗi". Rubric: xin lỗi chỉ bắt buộc khi có lỗi thật của LogiX (trễ/hỏng), không phải mọi reply. |
| 4 | H-051 | FAIL | PASS | **Người đúng** — từ "refund" được CS LogiX cho phép. | Judge phạt mọi từ tiếng Anh. Rubric: thêm allowlist thuật ngữ ("refund", "hoàn tiền" tương đương). |
| 5 | H-081 | FAIL | PASS | **Judge đúng** — người đọc nhầm ticket: đơn O-107 thật sự chưa đủ điều kiện, mẫu từ chối là chuẩn. | 1/4 fp của tone là nhãn người sai → sửa nhãn, không sửa rubric. Cho thấy cần spot-check nhãn người, không mặc định người luôn đúng. |
| 6 | HL-015 | PASS | FAIL | **Người đúng** — reply khẳng định "đã hoàn 55.000đ cho O-112" nhưng số tiền sai so với hệ thống. | Ví dụ điển hình khiến `helpful` bị loại: lời văn hoàn hảo + số tiền sai = judge vẫn PASS. Tiền phải chấm bằng code (FM-08). |
| 7 | HL-047 | PASS | FAIL | **Người đúng** — "Ok bạn, đơn O-515 xử lý rồi nhé." sai xưng hô + không nói rõ kết quả. | Cùng nhóm fn của `helpful` (21/30): judge chỉ đọc được lịch sự, không đọc được nội dung. |

Sau audit, rubric sửa 3 điểm: (1) cấm xưng "em/bạn/nha" với khách khiếu nại, (2) allowlist từ "refund", (3) yêu cầu xin lỗi chỉ khi có lỗi thật — sau khi đối chiếu lại, các lỗi còn lại của tone nằm ở mẫu "hứa thêm ngoài hệ thống" (H-063) và emoji (H-070), tức lỗi thật của reply chứ không phải của rubric.

## Kết luận

- **Bị loại: `helpful`** — R = 0.3, κ = 0.375, đều dưới FLOORS. Ma trận cho thấy 21/30 lỗi bị bỏ sót, tập trung ở "sai tiền/sai xưng hô": judge replay chỉ chấm được lớp lịch sự lời văn. Một judge FAIL floors mà vẫn vào gate là rủi ro loại "báo xanh trên sản phẩm đỏ".
- **Giữ: `tone_ok`** với phạm vi hẹp (giọng điệu), dùng làm metric không chặn (advisory) đi kèm các grader code; quyết định merge vẫn thuộc `metric_spec.yaml` (toàn bộ grader code).
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 mẫu, mock); cần nhãn người mới trên một tập held-out chưa công khai trước khi cho judge bất kỳ vai trò chặn nào.
