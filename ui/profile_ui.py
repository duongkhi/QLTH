#profile_ui.py
import streamlit as st
import base64
import json
from config import UserContext
from storage import load_user_profile, save_user_profile
from user_service import load_auth_config, save_auth_config, update_user_password
from user_service import update_user_password
from finance_service import load_finance_data, get_visible_project_ids
from docx_utils import cached_extract_docx, smart_truncate
from ai_client import call_model_json

def get_image_base64(uploaded_file):
    if uploaded_file is not None:
        bytes_data = uploaded_file.getvalue()
        base64_str = base64.b64encode(bytes_data).decode()
        return f"data:image/png;base64,{base64_str}"
    return None

def render_avatar(avatar_b64, username, size=120):
    if avatar_b64:
        st.markdown(f'<img src="{avatar_b64}" style="width:{size}px; height:{size}px; border-radius:50%; object-fit:cover; border: 3px solid #667eea;">', unsafe_allow_html=True)
    else:
        # Default avatar (chữ cái đầu)
        initial = username[0].upper() if username else "U"
        st.markdown(f'<div style="width:{size}px; height:{size}px; border-radius:50%; background-color:#667eea; color:white; display:flex; align-items:center; justify-content:center; font-size:{size//2}px; font-weight:bold;">{initial}</div>', unsafe_allow_html=True)

def render_profile_page(ctx: UserContext, target_username: str):
    # 1. Lấy dữ liệu
    cfg = load_auth_config()
    target_rec = cfg["users"].get(target_username, {})
    target_profile_key = target_rec.get("own_profile", target_username)
    data = load_user_profile(target_profile_key)
    
    if not data:
        st.warning(f"⚠️ Hồ sơ của {target_username} chưa có dữ liệu. Vui lòng cập nhật.")
        data = {}

    is_self = (target_username == ctx.username)
    
    # Khởi tạo trạng thái Mode
    if "profile_mode" not in st.session_state:
        st.session_state.profile_mode = "view"
        
    # Nếu chuyển sang xem người khác thì reset mode về view
    if st.session_state.get("current_view_profile") != target_username:
        st.session_state.current_view_profile = target_username
        st.session_state.profile_mode = "view"

    # ==========================================
    # GIAO DIỆN CỘT TRÁI (AVATAR & NÚT SETTING)
    # ==========================================
    col_left, col_right = st.columns([1, 3])
    
    with col_left:
        # Hiển thị Avatar
        avatar_b64 = data.get("avatar_base64")
        render_avatar(avatar_b64, target_username, size=150)
        
        st.markdown(f"<h3 style='text-align: center; margin-top: 10px;'>{data.get('ho_va_ten', target_username)}</h3>", unsafe_allow_html=True)
        st.markdown(f"<p style='text-align: center; color: gray;'>{data.get('chuc_vu', 'Chưa cập nhật')}</p>", unsafe_allow_html=True)
        
        if is_self:
            if st.session_state.profile_mode == "view":
                if st.button("⚙️ Cài đặt (Settings)", use_container_width=True):
                    st.session_state.profile_mode = "edit"
                    st.rerun()
            else:
                if st.button("⬅️ Quay lại Trang cá nhân", use_container_width=True, type="primary"):
                    st.session_state.profile_mode = "view"
                    st.rerun()

    # ==========================================
    # GIAO DIỆN CỘT PHẢI (CÁC TABS)
    # ==========================================
    with col_right:
        if st.session_state.profile_mode == "view":
            _render_view_mode(ctx, data, is_self, target_rec, target_username)
        else:
            _render_edit_mode(ctx, data, target_profile_key)


