import streamlit as st
import pandas as pd
import sqlite3
import json
import base64
import io
from datetime import datetime, date
from urllib.parse import quote

# ==========================================
# 1. إعدادات الصفحة والتصميم (G'day Pro UI)
# ==========================================
st.set_page_config(
    page_title="G'day — قسم دورة الإيرادات",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# تصميم CSS احترافي يدعم العربية (RTL) ويحاكي Slack Pro & Linear & macOS
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800;900&display=swap');

html, body, [class*="css"], .stMarkdown, .stButton button, .stSelectbox, .stTextInput, .stTextArea {
    font-family: 'Tajawal', sans-serif !important;
    direction: rtl;
}

/* إخفاء القوائم الافتراضية المزعجة وتجميل الهوامش */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
.block-container {
    padding-top: 1.2rem !important;
    padding-bottom: 2rem !important;
    max-width: 98% !important;
}

/* الشريط الجانبي بلون Slack Pro / Linear الداكن */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f172a 0%, #1e1b4b 100%) !important;
    border-left: 1px solid rgba(255,255,255,0.08);
}
[data-testid="stSidebar"] * {
    color: #f8fafc !important;
}
[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] > div,
[data-testid="stSidebar"] .stTextInput input {
    background-color: rgba(255, 255, 255, 0.08) !important;
    color: #ffffff !important;
    border: 1px solid rgba(255, 255, 255, 0.15) !important;
    border-radius: 10px !important;
}

/* ترويسة G'day العلوية */
.gday-header {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 60%, #312e81 100%);
    color: white;
    padding: 20px 26px;
    border-radius: 18px;
    margin-bottom: 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 14px;
    box-shadow: 0 12px 28px -8px rgba(15, 23, 42, 0.25);
    border: 1px solid rgba(255,255,255,0.1);
}
.gday-badge {
    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
    color: #fff;
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.5px;
}

/* شريط تنبيهات مهام اليوم */
.today-alert-banner {
    background: linear-gradient(90deg, #fffbeb 0%, #fef3c7 100%);
    border: 1px solid #f59e0b;
    border-right: 6px solid #d97706;
    color: #92400e;
    padding: 12px 18px;
    border-radius: 12px;
    margin-bottom: 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-weight: 700;
    font-size: 0.92rem;
}

/* بطاقات المؤشرات التنفيذية KPI */
.kpi-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
    padding: 16px 18px;
    box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
    transition: all 0.2s ease;
    height: 100%;
}
.kpi-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
    border-color: #cbd5e1;
}
.kpi-title {
    color: #64748b;
    font-size: 0.82rem;
    font-weight: 700;
    margin-bottom: 6px;
}
.kpi-value {
    color: #0f172a;
    font-size: 1.65rem;
    font-weight: 900;
    line-height: 1.2;
}
.kpi-sub {
    font-size: 0.76rem;
    font-weight: 700;
    margin-top: 6px;
}

/* بطاقات مسار الإنجاز (Workflow Pipeline) */
.stage-header {
    padding: 12px 16px;
    border-radius: 12px;
    font-weight: 800;
    font-size: 0.95rem;
    margin-bottom: 12px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.pipeline-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-right: 4px solid #6366f1;
    border-radius: 14px;
    padding: 14px;
    margin-bottom: 10px;
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
}
.pipeline-title {
    font-weight: 800;
    color: #0f172a;
    font-size: 0.95rem;
    margin-bottom: 6px;
}
.stakeholder-pill {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 8px 10px;
    margin: 8px 0;
    font-size: 0.8rem;
}

