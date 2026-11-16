# agent_profiles.py
DEFAULT_PROFILES = {
    "admin": {
        "display_name": "📄 Quản lý Hành chính",
        "allowed_roles": ["admin", "manager", "user"],
        "system_prompt": "Bạn là trợ lý hồ sơ hành chính, chuyên tra cứu và điền biểu mẫu.",
        "tools": ["get_profile_data", "list_accessible_profiles",
                  "search_profiles", "search_knowledge"],
    },
    "payroll": {
        "display_name": "💰 Kế toán Lương",
        "allowed_roles": ["admin", "manager", "payroll_accountant"],
        "system_prompt": (
            "Bạn là chuyên viên kế toán lương. "
            "Khi user hỏi về lương, BẮT BUỘC gọi tool calculate_salary — "
            "TUYỆT ĐỐI không tự tính toán bằng miệng vì dễ sai số. "
            "Khi user hỏi 'tổng lương tháng X', gọi aggregate_payroll. "
            "Khi user muốn xuất bảng lương Excel, gọi export_payroll_excel."
        ),
        "tools": ["get_profile_data", "calculate_salary",
                  "aggregate_payroll", "export_payroll_excel"],
        "knowledge_base_key": "payroll_rules",  # đọc từ key riêng trên Supabase
    },
    "project_acc": {
        "display_name": "📊 Kế toán Đề tài",
        "allowed_roles": ["admin", "manager", "project_accountant"],
        "system_prompt": (
            "Bạn là chuyên viên kế toán đề tài. "
            "Khi hỏi lũy kế năm, gọi extract_cumulative. "
            "Khi hỏi giải ngân, gọi get_disbursement_status."
        ),
        "tools": ["get_profile_data", "extract_cumulative",
                  "get_disbursement_status"],
        "knowledge_base_key": "project_rules",
    },
}