# ==========================================
# CHẾ ĐỘ 1: XEM (VIEW MODE)
# ==========================================
def _render_view_mode(ctx, data, is_self, target_rec, target_username):
    st.subheader("Hồ sơ cá nhân")
    
    # Lọc dữ liệu theo quyền
    is_admin = ctx.role == "admin"
    is_manager_hr = (ctx.role == "manager" and "hr" in ctx.record.get("permissions", []))
    
    if is_self or is_admin or is_manager_hr:
        display_data = data
        st.caption("✅ Bạn có toàn quyền xem hồ sơ này.")
    else:
        public_fields = target_rec.get("public_fields", ["ho_va_ten", "chuc_vu"])
        display_data = {k: v for k, v in data.items() if k in public_fields}
        st.caption("⚠️ Bạn chỉ được xem các thông tin công khai của hồ sơ này.")

    tab1, tab2, tab3, tab4 = st.tabs(["📋 Thông tin chung", "🎓 Quá trình đào tạo", "📚 Công bố khoa học", "🔬 Hướng nghiên cứu"])
    
    with tab1:
        colA, colB = st.columns(2)
        with colA:
            st.write(f"**Họ và tên:** {display_data.get('ho_va_ten', 'Chưa có')}")
            st.write(f"**Ngày sinh:** {display_data.get('ngay_sinh', 'Chưa có')}")
            st.write(f"**Giới tính:** {display_data.get('gioi_tinh', 'Chưa có')}")
            st.write(f"**Email:** {display_data.get('email', 'Chưa có')}")
            st.write(f"**SĐT:** {display_data.get('so_dien_thoai', 'Chưa có')}")
        with colB:
            st.write(f"**Chức vụ:** {display_data.get('chuc_vu', 'Chưa có')}")
            st.write(f"**Đơn vị:** {display_data.get('don_vi_cong_tac', 'Chưa có')}")
            st.write(f"**Địa chỉ:** {display_data.get('dia_chi_thuong_tru', 'Chưa có')}")
            st.write(f"**Ngày vào Đảng:** {display_data.get('ngay_vao_dang', 'Chưa có')}")
            st.write(f"**CCCD:** {display_data.get('so_cccd', 'Chưa có')}")

    with tab2:
        st.write(f"**Học vị:** {display_data.get('hoc_vi', 'Chưa có')}")
        st.write(f"**Năm tốt nghiệp:** {display_data.get('nam_tot_nghiep', 'Chưa có')}")
        st.write(f"**Nơi đào tạo:** {display_data.get('noi_dao_tao', 'Chưa có')}")
        
    with tab3:
        publications = display_data.get("cong_bo_khoa_hoc", [])
        if not publications:
            st.info("Chưa có công bố khoa học nào.")
        for pub in publications:
            # Nếu là người khác xem, chỉ hiện bài public
            if not is_self and not is_admin and not pub.get("is_public", True):
                continue
            with st.expander(f"📄 {pub.get('title', 'Bài báo')} ({pub.get('year', 'N/A')})"):
                st.write(f"**Tạp chí:** {pub.get('journal', 'N/A')}")
                st.write(f"**Vai trò:** {pub.get('role', 'Tác giả')}")
                if pub.get("link"):
                    st.markdown(f"[Xem chi tiết]({pub.get('link')})")

    with tab4:
        st.write(f"**Hướng nghiên cứu chính:** {display_data.get('huong_nghien_cuu', 'Chưa cập nhật')}")