/* أزرار التواصل السريع (اتصال، واتساب، إيميل) */
.contact-links a {
    text-decoration: none !important;
    display: inline-block;
    padding: 3px 9px;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 700;
    margin-left: 4px;
}
.btn-call { background: #eff6ff; color: #1d4ed8 !important; border: 1px solid #bfdbfe; }
.btn-wa { background: #ecfdf5; color: #047857 !important; border: 1px solid #a7f3d0; }
.btn-mail { background: #f5f3ff; color: #6d28d9 !important; border: 1px solid #ddd6fe; }

/* تحسين التبويبات */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background-color: #f1f5f9;
    padding: 6px;
    border-radius: 14px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 10px !important;
    padding: 8px 18px !important;
    font-weight: 800 !important;
}
.stTabs [aria-selected="true"] {
    background-color: #ffffff !important;
    color: #0f172a !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06) !important;
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. قاعدة البيانات التشاركية (SQLite)
# ==========================================
DB_FILE = "gday_rcm_workspace.db"

def get_conn():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # جدول الأعضاء
    c.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id TEXT PRIMARY KEY,
            name TEXT,
            role TEXT,
            access_level TEXT,
            avatar TEXT,
            specialty TEXT
        )
    """)

    # جدول المشاريع / القنوات
    c.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT,
            icon TEXT,
            description TEXT
        )
    """)

    # جدول الجهات والأشخاص المتواصل معهم (Stakeholders CRM)
    c.execute("""
        CREATE TABLE IF NOT EXISTS stakeholders (
            id TEXT PRIMARY KEY,
            name TEXT,
            org TEXT,
            phone TEXT,
            email TEXT,
            notes TEXT
        )
    """)

    # جدول المهام (بدون عمود اعتماد - مع الوقت المتوقع والجهة والملف المرفق)
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            channel_id TEXT,
            assignee TEXT,
            status TEXT,
            priority TEXT,
            stakeholder_id TEXT,
            est_hours REAL,
            due_date TEXT,
            file_id TEXT,
            notes TEXT,
            created_at TEXT
        )
    """)

    # جدول مكتبة الملفات (G'day Drive: Docs, Sheets, PDFs)
    c.execute("""
        CREATE TABLE IF NOT EXISTS drive_files (
            id TEXT PRIMARY KEY,
            title TEXT,
            file_type TEXT,
            channel_id TEXT,
            owner TEXT,
            starred INTEGER DEFAULT 0,
            content TEXT,
            binary_b64 TEXT,
            updated_at TEXT
        )
    """)

    # جدول المحادثات الفورية
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT,
            sender TEXT,
            role TEXT,
            text TEXT,
            attachment_id TEXT,
            created_at TEXT
        )
    """)

    # تعبئة البيانات الأولية لقسم دورة الإيرادات إذا كانت القاعدة فارغة
    c.execute("SELECT COUNT(*) FROM members")
    if c.fetchone()[0] == 0:
        default_members = [
            ("m_abdullah", "عبدالله", "أدمن المنصة • مشرف دورة الإيرادات", "admin", "👨‍💼", "الإشراف العام والتحليل"),
            ("m_waleed", "الوليد", "مدير قسم دورة الإيرادات", "director", "👔", "القيادة والتوجيه الاستراتيجي"),
            ("m_1", "سلمان الحربي", "أخصائي مطالبات نفيس NPHIES", "member", "⚡", "رفع ومطابقة مطالبات نفيس"),
            ("m_2", "ريم القحطاني", "أخصائية إدارة المرفوضات", "member", "🛡️", "تحليل المرفوضات والاستئناف"),
            ("m_3", "فهد العتيبي", "أخصائي الترميز الطبي ICD-10", "member", "🧬", "التدقيق السريري والترميز"),
            ("m_4", "نورة الدوسري", "منسقة الأهلية والموافقات", "member", "✅", "التحقق من التغطية التأمينية"),
            ("m_5", "طلال الشمري", "محاسب التحصيل والفوترة", "member", "💳", "المطابقات المالية والتحصيل"),
            ("m_6", "شهد المطيري", "محللة بيانات دورة الإيرادات", "member", "📊", "مؤشرات الأداء والتقارير الأسبوعية"),
        ]
        c.executemany("INSERT INTO members VALUES (?,?,?,?,?,?)", default_members)

    c.execute("SELECT COUNT(*) FROM channels")
    if c.fetchone()[0] == 0:
        default_channels = [
            ("ch_nphies", "المطالبات-ومبيعات-نفيس", "⚡", "متابعة رفع المطالبات اليومية عبر منصة نفيس ومعالجة أخطاء الربط"),
            ("ch_rejections", "إدارة-المرفوضات-والاعتراضات", "🛡️", "حصر المرفوضات الطبية والفنية ورفع خطابات الاعتراض قبل انتهاء المهلة"),
            ("ch_coding", "الترميز-الطبي-والتوثيق", "🧬", "مراجعة اكتمال التوثيق الطبي والترميز ICD-10-AM في المراكز الصحية"),
            ("ch_eligibility", "الأهلية-والموافقات-المسبقة", "✅", "التحقق من أهلية العلاج والموافقات المسبقة للشركات التأمينية"),
            ("ch_weekly", "التقارير-الأسبوعية-للأعضاء", "📊", "تسليم ومتابعة التقارير التشغيلية الأسبوعية للأعضاء الـ 6"),
            ("ch_circulars", "التعاميم-والتحديثات-المالية", "📢", "التعاميم الرسمية ولوائح مجلس الضمان الصحي واللوائح المالية"),
        ]
        c.executemany("INSERT INTO channels VALUES (?,?,?,?)", default_channels)

    c.execute("SELECT COUNT(*) FROM stakeholders")
    if c.fetchone()[0] == 0:
        default_stakeholders = [
            ("st_1", "أ. ماجد الحربي", "مجلس الضمان الصحي / نفيس", "966501112233", "nphies-support@chi.gov.sa", "الدعم الفني للمطالبات المعلقة - تحويلة 402"),
            ("st_2", "أ. طارق السالم", "بوبا العربية للتأمين", "966552223344", "claims.rcm@bupa.com.sa", "مسؤول تسوية المرفوضات والاعتراضات الطبية"),
            ("st_3", "د. هند العلي", "التعاونية للتأمين (Tawuniya)", "966543334455", "medical.audit@tawuniya.com.sa", "المراجعات السريرية والموافقات المسبقة"),
            ("st_4", "أ. نايف العنزي", "إدارة الشؤون المالية بالتجمع", "966564445566", "finance.phc@health.gov.sa", "مطابقة الحوالات البنكية والإيرادات الشهرية"),
            ("st_5", "د. ياسر الشهري", "المدير الطبي للمراكز الأول