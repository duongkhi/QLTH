# ui/skill_ui.py
# Giao diện tạo và quản trị Skill kế toán trên Supabase (bảng app_data / key "hermes_skills_registry")

import streamlit as st

from skill_manager import (
    load_skills_registry,
    list_skills,
    get_skill,
    create_skill,
    update_skill,
    delete_skill,
    add_allowed_user,
    remove_allowed_user,
    can_use_skill,
    generate_skill_from_request,
    SKILL_REGISTRY_KEY,
)
from user_service import load_auth_config


@st.fragment
def _render_skill_creation(username: str) -> None:
    """Form cho phép user nhập yêu cầu tạo Skill mới bằng tiếng Việt, AI sinh mã, rồi lưu.
    Toàn bộ nằm trong fragment → chỉ rerun phần này khi tạo/lưu Skill, không load lại trang khác."""
    st.markdown("### 🛠️ Tạo Skill kế toán mới")
    st.caption(
        "Nhập yêu cầu nghiệp vụ bằng tiếng Việt. Hệ thống sẽ gọi Gemini để tự động sinh tên Skill, mô tả và mã Python, rồi lưu vào kho kỹ năng."
    )

    with st.form("form_create_skill", clear_on_submit=False):
        user_request = st.text_area(
            "Yêu cầu tạo Skill (tiếng Việt)",
            placeholder="Ví dụ: Tính tổng lương tháng của toàn bộ nhân sự và xuất ra bảng tóm tắt.",
            height=120,
        )
        submitted = st.form_submit_button("🤖 Tạo Skill bằng AI", type="primary")

    if submitted:
        if not user_request or not user_request.strip():
            st.warning("Vui lòng nhập yêu cầu tạo Skill.")
            return

        with st.spinner("🤖 Đang gọi AI để sinh Skill..."):
            result = generate_skill_from_request(user_request.strip())

        if not result:
            st.error("Không thể sinh Skill từ yêu cầu. Vui lòng kiểm tra GEMINI_API_KEY / NVIDIA_API_KEY hoặc thử lại sau.")
            return

        st.success("✅ Đã sinh Skill thành công! Bạn có thể chỉnh sửa trước khi lưu.")

        # Hiển thị form chỉnh sửa trước khi lưu
        st.markdown("#### ✏️ Chỉnh sửa trước khi lưu")
        skill_name = st.text_input(
            "Tên Skill (không dấu, viết liền)",
            value=result.get("skill_name", ""),
            key="new_skill_name",
        )
        description = st.text_area(
            "Mô tả nghiệp vụ",
            value=result.get("description", ""),
            height=80,
            key="new_skill_desc",
        )
        code = st.text_area(
            "Mã Python (hàm execute(args, ctx))",
            value=result.get("code", ""),
            height=250,
            key="new_skill_code",
        )

        save_col, _ = st.columns([1, 5])
        with save_col:
            if st.button("💾 Lưu Skill vào kho", type="primary", key="btn_save_new_skill"):
                if not skill_name or not description or not code:
                    st.error("Vui lòng điền đầy đủ tên, mô tả và mã Python.")
                    return
                ok = create_skill(
                    skill_name=skill_name,
                    creator=username,
                    description=description,
                    code=code,
                    allowed_users=[username],
                )
                if ok:
                    st.success(f"✅ Đã lưu Skill '{skill_name}'. Bạn là người tạo và có quyền dùng.")
                    st.session_state.pop("new_skill_name", None)
                    st.session_state.pop("new_skill_desc", None)
                    st.session_state.pop("new_skill_code", None)
                    st.rerun()
                else:
                    st.error("Không lưu được Skill. Tên có thể đã tồn tại hoặc không hợp lệ.")


@st.fragment
def _render_skill_admin(username: str) -> None:
    """Trang quản trị Skill: chỉ Admin xem được. Liệt kê, xem code, xóa, quản lý allowed_users.
    Toàn bộ nằm trong fragment → khi Admin tích chọn checkbox / bấm Lưu quyền, chỉ rerun phần này."""
    st.markdown("### 🛡️ Quản trị Skill (Admin)")
    st.caption(
        "Liệt kê toàn bộ Skill do mọi người dùng đã tạo. Bạn có thể xem mô tả, đọc mã Python, xóa Skill và cấp/Thu hồi quyền dùng cho các tài khoản khác."
    )

    # Lấy danh sách tất cả user để hiển thị trong multiselect cấp quyền
    try:
        auth_cfg = load_auth_config()
        all_users = sorted(auth_cfg.get("users", {}).keys())
    except Exception as e:
        st.error(f"Không đọc được danh sách người dùng: {e}")
        all_users = []

    skills = list_skills()
    if not skills:
        st.info("Chưa có Skill nào trong kho.")
        return

    st.markdown(f"#### 📋 Danh sách Skill ({len(skills)})")

    for skill in skills:
        name = skill.get("skill_name", "")
        with st.expander(f"🔧 {name}  ·  tạo bởi: {skill.get('creator', '?')}", expanded=False):
            c_left, c_right = st.columns([3, 1])

            with c_left:
                st.markdown("**Mô tả:**")
                st.write(skill.get("description", "(không có mô tả)"))
                st.markdown("**Người tạo:**")
                st.write(skill.get("creator", "?"))
                st.markdown("**Danh sách người được phép dùng:**")
                current_users = skill.get("allowed_users", [])
                st.write(", ".join(current_users) if current_users else "(chỉ người tạo)")

                st.markdown("**Mã Python:**")
                st.code(skill.get("code", ""), language="python")

            with c_right:
                st.markdown("#### ⚙️ Quản lý quyền")
                # Multiselect thêm/bớt user
                selected_users = st.multiselect(
                    "Chọn user được phép dùng",
                    options=all_users,
                    default=current_users,
                    key=f"allowed_users_{name}",
                )

                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("💾 Lưu quyền", key=f"save_perm_{name}", width='stretch'):
                        # Tính toán thêm/bớt
                        to_add = [u for u in selected_users if u not in current_users]
                        to_remove = [u for u in current_users if u not in selected_users]
                        for u in to_add:
                            add_allowed_user(name, u)
                        for u in to_remove:
                            remove_allowed_user(name, u)
                        st.success("✅ Đã cập nhật quyền sử dụng.")
                        st.rerun()

                with btn_col2:
                    if st.button("🗑️ Xóa Skill", key=f"del_skill_{name}", type="secondary", width='stretch'):
                        delete_skill(name)
                        st.success(f"✅ Đã xóa Skill '{name}'.")
                        st.rerun()


def render_skill_page(ctx) -> None:
    """Điểm vào chính: hiển thị form tạo Skill hoặc trang quản trị tùy quyền."""
    if ctx.role == "admin":
        tab_create, tab_admin = st.tabs(["🛠️ Tạo Skill mới", "🛡️ Quản trị Skill"])
        with tab_create:
            _render_skill_creation(ctx.username)
        with tab_admin:
            _render_skill_admin(ctx.username)
    else:
        # User thường chỉ thấy tab tạo skill
        _render_skill_creation(ctx.username)
