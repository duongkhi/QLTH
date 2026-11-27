# Kiến trúc & Quy tắc Dự án `autofill`

## 1. Tổng quan Hệ thống
- **Nền tảng:** Ứng dụng web Python Streamlit (`main.py`), triển khai qua GitHub lên Streamlit Cloud.
- **Cơ sở dữ liệu (Supabase):** Sử dụng **một bảng duy nhất tên là `app_data`** với 2 cột: `key` (`text`, khóa chính) và `data` (`jsonb`).
- **Quy tắc dữ liệu JSONB:** Thông tin cán bộ được lưu dưới dạng JSON theo từng `key`. Các khóa hệ thống/cấu hình phải được khai báo trong `META_KEYS` tại `config.py` để không bị nhận nhầm là hồ sơ cá nhân.
- Quy trình phát triển: Khi người dùng yêu cầu thêm tính năng mới hoặc thay đổi logic nghiệp vụ, luôn tự động kích hoạt và chạy theo skill `openspec-quick-path` trước khi sửa mã nguồn.
## 2. Cấu trúc dữ liệu thực tế trên Supabase (kiểm tra trực tiếp)

### Tổng quan
- Tổng số `key` trong bảng `app_data`: **17+** (sau khi nhập SCImago 2025)
- Hồ sơ cá nhân: **4** (`BuiNhung`, `PhamHongMinh`, `VuDuong`, `admin_rules`)

### Key hệ thống/cấu hình chính
| Key | Ghi chú |
|-----|---------|
| `auth_config` | Cấu hình đăng nhập, phân quyền |
| `name_mapping` | Ánh xạ tên hiển thị |
| `hermes_skills_registry` | Kho skill |
| `ai_settings` | Cấu hình AI |
| `journal_quality_catalog_index` | Chỉ mục các batch catalog SCImago 2025 |
| `journal_quality_catalog_01` ... `_11` | Kho danh mục chất lượng tạp chí SCImago 2025 (32.186 tạp chí) |
| `_form_template_*` | Biểu mẫu |
| `chat_history_*` | Lịch sử chat |
| `finance_disbursements`, `finance_projects` | Chi tiêu, đề tài |
| `kb_*` | Quy chế |

### Cấu trúc hồ sơ cá nhân (thực tế)
** Trường lưu họ tên: `ho_va_ten` (KHÔNG phải `ho_ten`)**
** Trường lưu đơn vị công tác: `don_vi_cong_tac` (chỉ có ở một số hồ sơ)**

Ví dụ hồ sơ `PhamHongMinh` (8 trường):
```json
{
  "email": "...",
  "chuc_vu": "...",
  "ho_va_ten": "...",
  "ngay_sinh": "...",
  "ngay_vao_dang": "...",
  "so_dien_thoai": "...",
  "don_vi_cong_tac": "...",
  "dia_chi_thuong_tru": "..."
}
```

Ví dụ hồ sơ `BuiNhung` (61 trường, không có `don_vi_cong_tac`):
- Có `ho_va_ten`, `so_truong_cong_tac`, `cong_viec_chinh_duoc_giao`
- Có `dao_tao_boi_duong`, `tom_tat_qua_trinh_cong_tac`, `quan_he_gia_dinh`
- **Không có** danh sách bài báo khoa học

### Trường `bai_bao_cong_bo` (đã chuẩn hóa)
Đã được thêm vào hồ sơ `VuDuong` (7 bài báo) thông qua hàm `sync_bai_bao_cong_bo()` trong `profile_service.py`.

Mỗi bài báo trong `bai_bao_cong_bo` có cấu trúc:
```json
{
  "ten_cong_trinh": "Tên bài báo",
  "nam_cong_bo": "2008",
  "noi_cong_bo": "Journal of Korean Phys. Soc., p.3823-3826",
  "loai_cong_trinh": "Tạp chí quốc tế",
  "phan_loai": "Tạp chí quốc tế",  // hoặc "Scopus Q1", "ISI/SCI-EE Q1", "SCI", "Hội nghị quốc tế", "Tạp chí trong nước", "Khác"...
  "vai_tro": "Đồng tác giả",
  "tac_gia_dau": false,
  "tac_gia_lien_he": false,
  "dong_tac_gia": true,
  "doi": "",
  "issn": ""
}
```

**Luồng xử lý khi đính kèm file CV/Excel trong chatbox:**
1. `chat_agent.py`: Gọi **Gemini** (`generate_gemini_text_real`) để trích xuất văn bản từ file thành JSON chi tiết (có `phan_loai`, `vai_tro`, `tac_gia_dau`, `tac_gia_lien_he`, `dong_tac_gia`, `doi`, `issn`, ...).
2. `profile_service.py`: Hàm `sync_bai_bao_cong_bo()` chuẩn hóa dữ liệu:
   - Ưu tiên `phan_loai`, `tac_gia_dau`, `tac_gia_lien_he`, `dong_tac_gia` từ Gemini nếu đã có.
   - Nếu không có, tự phân loại (Scopus Q1-Q4, ISI/SCI-EE, SCI, Hội nghị/Tạp chí trong nước/quốc tế, Khác).
   - Xác định vai trò tác giả (đầu / liên hệ / đồng tác giả).
   - Loại bỏ trùng lặp theo `ten_cong_trinh + nam_cong_bo`.