# ==========================================
# CHẾ ĐỘ 2: SỬA (SETTINGS MODE)
# ==========================================
def _render_edit_mode(ctx, data, profile_key):
    st.subheader("⚙️ Cài đặt & Cập nhật Hồ sơ")
    
    tabs = st.tabs(["📸 Avatar & Cơ bản", "📄 Cập nhật từ CV (AI)", "🔒 Đổi mật khẩu", "📚 Quản lý Công bố"])
    
    with tabs[0]:
        st.markdown("### Ảnh đại diện")
        new_avatar_file = st.file_uploader("Tải lên ảnh mới (chỉ .jpg, .png)", type=["jpg", "jpeg", "png"])
        if new_avatar_file:
            b64 = get_image_base64(new_avatar_file)
            if st.button("Lưu Avatar"):
                data["avatar_base64"] = b64
                save_user_profile(profile_key, data)
                st.success("✅ Đã cập nhật Avatar!")
                st.rerun()
                
        st.markdown("### Thông tin cơ bản")
        with st.form("update_basic_info"):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("Họ tên", value=data.get("ho_va_ten", ""))
                dob = st.text_input("Ngày sinh", value=data.get("ngay_sinh", ""))
                email = st.text_input("Email", value=data.get("email", ""))
                phone = st.text_input("SĐT", value=data.get("so_dien_thoai", ""))
            with c2:
                role_pos = st.text_input("Chức vụ", value=data.get("chuc_vu", ""))
                dept = st.text_input("Đơn vị", value=data.get("don_vi_cong_tac", ""))
                addr = st.text_input("Địa chỉ", value=data.get("dia_chi_thuong_tru", ""))
                party_date = st.text_input("Ngày vào Đảng", value=data.get("ngay_vao_dang", ""))
                
            if st.form_submit_button("💾 Lưu thông tin cơ bản"):
                data.update({
                    "ho_va_ten": name, "ngay_sinh": dob, "email": email, "so_dien_thoai": phone,
                    "chuc_vu": role_pos, "don_vi_cong_tac": dept, "dia_chi_thuong_tru": addr, "ngay_vao_dang": party_date
                })
                save_user_profile(profile_key, data)
                st.success("✅ Đã lưu thông tin!")
                st.rerun()

    with tabs[1]:
        st.markdown("### Trích xuất tự động từ CV mới")
        st.caption("Tải lên CV mới, AI sẽ tự động bóc tách và cập nhật đè lên các trường tương ứng.")
        upf = st.file_uploader("Upload file .docx", type=["docx"], key="profile_cv_upload")
        if upf:
            if st.button("🤖 Trích xuất & Cập nhật"):
                with st.spinner("AI đang đọc file..."):
                    raw = cached_extract_docx(upf.getvalue())
                    prompt = f"Trích xuất toàn bộ thông tin cá nhân từ văn bản sau thành JSON phẳng (key tiếng Anh).\n\n{raw}"
                    progress = st.progress(10)
                    try:
                        jt = call_model_json(prompt, progress, 20, 90, "Đang trích xuất")
                        extracted = json.loads(jt)
                        # Merge vào data hiện tại
                        data.update(extracted)
                        save_user_profile(profile_key, data)
                        st.success(f"✅ Đã cập nhật {len(extracted)} trường từ CV!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Lỗi: {e}")

    with tabs[2]:
        st.markdown("### Đổi mật khẩu")
        with st.form("profile_change_pw"):
            new_pw = st.text_input("Mật khẩu mới", type="password")
            confirm = st.text_input("Nhập lại mật khẩu mới", type="password")
            if st.form_submit_button("Xác nhận đổi", type="primary"):
                if not new_pw or len(new_pw) < 6:
                    st.error("Mật khẩu ≥6 ký tự.")
                elif new_pw != confirm:
                    st.error("Mật khẩu nhập lại không khớp.")
                else:
                    if update_user_password(ctx.username, new_pw):
                        st.success("✅ Đã đổi mật khẩu thành công!")
                    else:
                        st.error("Lỗi không xác định.")

    with tabs[3]:
        st.markdown("### Thêm Công bố Khoa học")
        with st.form("add_publication"):
            title = st.text_input("Tên bài báo")
            journal = st.text_input("Tên tạp chí / Hội thảo")
            year = st.number_input("Năm công bố", min_value=1900, max_value=2100, value=2024, step=1)
            link = st.text_input("Link bài báo (nếu có)")
            is_public = st.checkbox("Cho phép người khác xem bài này", value=True)
            
            if st.form_submit_button("Thêm bài báo"):
                if not title:
                    st.error("Cần nhập tên bài báo.")
                else:
                    pubs = data.get("cong_bo_khoa_hoc", [])
                    pubs.append({
                        "title": title, "journal": journal, "year": year, 
                        "link": link, "is_public": is_public
                    })
                    data["cong_bo_khoa_hoc"] = pubs
                    save_user_profile(profile_key, data)
                    st.success("✅ Đã thêm công bố!")
                    st.rerun()