3. Lưu vào trường `bai_bao_cong_bo` của hồ sơ.
4. Hàm `merge_and_save()` đã được sửa để tự động gọi `sync_bai_bao_cong_bo()` trước khi lưu, nên mọi lần cập nhật hồ sơ sau này sẽ tự động chuẩn hóa bài báo.

### Kho danh mục chất lượng tạp chí `journal_quality_catalog` (SCImago 2025)
- Đã nhập **32.186 tạp chí** từ file `scimagojr 2025.csv` vào 11 key sharded trên Supabase.
- Mỗi mục có: `journal_name`, `source_title`, `issn`, `quartile` (Q1-Q4), `year`, `document_type`, `publisher`, `country`, `region`, `index_type` (= "Scopus"), ...

## 3. Bản đồ các tệp chính
- `main.py` & `config.py`: Điều hướng trang (`view_mode`), cấu hình `UserContext` và danh sách `META_KEYS`.
- `supabase_adapter.py`: Kết nối Supabase, đọc/ghi JSON.
- `chat_agent.py`: Xử lý chat AI, **gọi Gemini khi có file đính kèm**, gọi Nemotron cho chat văn bản.
- `chat_ui.py`: Chat box trong sidebar, nút Gửi đồng bộ với text/file.
- `profile_service.py`: Xử lý hồ sơ khoa học, **chứa hàm `sync_bai_bao_cong_bo()` và `merge_and_save()` đã cập nhật**.
- `journal_service.py`: Quản lý danh mục chất lượng bài báo (đã cập nhật đọc từ sharded key).
- `user_service.py`, `finance_service.py`: Phân quyền tài khoản, dữ liệu đề tài/kinh phí.
- `skill_manager.py` & `ui/skill_ui.py`: Kho skill, tạo skill bằng AI.
- `thu_muc_cau_hình_ke_toan/`: Gói cấu hình cục bộ.

## 4. Quy tắc làm việc bắt buộc cho AI Agent
1. **Ngôn ngữ:** Luôn trả lời, giải thích và báo cáo kết quả bằng tiếng Việt tự nhiên, rõ ràng.
2. **An toàn ghi tệp (OneDrive):** Luôn đọc lại chính xác các dòng xung quanh trước khi `patch`; nếu sửa nhiều vị trí hoặc `patch` lỗi 1 lần, dùng ngay `write_file` để ghi đè sạch toàn bộ tệp.
3. **Bảo mật Git:** Tuyệt đối không đưa `.streamlit/secrets.toml`, `.env` hay thư mục `thu_muc_cau_hình_ke_toan/` vào `git add` / `git push`.
4. **Quy trình thay đổi lớn:** Luôn liệt kê kế hoạch các tệp sẽ sửa và nội dung thay đổi trước, chờ người dùng xác nhận rồi mới ghi tệp.

## Quy tắc Chống Sửa Dở & Tự Kiểm Tra (Bắt buộc)
1. **Đọc trọn vẹn trước khi ghi:** Luôn gọi `read_file` đọc từ dòng đầu đến dòng cuối trước khi sửa tệp đã tồn tại.
2. **Đồng bộ cả 2 đầu khi đổi hàm:** Khi thêm/sửa tham số hàm, BẮT BUỘC sửa khớp ở tất cả tệp gọi hàm đó ngay trong cùng lượt.
3. **Chia nhỏ tác vụ:** Không sửa quá 2 tệp lớn cùng một lúc.
4. **Tự kiểm tra cú pháp trước khi báo xong:** Chạy `python -m py_compile <cac_tep_vua_sua>` để đảm bảo 0 lỗi cú pháp.

## 5. Công việc đã hoàn thành & đang chờ
- ✅ Đã nhập SCImago 2025 vào `journal_quality_catalog` (32.186 tạp chí).
- ✅ Đã chuẩn hóa dữ liệu bài báo về `bai_bao_cong_bo` cho hồ sơ `VuDuong` (7 bài báo).
- ✅ Đã cập nhật `merge_and_save()` để tự động chuẩn hóa bài báo khi lưu hồ sơ.
- ✅ Đã cập nhật prompt Gemini để trích xuất chi tiết (phan_loai, vai_tro, doi, issn, ...).
- ✅ Đã cập nhật `_normalize_one_publication` để ưu tiên giá trị từ Gemini.
- ⏳ Chưa cập nhật Skill `thong_ke_bai_bao_khoa_hoc` để đọc từ `bai_bao_cong_bo` / `publications_index` (người dùng yêu cầu chờ).
