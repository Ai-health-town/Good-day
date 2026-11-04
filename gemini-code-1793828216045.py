import streamlit as st
import streamlit.components.v1 as components

# إعدادات الصفحة لتعمل بملء الشاشة تماماً مثل تطبيقات Slack و Linear
st.set_page_config(
    page_title="G'day — مساحة العمل الذكية",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# إخفاء كافة قوائم وحواف Streamlit الافتراضية للحفاظ على جمال الواجهة
st.markdown("""
    <style>
        #MainMenu, header, footer, [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] {
            display: none !important;
            visibility: hidden !important;
        }
        .block-container, [data-testid="stAppViewBlockContainer"] {
            padding: 0 !important;
            margin: 0 !important;
            max-width: 100% !important;
        }
        .stApp, body, html {
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
            background-color: #0F172A !important;
        }
        iframe {
            width: 100vw !important;
            height: 100vh !important;
            border: none !important;
            display: block !important;
        }
    </style>
""", unsafe_allow_html=True)

# الكود الكامل لمنصة G'day Workspace (شامل تسجيل الدخول، بوابة الـ AI، المهام، مسار الإنجاز، الدردشة مع الحذف، ومكتبة الملفات)
GDAY_APP_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>G'day — مساحة العمل الذكية</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" />
  <style>
    * { font-family: 'IBM Plex Sans Arabic', sans-serif; box-sizing: border-box; }
    body { background: #F8FAFC; color: #0F172A; margin: 0; padding: 0; overflow: hidden; }
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-thumb { background: #CBD5E1; border-radius: 99px; }
    .gday-sidebar { background: linear-gradient(180deg, #1E1026 0%, #130919 100%); }
    .ch-item { transition: all 0.15s ease; }
    .ch-item:hover { background: rgba(255,255,255,0.08); }
    .ch-active { background: linear-gradient(90deg, #0D9488 0%, #0284C7 100%) !important; color: #fff !important; font-weight: 600; }
    .inline-input { background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 3px 6px; width: 100%; transition: 0.15s; }
    .inline-input:hover { background: #F1F5F9; border-color: #E2E8F0; }
    .inline-input:focus { background: #fff; border-color: #0D9488; outline: none; box-shadow: 0 0 0 3px rgba(13,148,136,0.12); }
    .inline-select { appearance: none; cursor: pointer; border-radius: 7px; padding: 3px 10px; font-size: 11px; font-weight: 700; border: 1px solid transparent; }
    .s-new { background: #F1F5F9; color: #475569; border-color: #CBD5E1; }
    .s-doing { background: #EFF6FF; color: #1D4ED8; border-color: #BFDBFE; }
    .s-waiting { background: #FFFBEB; color: #B45309; border-color: #FDE68A; }
    .s-done { background: #ECFDF5; color: #047857; border-color: #A7F3D0; }
    .p-high { background: #FEF2F2; color: #DC2626; border-color: #FECACA; }
    .p-med { background: #FFFBEB; color: #D97706; border-color: #FDE68A; }
    .p-low { background: #F8FAFC; color: #64748B; border-color: #E2E8F0; }
    .sheet-cell { border: 1px solid #E2E8F0; padding: 6px 8px; min-width: 110px; font-size: 12px; outline: none; background: #fff; }
    .sheet-cell:focus { border: 2px solid #0D9488; background: #F0FDFA; }
  </style>
</head>
<body class="h-screen w-screen flex flex-col select-none">

  <!-- ================= شاشة تسجيل الدخول الذكية (الأعضاء + متصفح الـ AI) ================= -->
  <div id="login-screen" class="fixed inset-0 z-[100] flex items-center justify-center p-4" style="background: radial-gradient(circle at top right, #134E4A 0%, #1E1026 55%, #09050D 100%);">
    <div class="w-full max-w-md bg-white/95 backdrop-blur-xl rounded-3xl shadow-2xl border border-white/20 overflow-hidden">
      <div class="p-6 pb-5 bg-gradient-to-l from-slate-900 via-purple-950 to-teal-950 text-white relative">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <div class="w-11 h-11 rounded-2xl bg-gradient-to-br from-teal-400 to-sky-500 flex items-center justify-center shadow-lg font-black text-xl">G'</div>
            <div>
              <div class="flex items-center gap-2">
                <h1 class="text-xl font-black tracking-tight">G'day Workspace</h1>
                <span class="text-[10px] bg-teal-500/20 text-teal-300 border border-teal-400/30 px-2 py-0.5 rounded-full font-bold">PRO + AI</span>
              </div>
              <p class="text-xs text-slate-300 mt-0.5">بوابة الدخول الآمن للأعضاء ووكيل الذكاء الاصطناعي</p>
            </div>
          </div>
        </div>
      </div>

      <form id="login-form" onsubmit="handleLoginSubmit(event)" class="p-6 space-y-4">
        <div id="login-error" class="hidden bg-rose-50 border border-rose-200 text-rose-700 text-xs font-bold px-3.5 py-2.5 rounded-xl">
          <i class="fa-solid fa-circle-exclamation ml-1"></i> اسم المستخدم أو رمز الدخول غير صحيح
        </div>

        <div>
          <label class="block text-xs font-bold text-slate-700 mb-1.5">اسم المستخدم (Username)</label>
          <input id="login-username" name="username" type="text" required autocomplete="username" aria-label="Username" placeholder="مثال: admin أو waleed أو ai" class="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 bg-slate-50 focus:bg-white focus:border-teal-500 focus:outline-none text-sm font-bold text-slate-800" dir="ltr" />
        </div>

        <div>
          <label class="block text-xs font-bold text-slate-700 mb-1.5">رمز الدخول (Password / PIN)</label>
          <input id="login-password" name="password" type="password" required autocomplete="current-password" aria-label="Password" placeholder="••••" class="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 bg-slate-50 focus:bg-white focus:border-teal-500 focus:outline-none text-sm font-bold text-slate-800" dir="ltr" />
        </div>

        <div class="flex items-center justify-between pt-1">
          <label class="flex items-center gap-2 cursor-pointer text-xs font-semibold text-slate-600">
            <input id="login-remember" type="checkbox" checked class="w-4 h-4 rounded text-teal-600" />
            <span>حفظ الدخول دائماً على هذا الجهاز والمتصفح</span>
          </label>
        </div>

        <button id="login-submit-btn" type="submit" aria-label="Login Submit" class="w-full py-3 rounded-xl bg-gradient-to-l from-teal-600 to-sky-600 hover:from-teal-500 hover:to-sky-500 text-white font-bold text-sm shadow-lg transition flex items-center justify-center gap-2">
          <span>تسجيل الدخول للمنصة</span>
          <i class="fa-solid fa-arrow-left text-xs"></i>
        </button>

        <div class="pt-3 border-t border-slate-100">
          <p class="text-[11px] font-bold text-slate-400 mb-2">دخول سريع للتجربة (أو لمتصفح الـ AI):</p>
          <div id="quick-login-chips" class="flex flex-wrap gap-1.5"></div>
        </div>
      </form>
    </div>
  </div>

  <!-- ================= الواجهة الرئيسية ================= -->
  <div class="flex flex-1 overflow-hidden">

    <!-- القائمة الجانبية -->
    <aside class="gday-sidebar w-64 text-slate-200 flex flex-col justify-between shrink-0 border-l border-white/10 select-none">
      <div>
        <div class="h-16 px-4 flex items-center justify-between border-b border-white/10">
          <div class="flex items-center gap-2.5">
            <div class="w-9 h-9 rounded-xl bg-gradient-to-br from-teal-400 to-sky-500 flex items-center justify-center text-white font-black text-base shadow">G'</div>
            <div>
              <div class="flex items-center gap-1.5">
                <span class="font-black text-white text-sm tracking-tight">G'day</span>
                <span class="text-[9px] bg-teal-500/20 text-teal-300 px-1.5 py-0.5 rounded font-bold">PRO</span>
              </div>
              <p class="text-[10px] text-slate-400">مساحة العمل والمشاريع</p>
            </div>
          </div>
          <button onclick="openNewTaskModal()" class="w-8 h-8 rounded-lg bg-white/10 hover:bg-teal-500 text-white flex items-center justify-center transition" title="مهمة جديدة">
            <i class="fa-solid fa-plus text-xs"></i>
          </button>
        </div>

        <!-- التنقل الرئيسي -->
        <div class="p-3 space-y-1 border-b border-white/10">
          <button onclick="switchMainView('workspace')" id="nav-workspace" class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-bold text-white bg-white/10 transition">
            <span class="flex items-center gap-2"><i class="fa-solid fa-layer-group text-teal-400"></i> مساحة المشاريع</span>
            <span id="side-total-tasks" class="text-[10px] bg-white/10 px-1.5 py-0.5 rounded">0</span>
          </button>
          <button onclick="switchMainView('drive')" id="nav-drive" class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-medium text-slate-300 hover:bg-white/5 transition">
            <span class="flex items-center gap-2"><i class="fa-solid fa-folder-open text-amber-400"></i> مكتبة الملفات (Drive)</span>
            <span id="side-total-files" class="text-[10px] bg-white/10 px-1.5 py-0.5 rounded">0</span>
          </button>
          <button onclick="switchMainView('stakeholders')" id="nav-stakeholders" class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-medium text-slate-300 hover:bg-white/5 transition">
            <span class="flex items-center gap-2"><i class="fa-solid fa-address-book text-sky-400"></i> جهات التواصل</span>
            <span id="side-total-stk" class="text-[10px] bg-white/10 px-1.5 py-0.5 rounded">0</span>
          </button>
          <button onclick="switchMainView('ai_hub')" id="nav-ai_hub" data-ai-action="open-ai-hub" class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-medium text-emerald-300 hover:bg-emerald-500/10 border border-emerald-500/20 transition">
            <span class="flex items-center gap-2"><i class="fa-solid fa-robot text-emerald-400"></i> بوابة الـ AI والتحكم</span>
            <span class="text-[9px] bg-emerald-500/20 text-emerald-300 px-1.5 py-0.5 rounded font-bold">متصل</span>
          </button>
        </div>

        <!-- القنوات والمشاريع -->
        <div class="px-3 pt-3 pb-1 flex items-center justify-between">
          <span class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">المشاريع والقنوات</span>
          <button onclick="openProjectModal()" class="text-[10px] text-teal-400 hover:text-teal-300 font-bold">+ مشروع</button>
        </div>
        <div id="sidebar-projects" class="px-2 space-y-0.5 max-h-52 overflow-y-auto"></div>

        <!-- الأعضاء -->
        <div class="px-3 pt-4 pb-1 flex items-center justify-between">
          <span class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">الفريق والحسابات</span>
          <button onclick="openMembersModal()" class="text-[10px] text-teal-400 hover:text-teal-300 font-bold">إدارة الحسابات</button>
        </div>
        <div id="sidebar-members" class="px-2 space-y-0.5 max-h-44 overflow-y-auto"></div>
      </div>

      <!-- بطاقة المستخدم المسجل -->
      <div class="p-3 border-t border-white/10 bg-black/25 flex items-center justify-between">
        <div class="flex items-center gap-2 min-w-0">
          <div id="current-user-avatar" class="w-8 h-8 rounded-lg bg-teal-600 flex items-center justify-center text-white font-bold text-xs shrink-0">ع</div>
          <div class="truncate">
            <div id="current-user-name" class="text-xs font-bold text-white truncate">عبدالله</div>
            <div id="current-user-role" class="text-[10px] text-teal-300 truncate">مدير النظام (Admin)</div>
          </div>
        </div>
        <button onclick="logoutUser()" title="تسجيل الخروج" class="px-2.5 py-1.5 rounded-lg bg-rose-500/15 hover:bg-rose-500 text-rose-300 hover:text-white text-xs font-bold transition">
          <i class="fa-solid fa-power-off"></i>
        </button>
      </div>
    </aside>

    <!-- المحتوى الرئيسي -->
    <main class="flex-1 flex flex-col overflow-hidden bg-slate-50">

      <!-- الشريط العلوي -->
      <header class="h-16 bg-white border-b border-slate-200 px-6 flex items-center justify-between shrink-0">
        <div class="flex items-center gap-4">
          <div>
            <div class="flex items-center gap-2">
              <h2 id="active-project-title" class="text-base font-black text-slate-900"># المشاريع والمبادرات الرئيسية</h2>
              <button onclick="editCurrentProject()" class="text-slate-400 hover:text-teal-600 text-xs" title="تعديل المشروع"><i class="fa-solid fa-pen"></i></button>
            </div>
            <p id="active-project-desc" class="text-[11px] text-slate-500">متابعة المهام، المسؤولين، والوقت المتوقع مع جهات التواصل</p>
          </div>
        </div>

        <!-- التبويبات الوسطية للمشروع -->
        <div id="workspace-tabs" class="flex items-center bg-slate-100 p-1 rounded-xl border border-slate-200/70">
          <button onclick="switchSubTab('table')" id="subtab-table" class="px-3.5 py-1.5 rounded-lg text-xs font-bold bg-white text-slate-900 shadow-sm transition">
            <i class="fa-solid fa-table-list text-teal-600 ml-1"></i> جدول المهام
          </button>
          <button onclick="switchSubTab('pipeline')" id="subtab-pipeline" class="px-3.5 py-1.5 rounded-lg text-xs font-semibold text-slate-600 hover:text-slate-900 transition">
            <i class="fa-solid fa-diagram-next text-sky-600 ml-1"></i> مسار الإنجاز
          </button>
          <button onclick="switchSubTab('chat')" id="subtab-chat" class="px-3.5 py-1.5 rounded-lg text-xs font-semibold text-slate-600 hover:text-slate-900 transition">
            <i class="fa-solid fa-comments text-indigo-600 ml-1"></i> المحادثة <span id="chat-badge" class="mr-1 px-1.5 py-0.2 bg-indigo-100 text-indigo-700 rounded-full text-[10px]">0</span>
          </button>
        </div>

        <!-- أدوات اليسار -->
        <div class="flex items-center gap-2.5">
          <div class="relative">
            <input id="global-search" oninput="renderAll()" type="text" placeholder="بحث سريع في المهام..." class="w-48 pl-3 pr-8 py-1.5 rounded-xl bg-slate-100 border border-slate-200 text-xs focus:bg-white focus:border-teal-500 focus:outline-none" />
            <i class="fa-solid fa-magnifying-glass absolute right-2.5 top-2.5 text-slate-400 text-xs"></i>
          </div>
          <button onclick="filterTodayTasks()" id="today-alert-btn" class="px-3 py-1.5 rounded-xl bg-amber-50 hover:bg-amber-100 border border-amber-200 text-amber-800 text-xs font-bold flex items-center gap-1.5 transition">
            <i class="fa-solid fa-bell text-amber-500"></i>
            <span>مهام اليوم:</span>
            <span id="today-count-badge" class="font-black">0</span>
          </button>
          <button onclick="openNewTaskModal()" class="px-3.5 py-1.5 rounded-xl bg-teal-600 hover:bg-teal-500 text-white text-xs font-bold shadow-sm transition flex items-center gap-1.5">
            <i class="fa-solid fa-plus"></i> مهمة جديدة
          </button>
        </div>
      </header>

      <!-- شريط المؤشرات المختصر -->
      <div class="bg-white/70 border-b border-slate-200/80 px-6 py-2.5 grid grid-cols-4 gap-3 shrink-0">
        <div class="flex items-center justify-between bg-slate-50 px-3.5 py-2 rounded-xl border border-slate-200/60">
          <div>
            <div class="text-[10px] font-bold text-slate-400">مهام اليوم</div>
            <div id="kpi-today" class="text-sm font-black text-slate-800">0 مهام</div>
          </div>
          <div class="w-8 h-8 rounded-lg bg-amber-100 text-amber-600 flex items-center justify-center"><i class="fa-solid fa-calendar-day text-xs"></i></div>
        </div>
        <div class="flex items-center justify-between bg-slate-50 px-3.5 py-2 rounded-xl border border-slate-200/60">
          <div>
            <div class="text-[10px] font-bold text-slate-400">بانتظار رد الجهات</div>
            <div id="kpi-waiting" class="text-sm font-black text-amber-700">0 مهام</div>
          </div>
          <div class="w-8 h-8 rounded-lg bg-orange-100 text-orange-600 flex items-center justify-center"><i class="fa-solid fa-hourglass-half text-xs"></i></div>
        </div>
        <div class="flex items-center justify-between bg-slate-50 px-3.5 py-2 rounded-xl border border-slate-200/60">
          <div>
            <div class="text-[10px] font-bold text-slate-400">إجمالي الوقت المقدر</div>
            <div id="kpi-hours" class="text-sm font-black text-sky-700">0 ساعة</div>
          </div>
          <div class="w-8 h-8 rounded-lg bg-sky-100 text-sky-600 flex items-center justify-center"><i class="fa-solid fa-clock text-xs"></i></div>
        </div>
        <div class="flex items-center justify-between bg-slate-50 px-3.5 py-2 rounded-xl border border-slate-200/60">
          <div>
            <div class="text-[10px] font-bold text-slate-400">نسبة الإنجاز</div>
            <div id="kpi-progress" class="text-sm font-black text-teal-700">0%</div>
          </div>
          <div class="w-8 h-8 rounded-lg bg-teal-100 text-teal-600 flex items-center justify-center"><i class="fa-solid fa-chart-pie text-xs"></i></div>
        </div>
      </div>

      <!-- حاوية العروض المتعددة -->
      <div class="flex-1 overflow-y-auto p-6">

        <!-- 1. عرض جدول المهام (Inline Editing) -->
        <div id="view-table" class="space-y-4">
          <!-- إضافة مهمة سريعة بضغطة زر -->
          <form onsubmit="handleQuickTaskAdd(event)" class="bg-white p-2.5 rounded-2xl shadow-sm border border-slate-200 flex items-center gap-2">
            <i class="fa-solid fa-bolt text-teal-500 mr-2"></i>
            <input id="quick-task-title" type="text" required placeholder="اكتب مهمة جديدة هنا واضغط Enter للإضافة الفورية..." class="flex-1 text-xs font-semibold text-slate-800 bg-transparent focus:outline-none" />
            <select id="quick-task-assignee" class="text-xs bg-slate-100 px-2.5 py-1.5 rounded-lg font-semibold text-slate-700"></select>
            <select id="quick-task-stk" class="text-xs bg-slate-100 px-2.5 py-1.5 rounded-lg font-semibold text-slate-700"></select>
            <select id="quick-task-time" class="text-xs bg-slate-100 px-2.5 py-1.5 rounded-lg font-semibold text-slate-700">
              <option value="0.5">30 دقيقة</option>
              <option value="1" selected>1 ساعة</option>
              <option value="2">ساعتان</option>
              <option value="4">4 ساعات</option>
              <option value="8">يوم عمل (8 س)</option>
            </select>
            <button type="submit" class="px-4 py-1.5 bg-slate-900 hover:bg-teal-600 text-white rounded-xl text-xs font-bold transition">إضافة</button>
          </form>

          <!-- الجدول -->
          <div class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            <table class="w-full text-right border-collapse">
              <thead>
                <tr class="bg-slate-50 border-b border-slate-200 text-[11px] font-bold text-slate-500">
                  <th class="py-3 px-4 w-[28%]">المهمة</th>
                  <th class="py-3 px-3">المسؤول</th>
                  <th class="py-3 px-3">المرحلة</th>
                  <th class="py-3 px-3">الأولوية</th>
                  <th class="py-3 px-3">الشخص / الجهة (Stakeholder)</th>
                  <th class="py-3 px-3">الوقت المتوقع</th>
                  <th class="py-3 px-3">التاريخ</th>
                  <th class="py-3 px-3">ملف مرفق</th>
                  <th class="py-3 px-3 text-center">إجراء</th>
                </tr>
              </thead>
              <tbody id="tasks-tbody" class="divide-y divide-slate-100 text-xs"></tbody>
            </table>
          </div>
        </div>

        <!-- 2. عرض مسار الإنجاز (Workflow Pipeline) -->
        <div id="view-pipeline" class="hidden grid grid-cols-4 gap-4 h-full"></div>

        <!-- 3. عرض المحادثة الفورية مع التحكم بحذف الدردشات -->
        <div id="view-chat" class="hidden flex flex-col h-[calc(100vh-210px)] bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
          <div class="px-5 py-3 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
            <div class="flex items-center gap-2">
              <i class="fa-solid fa-hashtag text-teal-600"></i>
              <span id="chat-header-title" class="text-xs font-black text-slate-800">محادثة المشروع</span>
              <span class="text-[11px] text-slate-400">• يمكنك تحويل أي رسالة إلى مهمة أو حذف الرسائل</span>
            </div>
            <div class="flex items-center gap-2">
              <button onclick="clearChannelChat()" class="px-3 py-1.5 rounded-xl bg-rose-50 hover:bg-rose-600 text-rose-600 hover:text-white border border-rose-200 text-xs font-bold transition flex items-center gap-1.5">
                <i class="fa-solid fa-trash-can"></i> مسح محادثة القناة بالكامل
              </button>
            </div>
          </div>

          <div id="chat-messages" class="flex-1 overflow-y-auto p-5 space-y-3 bg-slate-50/40"></div>

          <form onsubmit="handleSendChat(event)" class="p-3 bg-white border-t border-slate-200 flex items-center gap-2">
            <input id="chat-input" type="text" required placeholder="اكتب رسالتك هنا أو وجّه الفريق..." class="flex-1 px-4 py-2.5 rounded-xl bg-slate-100 focus:bg-white border border-slate-200 focus:border-teal-500 text-xs font-semibold focus:outline-none" />
            <button type="submit" class="px-5 py-2.5 rounded-xl bg-teal-600 hover:bg-teal-500 text-white text-xs font-bold transition flex items-center gap-1.5">
              <span>إرسال</span>
              <i class="fa-solid fa-paper-plane"></i>
            </button>
          </form>
        </div>

        <!-- 4. مكتبة الملفات (G'day Drive) -->
        <div id="view-drive" class="hidden space-y-4">
          <div class="bg-white p-4 rounded-2xl border border-slate-200 flex items-center justify-between">
            <div>
              <h3 class="text-sm font-black text-slate-900">📁 مكتبة الملفات والمستندات التفاعلية (G'day Drive)</h3>
              <p class="text-xs text-slate-500">افتح وعدّل مستندات Word وجداول Excel وملفات PDF مباشرة داخل المنصة بدون الخروج منها</p>
            </div>
            <div class="flex items-center gap-2">
              <button onclick="createNewDriveFile('doc')" class="px-3 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold">+ مستند Word</button>
              <button onclick="createNewDriveFile('sheet')" class="px-3 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold">+ جدول Excel</button>
              <label class="px-3 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold cursor-pointer">
                <i class="fa-solid fa-upload ml-1"></i> رفع ملف من جهازك
                <input type="file" class="hidden" onchange="handleFileUpload(event)" />
              </label>
            </div>
          </div>
          <div id="drive-grid" class="grid grid-cols-3 gap-4"></div>
        </div>

        <!-- 5. دليل جهات التواصل (Stakeholders) -->
        <div id="view-stakeholders" class="hidden space-y-4">
          <div class="bg-white p-4 rounded-2xl border border-slate-200 flex items-center justify-between">
            <div>
              <h3 class="text-sm font-black text-slate-900">📇 دليل الأشخاص والجهات (Stakeholders CRM)</h3>
              <p class="text-xs text-slate-500">تواصل مباشر عبر الاتصال أو الواتساب أو البريد الإلكتروني مع ربطهم بالمهام</p>
            </div>
            <button onclick="openStakeholderModal()" class="px-4 py-2 rounded-xl bg-teal-600 hover:bg-teal-500 text-white text-xs font-bold">+ إضافة شخص / جهة</button>
          </div>
          <div id="stakeholders-grid" class="grid grid-cols-3 gap-4"></div>
        </div>

        <!-- 6. بوابة الـ AI ومتصفح الـ AI الذكي -->
        <div id="view-ai_hub" class="hidden space-y-4">
          <div class="bg-gradient-to-l from-slate-900 via-teal-950 to-slate-900 text-white p-5 rounded-2xl shadow-lg flex items-center justify-between">
            <div>
              <div class="flex items-center gap-2">
                <span class="px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-400/30 text-[11px] font-bold">AI Agent Bridge Active</span>
                <h3 class="text-base font-black">🤖 بوابة متصفح الـ AI والمساعد الذكي</h3>
              </div>
              <p class="text-xs text-slate-300 mt-1">يمكن لمتصفح الـ AI الدخول بحساب <code class="bg-white/10 px-1.5 py-0.5 rounded text-teal-300">ai</code> ورمز <code class="bg-white/10 px-1.5 py-0.5 rounded text-teal-300">1111</code> لقراءة البيانات وتنفيذ التعديلات وإدارة المهام تلقائياً.</p>
            </div>
            <button onclick="refreshAiSnapshot()" class="px-4 py-2 rounded-xl bg-teal-500 hover:bg-teal-400 text-slate-950 font-black text-xs transition">
              <i class="fa-solid fa-rotate ml-1"></i> تحديث قراءة الـ AI
            </button>
          </div>

          <div class="grid grid-cols-2 gap-4">
            <!-- صندوق أوامر الـ AI المباشرة -->
            <div class="bg-white p-4 rounded-2xl border border-slate-200 space-y-3">
              <h4 class="text-xs font-black text-slate-800 flex items-center gap-2">
                <i class="fa-solid fa-terminal text-teal-600"></i> منفّذ أوامر الـ AI الفوري (أوامر نصية أو JSON)
              </h4>
              <p class="text-[11px] text-slate-500">يستطيع متصفح الـ AI (أو أنت) كتابة أمر مباشر هنا ليتم تنفيذه فوراً على المهام أو الدردشة:</p>
              <textarea id="ai-command-input" rows="4" aria-label="AI Command Input" placeholder="مثال: أضف مهمة: إعداد خطة الأسبوع القادم | المسؤول: عبدالله | الوقت: 2&#10;أو اكتب: لخص مهام اليوم في المحادثة" class="w-full p-3 rounded-xl bg-slate-50 border border-slate-200 text-xs font-semibold focus:bg-white focus:border-teal-500 focus:outline-none"></textarea>
              <div class="flex flex-wrap gap-2">
                <button id="ai-execute-btn" onclick="executeAiCommand()" aria-label="Execute AI Command" class="px-4 py-2 rounded-xl bg-teal-600 hover:bg-teal-500 text-white text-xs font-bold">
                  ⚡ تنفيذ الأمر الآن
                </button>
                <button onclick="aiQuickSummaryToChat()" class="px-3 py-2 rounded-xl bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-xs font-bold">
                  📊 إرسال ملخص ذكي بالمحادثة
                </button>
                <button onclick="aiAutoPrioritize()" class="px-3 py-2 rounded-xl bg-amber-50 hover:bg-amber-100 text-amber-800 text-xs font-bold">
                  🎯 ترتيب أولويات مهام اليوم تلقائياً
                </button>
              </div>
              <div id="ai-command-result" class="hidden p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-bold"></div>
            </div>

            <!-- قراءة حالة المنصة الكاملة لمتصفح الـ AI -->
            <div class="bg-white p-4 rounded-2xl border border-slate-200 space-y-3">
              <div class="flex items-center justify-between">
                <h4 class="text-xs font-black text-slate-800 flex items-center gap-2">
                  <i class="fa-solid fa-database text-sky-600"></i> حالة المنصة الحية لمتصفح الـ AI (JSON Context)
                </h4>
                <button onclick="copyAiSnapshot()" class="text-[11px] text-teal-600 font-bold hover:underline">نسخ البيانات</button>
              </div>
              <textarea id="ai-context-snapshot" readonly rows="8" aria-label="AI Workspace State JSON" class="w-full p-3 rounded-xl bg-slate-900 text-teal-300 font-mono text-[11px] focus:outline-none" dir="ltr"></textarea>
            </div>
          </div>
        </div>

      </div>
    </main>
  </div>

  <!-- ================= نافذة محرر الملفات (Word / Excel / PDF) ================= -->
  <div id="file-editor-modal" class="hidden fixed inset-0 z-50 bg-slate-900/70 backdrop-blur-sm flex items-center justify-center p-6">
    <div class="bg-white w-full max-w-4xl h-[82vh] rounded-3xl shadow-2xl border border-slate-200 flex flex-col overflow-hidden">
      <div class="px-6 py-4 bg-slate-900 text-white flex items-center justify-between">
        <div class="flex items-center gap-3">
          <span id="editor-file-icon" class="text-xl">📝</span>
          <input id="editor-file-title" type="text" class="bg-transparent font-black text-sm text-white border-b border-transparent focus:border-teal-400 focus:outline-none" />
        </div>
        <div class="flex items-center gap-2">
          <button onclick="shareCurrentFileToChat()" class="px-3 py-1.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold">
            <i class="fa-solid fa-share-nodes ml-1"></i> مشاركة في المحادثة
          </button>
          <button onclick="saveCurrentFile()" class="px-4 py-1.5 rounded-xl bg-teal-500 hover:bg-teal-400 text-slate-950 text-xs font-black">
            حفظ التعديلات
          </button>
          <button onclick="closeFileEditor()" class="w-8 h-8 rounded-xl bg-white/10 hover:bg-rose-500 text-white flex items-center justify-center">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
      </div>
      <div id="editor-body" class="flex-1 overflow-y-auto p-6 bg-slate-50"></div>
    </div>
  </div>

  <!-- ================= نافذة إدارة الأعضاء والحسابات (مع حساب الـ AI) ================= -->
  <div id="members-modal" class="hidden fixed inset-0 z-50 bg-slate-900/70 backdrop-blur-sm flex items-center justify-center p-4">
    <div class="bg-white w-full max-w-2xl rounded-3xl shadow-2xl border border-slate-200 overflow-hidden">
      <div class="px-6 py-4 bg-slate-900 text-white flex items-center justify-between">
        <h3 class="text-sm font-black">👥 إدارة حسابات الأعضاء ووكيل الـ AI (تسجيل الدخول والصلاحيات)</h3>
        <button onclick="closeMembersModal()" class="text-slate-400 hover:text-white"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div class="p-6 space-y-4 max-h-[75vh] overflow-y-auto">
        <form onsubmit="handleSaveMember(event)" class="grid grid-cols-5 gap-2 bg-slate-50 p-3 rounded-2xl border border-slate-200">
          <input id="mem-name" type="text" required placeholder="الاسم (مثال: خالد)" class="px-3 py-2 rounded-xl border border-slate-200 text-xs font-bold" />
          <input id="mem-user" type="text" required placeholder="اسم المستخدم (login)" class="px-3 py-2 rounded-xl border border-slate-200 text-xs font-bold" dir="ltr" />
          <input id="mem-pass" type="text" required placeholder="رمز الدخول (PIN)" class="px-3 py-2 rounded-xl border border-slate-200 text-xs font-bold" dir="ltr" />
          <select id="mem-role" class="px-2 py-2 rounded-xl border border-slate-200 text-xs font-bold">
            <option value="عضو فريق">عضو فريق</option>
            <option value="مدير النظام (Admin)">مدير النظام (Admin)</option>
            <option value="مدير القسم">مدير القسم</option>
            <option value="وكيل ذكاء اصطناعي 🤖">وكيل ذكاء اصطناعي 🤖</option>
          </select>
          <button type="submit" class="bg-teal-600 hover:bg-teal-500 text-white rounded-xl text-xs font-bold">+ إضافة حساب</button>
        </form>
        <div id="members-list-manage" class="space-y-2"></div>
      </div>
    </div>
  </div>

  <!-- ================= نافذة إضافة جهة تواصل (Stakeholder) ================= -->
  <div id="stk-modal" class="hidden fixed inset-0 z-50 bg-slate-900/70 backdrop-blur-sm flex items-center justify-center p-4">
    <div class="bg-white w-full max-w-md rounded-3xl shadow-2xl border border-slate-200 overflow-hidden">
      <div class="px-6 py-4 bg-slate-900 text-white flex items-center justify-between">
        <h3 class="text-sm font-black">📇 إضافة شخص أو جهة تواصل</h3>
        <button onclick="closeStakeholderModal()" class="text-slate-400 hover:text-white"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <form onsubmit="handleSaveStakeholder(event)" class="p-6 space-y-3">
        <input id="stk-name" type="text" required placeholder="اسم الشخص (مثال: أ. ماجد الحربي)" class="w-full px-3.5 py-2 rounded-xl border border-slate-200 text-xs font-bold" />
        <input id="stk-org" type="text" required placeholder="الجهة / الإدارة" class="w-full px-3.5 py-2 rounded-xl border border-slate-200 text-xs font-bold" />
        <input id="stk-phone" type="text" required placeholder="رقم الجوال (9665...)" class="w-full px-3.5 py-2 rounded-xl border border-slate-200 text-xs font-bold" dir="ltr" />
        <input id="stk-email" type="email" placeholder="البريد الإلكتروني" class="w-full px-3.5 py-2 rounded-xl border border-slate-200 text-xs font-bold" dir="ltr" />
        <button type="submit" class="w-full py-2.5 bg-teal-600 hover:bg-teal-500 text-white rounded-xl text-xs font-bold">حفظ جهة التواصل</button>
      </form>
    </div>
  </div>

  <script>
    const STORAGE_KEY = 'gday_pro_workspace_v5';
    const AUTH_KEY = 'gday_pro_active_user_v5';
    const todayStr = new Date().toISOString().split('T')[0];

    const defaultState = {
      activeProjectId: 'p1',
      mainView: 'workspace',
      subTab: 'table',
      filterTodayOnly: false,
      members: [
        { id: 'm1', name: 'عبدالله', username: 'admin', pass: '1234', role: 'مدير النظام (Admin)', isAdmin: true, color: 'bg-teal-600' },
        { id: 'm2', name: 'الوليد', username: 'waleed', pass: '1234', role: 'مدير القسم', isAdmin: true, color: 'bg-indigo-600' },
        { id: 'm_ai', name: 'مساعد G\'day الذكي 🤖', username: 'ai', pass: '1111', role: 'وكيل ذكاء اصطناعي 🤖', isAdmin: true, isAI: true, color: 'bg-emerald-600' },
        { id: 'm3', name: 'سارة', username: 'sara', pass: '1234', role: 'عضو فريق', isAdmin: false, color: 'bg-sky-600' },
        { id: 'm4', name: 'فهد', username: 'fahad', pass: '1234', role: 'عضو فريق', isAdmin: false, color: 'bg-amber-600' },
        { id: 'm5', name: 'نورة', username: 'noura', pass: '1234', role: 'عضو فريق', isAdmin: false, color: 'bg-rose-600' }
      ],
      projects: [
        { id: 'p1', name: 'المشاريع والمبادرات الرئيسية', desc: 'متابعة المهام التنفيذية والجهات المرتبطة والوقت المقدر' },
        { id: 'p2', name: 'المتابعة والتنسيق اليومي', desc: 'التنسيق اليومي السريع بين أعضاء الفريق والجهات الخارجية' },
        { id: 'p3', name: 'التقارير ومؤشرات الأداء', desc: 'إعداد ومراجعة التقارير الدورية ومؤشرات الإنجاز' }
      ],
      stakeholders: [
        { id: 's1', name: 'أ. ماجد الحربي', org: 'الإدارة التنفيذية', phone: '966500001122', email: 'majed@example.com' },
        { id: 's2', name: 'م. طارق السالم', org: 'الدعم التقني والمنصات', phone: '966500003344', email: 'tariq@example.com' },
        { id: 's3', name: 'أ. ريم العتيبي', org: 'التنسيق والمتابعة', phone: '966500005566', email: 'reem@example.com' }
      ],
      files: [
        { id: 'f1', title: 'الخطة التنفيذية للمشاريع', type: 'doc', updated: todayStr, content: '<h3>الخطة التنفيذية المعتمدة</h3><p>يتم تحديث بنود الخطة ومؤشرات الإنجاز بشكل أسبوعي بالتنسيق مع الفريق.</p>' },
        { id: 'f2', title: 'جدول متابعة مؤشرات الأداء', type: 'sheet', updated: todayStr, grid: [['البند', 'المسؤول', 'المستهدف', 'المنجز'], ['المبادرة الأولى', 'عبدالله', '100', '92'], ['المبادرة الثانية', 'سارة', '80', '75'], ['المبادرة الثالثة', 'فهد', '60', '58']] }
      ],
      tasks: [
        { id: 't1', projectId: 'p1', title: 'مراجعة واعتماد خطة العمل الأسبوعية وتوزيع المهام', assigneeId: 'm1', status: 'doing', priority: 'high', stakeholderId: 's1', estHours: 1.5, dueDate: todayStr, fileId: 'f1' },
        { id: 't2', projectId: 'p1', title: 'التنسيق مع الدعم التقني لتحديث لوحة المؤشرات', assigneeId: 'm3', status: 'waiting', priority: 'med', stakeholderId: 's2', estHours: 2, dueDate: todayStr, fileId: 'f2' },
        { id: 't3', projectId: 'p1', title: 'إعداد الملخص التنفيذي وعرضه على مدير القسم', assigneeId: 'm4', status: 'done', priority: 'high', stakeholderId: 's3', estHours: 1, dueDate: todayStr, fileId: 'f1' }
      ],
      chats: [
        { id: 'c1', projectId: 'p1', senderId: 'm2', text: 'يعطيكم العافية جميعاً، نرجو التركيز على مهام اليوم وتحديث المرحلة أولاً بأول.', time: '09:15 ص' },
        { id: 'c2', projectId: 'p1', senderId: 'm1', text: 'تم تحديث خطة العمل وربط كل مهمة بجهة التواصل والوقت المتوقع.', time: '09:20 ص' },
        { id: 'c3', projectId: 'p1', senderId: 'm_ai', text: 'مرحباً فريق G\'day 🤖 أنا جاهز لمساعدتكم في تحديث المهام وتلخيص الإنجاز.', time: '09:22 ص' }
      ]
    };

    let state = loadState();
    let currentUser = null;
    let activeEditingFileId = null;

    function loadState() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        return raw ? Object.assign({}, defaultState, JSON.parse(raw)) : JSON.parse(JSON.stringify(defaultState));
      } catch (e) {
        return JSON.parse(JSON.stringify(defaultState));
      }
    }

    function saveState() {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      refreshAiSnapshot();
    }

    // ================= نظام تسجيل الدخول الدائم =================
    function initAuth() {
      renderQuickLoginChips();
      const params = new URLSearchParams(window.location.search);
      const aiUserParam = params.get('ai_user');
      if (aiUserParam) {
        const foundAi = state.members.find(m => m.username.toLowerCase() === aiUserParam.toLowerCase());
        if (foundAi) {
          completeLogin(foundAi, true);
          return;
        }
      }
      const savedUserId = localStorage.getItem(AUTH_KEY);
      if (savedUserId) {
        const found = state.members.find(m => m.id === savedUserId);
        if (found) {
          completeLogin(found, false);
          return;
        }
      }
      document.getElementById('login-screen').classList.remove('hidden');
    }

    function renderQuickLoginChips() {
      const box = document.getElementById('quick-login-chips');
      box.innerHTML = state.members.map(m => `
        <button type="button" onclick="quickFillLogin('${m.username}', '${m.pass}')" class="px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-teal-50 text-slate-700 hover:text-teal-700 border border-slate-200 text-[11px] font-bold transition">
          ${m.name} (<span dir="ltr">${m.username}</span>)
        </button>
      `).join('');
    }

    function quickFillLogin(u, p) {
      document.getElementById('login-username').value = u;
      document.getElementById('login-password').value = p;
      handleLoginSubmit(new Event('submit'));
    }

    function handleLoginSubmit(e) {
      if (e && e.preventDefault) e.preventDefault();
      const u = document.getElementById('login-username').value.trim().toLowerCase();
      const p = document.getElementById('login-password').value.trim();
      const remember = document.getElementById('login-remember').checked;
      const found = state.members.find(m => m.username.toLowerCase() === u && m.pass === p);
      if (!found) {
        document.getElementById('login-error').classList.remove('hidden');
        return;
      }
      document.getElementById('login-error').classList.add('hidden');
      completeLogin(found, remember);
    }

    function completeLogin(member, remember) {
      currentUser = member;
      if (remember) localStorage.setItem(AUTH_KEY, member.id);
      document.getElementById('login-screen').classList.add('hidden');
      document.getElementById('current-user-name').textContent = member.name;
      document.getElementById('current-user-role').textContent = member.role;
      document.getElementById('current-user-avatar').textContent = member.name.charAt(0);
      renderAll();
    }

    function logoutUser() {
      localStorage.removeItem(AUTH_KEY);
      currentUser = null;
      document.getElementById('login-username').value = '';
      document.getElementById('login-password').value = '';
      renderQuickLoginChips();
      document.getElementById('login-screen').classList.remove('hidden');
    }

    // ================= العرض والتنقل =================
    function switchMainView(view) {
      state.mainView = view;
      ['workspace', 'drive', 'stakeholders', 'ai_hub'].forEach(v => {
        const btn = document.getElementById('nav-' + v);
        if (btn) btn.className = v === view
          ? 'w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-bold text-white bg-white/15 transition'
          : 'w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-medium text-slate-300 hover:bg-white/5 transition';
      });
      document.getElementById('workspace-tabs').classList.toggle('hidden', view !== 'workspace');
      renderAll();
    }

    function switchSubTab(tab) {
      state.subTab = tab;
      ['table', 'pipeline', 'chat'].forEach(t => {
        const el = document.getElementById('subtab-' + t);
        if (el) el.className = t === tab
          ? 'px-3.5 py-1.5 rounded-lg text-xs font-bold bg-white text-slate-900 shadow-sm transition'
          : 'px-3.5 py-1.5 rounded-lg text-xs font-semibold text-slate-600 hover:text-slate-900 transition';
      });
      renderAll();
    }

    function selectProject(pid) {
      state.activeProjectId = pid;
      state.mainView = 'workspace';
      switchMainView('workspace');
    }

    function renderAll() {
      renderSidebar();
      renderKPIs();
      renderQuickFormSelects();

      ['table', 'pipeline', 'chat', 'drive', 'stakeholders', 'ai_hub'].forEach(v => {
        document.getElementById('view-' + v).classList.add('hidden');
      });

      if (state.mainView === 'workspace') {
        document.getElementById('view-' + state.subTab).classList.remove('hidden');
        if (state.subTab === 'table') renderTable();
        if (state.subTab === 'pipeline') renderPipeline();
        if (state.subTab === 'chat') renderChat();
      } else {
        document.getElementById('view-' + state.mainView).classList.remove('hidden');
        if (state.mainView === 'drive') renderDrive();
        if (state.mainView === 'stakeholders') renderStakeholders();
        if (state.mainView === 'ai_hub') refreshAiSnapshot();
      }
      saveState();
    }

    function renderSidebar() {
      const proj = state.projects.find(p => p.id === state.activeProjectId) || state.projects[0];
      document.getElementById('active-project-title').textContent = '# ' + proj.name;
      document.getElementById('active-project-desc').textContent = proj.desc;
      document.getElementById('chat-header-title').textContent = 'محادثة: ' + proj.name;

      document.getElementById('side-total-tasks').textContent = state.tasks.length;
      document.getElementById('side-total-files').textContent = state.files.length;
      document.getElementById('side-total-stk').textContent = state.stakeholders.length;

      document.getElementById('sidebar-projects').innerHTML = state.projects.map(p => {
        const count = state.tasks.filter(t => t.projectId === p.id).length;
        const active = p.id === state.activeProjectId && state.mainView === 'workspace';
        return `
          <button onclick="selectProject('${p.id}')" class="ch-item ${active ? 'ch-active' : 'text-slate-300'} w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs">
            <span class="truncate"># ${p.name}</span>
            <span class="text-[10px] opacity-75">${count}</span>
          </button>
        `;
      }).join('');

      document.getElementById('sidebar-members').innerHTML = state.members.map(m => `
        <div class="flex items-center justify-between px-3 py-1.5 rounded-xl text-xs text-slate-300">
          <div class="flex items-center gap-2 truncate">
            <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
            <span class="truncate font-medium">${m.name}</span>
          </div>
          <span class="text-[9px] text-slate-400">${m.username}</span>
        </div>
      `).join('');
    }

    function renderKPIs() {
      const pTasks = state.tasks.filter(t => t.projectId === state.activeProjectId);
      const todayTasks = pTasks.filter(t => t.dueDate === todayStr && t.status !== 'done');
      const waitingTasks = pTasks.filter(t => t.status === 'waiting');
      const totalHours = pTasks.reduce((acc, t) => acc + (parseFloat(t.estHours) || 0), 0);
      const doneCount = pTasks.filter(t => t.status === 'done').length;
      const pct = pTasks.length ? Math.round((doneCount / pTasks.length) * 100) : 0;

      document.getElementById('today-count-badge').textContent = todayTasks.length;
      document.getElementById('kpi-today').textContent = todayTasks.length + ' مهام';
      document.getElementById('kpi-waiting').textContent = waitingTasks.length + ' مهام';
      document.getElementById('kpi-hours').textContent = totalHours + ' ساعة';
      document.getElementById('kpi-progress').textContent = pct + '%';

      const chatCount = state.chats.filter(c => c.projectId === state.activeProjectId).length;
      document.getElementById('chat-badge').textContent = chatCount;
    }

    function renderQuickFormSelects() {
      document.getElementById('quick-task-assignee').innerHTML = state.members.map(m => `<option value="${m.id}">${m.name}</option>`).join('');
      document.getElementById('quick-task-stk').innerHTML = `<option value="">بدون جهة</option>` + state.stakeholders.map(s => `<option value="${s.id}">${s.name} • ${s.org}</option>`).join('');
    }

    // ================= جدول المهام الذكي =================
    function getFilteredTasks() {
      const q = (document.getElementById('global-search')?.value || '').trim().toLowerCase();
      return state.tasks.filter(t => {
        if (t.projectId !== state.activeProjectId) return false;
        if (state.filterTodayOnly && t.dueDate !== todayStr) return false;
        if (q && !t.title.toLowerCase().includes(q)) return false;
        return true;
      });
    }

    function filterTodayTasks() {
      state.filterTodayOnly = !state.filterTodayOnly;
      document.getElementById('today-alert-btn').classList.toggle('ring-2', state.filterTodayOnly);
      document.getElementById('today-alert-btn').classList.toggle('ring-amber-400', state.filterTodayOnly);
      renderAll();
    }

    function renderTable() {
      const tasks = getFilteredTasks();
      const tbody = document.getElementById('tasks-tbody');
      if (!tasks.length) {
        tbody.innerHTML = `<tr><td colspan="9" class="py-10 text-center text-slate-400 font-bold">لا توجد مهام مطابقة حالياً — أضف مهمة من الشريط العلوي</td></tr>`;
        return;
      }

      tbody.innerHTML = tasks.map(t => {
        const stk = state.stakeholders.find(s => s.id === t.stakeholderId);
        return `
          <tr class="hover:bg-slate-50/90 transition">
            <td class="py-2.5 px-4">
              <input type="text" value="${t.title}" onchange="updateTaskField('${t.id}', 'title', this.value)" class="inline-input font-bold text-slate-800" />
            </td>
            <td class="py-2.5 px-3">
              <select onchange="updateTaskField('${t.id}', 'assigneeId', this.value)" class="inline-select bg-slate-100 text-slate-700">
                ${state.members.map(m => `<option value="${m.id}" ${m.id === t.assigneeId ? 'selected' : ''}>${m.name}</option>`).join('')}
              </select>
            </td>
            <td class="py-2.5 px-3">
              <select onchange="updateTaskField('${t.id}', 'status', this.value)" class="inline-select s-${t.status}">
                <option value="new" ${t.status === 'new' ? 'selected' : ''}>جديدة</option>
                <option value="doing" ${t.status === 'doing' ? 'selected' : ''}>جاري العمل ⚡</option>
                <option value="waiting" ${t.status === 'waiting' ? 'selected' : ''}>بانتظار الرد ⏳</option>
                <option value="done" ${t.status === 'done' ? 'selected' : ''}>مكتملة ✅</option>
              </select>
            </td>
            <td class="py-2.5 px-3">
              <select onchange="updateTaskField('${t.id}', 'priority', this.value)" class="inline-select p-${t.priority}">
                <option value="high" ${t.priority === 'high' ? 'selected' : ''}>عاجلة 🔥</option>
                <option value="med" ${t.priority === 'med' ? 'selected' : ''}>متوسطة</option>
                <option value="low" ${t.priority === 'low' ? 'selected' : ''}>عادية</option>
              </select>
            </td>
            <td class="py-2.5 px-3">
              <div class="flex items-center gap-1.5">
                <select onchange="updateTaskField('${t.id}', 'stakeholderId', this.value)" class="inline-select bg-slate-100 text-slate-700 max-w-[145px] truncate">
                  <option value="">— اختر الجهة —</option>
                  ${state.stakeholders.map(s => `<option value="${s.id}" ${s.id === t.stakeholderId ? 'selected' : ''}>${s.name} (${s.org})</option>`).join('')}
                </select>
                ${stk ? `
                  <a href="tel:${stk.phone}" title="اتصال: ${stk.phone}" class="w-6 h-6 rounded-lg bg-teal-50 text-teal-600 hover:bg-teal-600 hover:text-white flex items-center justify-center"><i class="fa-solid fa-phone text-[10px]"></i></a>
                  <a href="https://wa.me/${stk.phone}?text=${encodeURIComponent('مرحباً ' + stk.name + ' بخصوص: ' + t.title)}" target="_blank" title="واتساب" class="w-6 h-6 rounded-lg bg-emerald-50 text-emerald-600 hover:bg-emerald-600 hover:text-white flex items-center justify-center"><i class="fa-brands fa-whatsapp text-xs"></i></a>
                ` : ''}
              </div>
            </td>
            <td class="py-2.5 px-3">
              <div class="flex items-center gap-1">
                <input type="number" step="0.5" min="0.5" value="${t.estHours || 1}" onchange="updateTaskField('${t.id}', 'estHours', this.value)" class="w-14 px-2 py-1 rounded-lg border border-slate-200 text-center font-bold text-sky-700 bg-sky-50/50" />
                <span class="text-[10px] text-slate-400">ساعة</span>
              </div>
            </td>
            <td class="py-2.5 px-3">
              <input type="date" value="${t.dueDate || todayStr}" onchange="updateTaskField('${t.id}', 'dueDate', this.value)" class="text-[11px] bg-slate-100 px-2 py-1 rounded-lg font-semibold text-slate-700" />
            </td>
            <td class="py-2.5 px-3">
              <div class="flex items-center gap-1">
                <select onchange="updateTaskField('${t.id}', 'fileId', this.value)" class="inline-select bg-slate-100 text-slate-700 max-w-[120px] truncate">
                  <option value="">بدون ملف</option>
                  ${state.files.map(f => `<option value="${f.id}" ${f.id === t.fileId ? 'selected' : ''}>${f.title}</option>`).join('')}
                </select>
                ${t.fileId ? `<button onclick="openFileEditor('${t.fileId}')" class="w-6 h-6 rounded-lg bg-blue-50 text-blue-600 hover:bg-blue-600 hover:text-white flex items-center justify-center" title="فتح الملف"><i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i></button>` : ''}
              </div>
            </td>
            <td class="py-2.5 px-3 text-center">
              <button onclick="deleteTask('${t.id}')" class="text-slate-400 hover:text-rose-600 p-1" title="حذف المهمة"><i class="fa-solid fa-trash-can"></i></button>
            </td>
          </tr>
        `;
      }).join('');
    }

    function handleQuickTaskAdd(e) {
      e.preventDefault();
      const title = document.getElementById('quick-task-title').value.trim();
      if (!title) return;
      state.tasks.unshift({
        id: 't_' + Date.now(),
        projectId: state.activeProjectId,
        title,
        assigneeId: document.getElementById('quick-task-assignee').value || state.members[0].id,
        status: 'new',
        priority: 'med',
        stakeholderId: document.getElementById('quick-task-stk').value || '',
        estHours: parseFloat(document.getElementById('quick-task-time').value) || 1,
        dueDate: todayStr,
        fileId: ''
      });
      document.getElementById('quick-task-title').value = '';
      renderAll();
    }

    function openNewTaskModal() {
      state.mainView = 'workspace';
      state.subTab = 'table';
      renderAll();
      setTimeout(() => document.getElementById('quick-task-title')?.focus(), 80);
    }

    function updateTaskField(id, field, val) {
      const t = state.tasks.find(x => x.id === id);
      if (t) {
        t[field] = val;
        renderAll();
      }
    }

    function deleteTask(id) {
      state.tasks = state.tasks.filter(t => t.id !== id);
      renderAll();
    }

    // ================= مسار الإنجاز (Workflow Pipeline) =================
    function renderPipeline() {
      const stages = [
        { key: 'new', title: 'جديدة', badge: 'bg-slate-200 text-slate-700' },
        { key: 'doing', title: 'جاري العمل ⚡', badge: 'bg-blue-100 text-blue-700' },
        { key: 'waiting', title: 'بانتظار رد الجهة ⏳', badge: 'bg-amber-100 text-amber-800' },
        { key: 'done', title: 'مكتملة ✅', badge: 'bg-emerald-100 text-emerald-700' }
      ];
      const tasks = getFilteredTasks();
      document.getElementById('view-pipeline').innerHTML = stages.map(st => {
        const list = tasks.filter(t => t.status === st.key);
        return `
          <div class="bg-slate-100/90 rounded-2xl p-3 border border-slate-200 flex flex-col">
            <div class="flex items-center justify-between mb-3 px-1">
              <span class="text-xs font-black text-slate-800">${st.title}</span>
              <span class="px-2 py-0.5 rounded-full text-[11px] font-bold ${st.badge}">${list.length}</span>
            </div>
            <div class="space-y-2.5 flex-1 overflow-y-auto">
              ${list.map(t => {
                const mem = state.members.find(m => m.id === t.assigneeId);
                const stk = state.stakeholders.find(s => s.id === t.stakeholderId);
                return `
                  <div class="bg-white p-3.5 rounded-xl shadow-sm border border-slate-200 space-y-2">
                    <div class="text-xs font-bold text-slate-800">${t.title}</div>
                    ${stk ? `<div class="text-[11px] text-teal-700 bg-teal-50 px-2 py-1 rounded-lg font-semibold">📇 ${stk.name} • ${stk.org}</div>` : ''}
                    <div class="flex items-center justify-between text-[11px] text-slate-500 pt-1 border-t border-slate-100">
                      <span class="font-bold text-slate-700">👤 ${mem ? mem.name : '—'}</span>
                      <span class="font-bold text-sky-700">⏱️ ${t.estHours} س</span>
                    </div>
                  </div>
                `;
              }).join('')}
            </div>
          </div>
        `;
      }).join('');
    }

    // ================= المحادثة الفورية + التحكم بحذف الدردشات =================
    function renderChat() {
      const box = document.getElementById('chat-messages');
      const list = state.chats.filter(c => c.projectId === state.activeProjectId);
      if (!list.length) {
        box.innerHTML = `<div class="text-center py-12 text-slate-400 text-xs font-bold">لا توجد رسائل في هذه القناة حالياً</div>`;
        return;
      }
      box.innerHTML = list.map(c => {
        const sender = state.members.find(m => m.id === c.senderId) || { name: 'عضو', color: 'bg-slate-600' };
        return `
          <div class="bg-white p-3.5 rounded-2xl border border-slate-200/80 shadow-sm flex items-start justify-between gap-3">
            <div class="flex items-start gap-3">
              <div class="w-8 h-8 rounded-xl ${sender.color || 'bg-teal-600'} text-white flex items-center justify-center font-bold text-xs shrink-0">${sender.name.charAt(0)}</div>
              <div>
                <div class="flex items-center gap-2">
                  <span class="text-xs font-black text-slate-900">${sender.name}</span>
                  <span class="text-[10px] text-slate-400">${c.time}</span>
                </div>
                <p class="text-xs text-slate-700 mt-1 leading-relaxed">${c.text}</p>
              </div>
            </div>
            <div class="flex items-center gap-1.5 shrink-0">
              <button onclick="convertChatToTask('${c.id}')" class="px-2.5 py-1 rounded-lg bg-teal-50 hover:bg-teal-600 text-teal-700 hover:text-white text-[10px] font-bold transition">
                ⚡ تحويل لمهمة
              </button>
              <button onclick="deleteSingleChat('${c.id}')" title="حذف الرسالة" class="w-7 h-7 rounded-lg bg-rose-50 hover:bg-rose-600 text-rose-600 hover:text-white flex items-center justify-center text-xs transition">
                <i class="fa-solid fa-trash-can"></i>
              </button>
            </div>
          </div>
        `;
      }).join('');
      box.scrollTop = box.scrollHeight;
    }

    function handleSendChat(e) {
      e.preventDefault();
      const inp = document.getElementById('chat-input');
      const text = inp.value.trim();
      if (!text) return;
      const now = new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' });
      state.chats.push({
        id: 'c_' + Date.now(),
        projectId: state.activeProjectId,
        senderId: currentUser ? currentUser.id : 'm1',
        text,
        time: now
      });
      inp.value = '';
      renderAll();
    }

    function deleteSingleChat(cid) {
      state.chats = state.chats.filter(c => c.id !== cid);
      renderAll();
    }

    function clearChannelChat() {
      state.chats = state.chats.filter(c => c.projectId !== state.activeProjectId);
      renderAll();
    }

    function convertChatToTask(cid) {
      const msg = state.chats.find(c => c.id === cid);
      if (!msg) return;
      state.tasks.unshift({
        id: 't_' + Date.now(),
        projectId: state.activeProjectId,
        title: msg.text,
        assigneeId: currentUser ? currentUser.id : 'm1',
        status: 'new',
        priority: 'med',
        stakeholderId: '',
        estHours: 1,
        dueDate: todayStr,
        fileId: ''
      });
      state.subTab = 'table';
      renderAll();
    }

    // ================= مكتبة الملفات (Drive) =================
    function renderDrive() {
      const grid = document.getElementById('drive-grid');
      grid.innerHTML = state.files.map(f => {
        const icon = f.type === 'doc' ? '📝' : (f.type === 'sheet' ? '📊' : '📕');
        const typeLabel = f.type === 'doc' ? 'مستند Word تفاعلي' : (f.type === 'sheet' ? 'جدول Excel تفاعلي' : 'ملف PDF / مرفق');
        return `
          <div class="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm hover:shadow-md transition flex flex-col justify-between">
            <div>
              <div class="flex items-start justify-between">
                <span class="text-2xl">${icon}</span>
                <button onclick="deleteDriveFile('${f.id}')" class="text-slate-300 hover:text-rose-600 text-xs"><i class="fa-solid fa-trash"></i></button>
              </div>
              <h4 class="text-xs font-black text-slate-900 mt-3">${f.title}</h4>
              <p class="text-[11px] text-slate-400 mt-0.5">${typeLabel} • ${f.updated}</p>
            </div>
            <div class="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between">
              <button onclick="openFileEditor('${f.id}')" class="px-3 py-1.5 rounded-xl bg-slate-900 hover:bg-teal-600 text-white text-[11px] font-bold transition">فتح وتعديل</button>
            </div>
          </div>
        `;
      }).join('');
    }

    function createNewDriveFile(type) {
      const id = 'f_' + Date.now();
      const newFile = type === 'doc'
        ? { id, title: 'مستند عمل جديد', type: 'doc', updated: todayStr, content: '<h3>عنوان المستند</h3><p>اكتب محتوى المستند هنا...</p>' }
        : { id, title: 'جدول بيانات جديد', type: 'sheet', updated: todayStr, grid: [['البند', 'المسؤول', 'القيمة', 'الملاحظات'], ['', '', '0', ''], ['', '', '0', '']] };
      state.files.unshift(newFile);
      renderAll();
      openFileEditor(id);
    }

    function handleFileUpload(e) {
      const file = e.target.files[0];
      if (!file) return;
      const id = 'f_' + Date.now();
      state.files.unshift({
        id,
        title: file.name,
        type: 'pdf',
        updated: todayStr,
        content: `<div class="p-6 text-center space-y-2"><div class="text-4xl">📕</div><h4 class="font-bold text-sm">${file.name}</h4><p class="text-xs text-slate-500">الحجم: ${(file.size / 1024).toFixed(1)} KB</p></div>`
      });
      renderAll();
    }

    function openFileEditor(fid) {
      const f = state.files.find(x => x.id === fid);
      if (!f) return;
      activeEditingFileId = fid;
      document.getElementById('editor-file-title').value = f.title;
      document.getElementById('editor-file-icon').textContent = f.type === 'doc' ? '📝' : (f.type === 'sheet' ? '📊' : '📕');
      const body = document.getElementById('editor-body');
      if (f.type === 'doc' || f.type === 'pdf') {
        body.innerHTML = `<div id="doc-live-area" contenteditable="true" class="bg-white min-h-[55vh] p-8 rounded-2xl shadow border border-slate-200 focus:outline-none prose max-w-none text-sm leading-relaxed">${f.content || ''}</div>`;
      } else if (f.type === 'sheet') {
        const rows = f.grid || [['A', 'B'], ['', '']];
        body.innerHTML = `
          <div class="overflow-x-auto bg-white p-4 rounded-2xl shadow border border-slate-200">
            <table id="sheet-live-table" class="border-collapse">
              <tbody>
                ${rows.map((r, ri) => `<tr>${r.map((c, ci) => `<td contenteditable="true" class="sheet-cell ${ri === 0 ? 'bg-slate-100 font-bold' : ''}">${c}</td>`).join('')}</tr>`).join('')}
              </tbody>
            </table>
          </div>
        `;
      }
      document.getElementById('file-editor-modal').classList.remove('hidden');
    }

    function saveCurrentFile() {
      const f = state.files.find(x => x.id === activeEditingFileId);
      if (!f) return;
      f.title = document.getElementById('editor-file-title').value.trim() || f.title;
      f.updated = todayStr;
      if (f.type === 'doc' || f.type === 'pdf') {
        f.content = document.getElementById('doc-live-area').innerHTML;
      } else if (f.type === 'sheet') {
        const trs = Array.from(document.querySelectorAll('#sheet-live-table tr'));
        f.grid = trs.map(tr => Array.from(tr.querySelectorAll('td')).map(td => td.innerText));
      }
      closeFileEditor();
      renderAll();
    }

    function shareCurrentFileToChat() {
      const f = state.files.find(x => x.id === activeEditingFileId);
      if (!f) return;
      state.chats.push({
        id: 'c_' + Date.now(),
        projectId: state.activeProjectId,
        senderId: currentUser ? currentUser.id : 'm1',
        text: `📎 تمت مشاركة الملف: "${f.title}" في مكتبة الملفات للمراجعة.`,
        time: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })
      });
      closeFileEditor();
      state.mainView = 'workspace';
      state.subTab = 'chat';
      renderAll();
    }

    function closeFileEditor() {
      document.getElementById('file-editor-modal').classList.add('hidden');
    }

    function deleteDriveFile(fid) {
      state.files = state.files.filter(f => f.id !== fid);
      renderAll();
    }

    // ================= جهات التواصل (Stakeholders) =================
    function renderStakeholders() {
      document.getElementById('stakeholders-grid').innerHTML = state.stakeholders.map(s => `
        <div class="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm space-y-2">
          <div class="flex items-center justify-between">
            <h4 class="text-xs font-black text-slate-900">${s.name}</h4>
            <button onclick="deleteStakeholder('${s.id}')" class="text-slate-300 hover:text-rose-600 text-xs"><i class="fa-solid fa-trash"></i></button>
          </div>
          <p class="text-[11px] text-teal-700 font-bold">${s.org}</p>
          <div class="text-[11px] text-slate-500" dir="ltr">${s.phone}</div>
          <div class="pt-2 flex items-center gap-2">
            <a href="tel:${s.phone}" class="flex-1 py-1.5 rounded-xl bg-teal-50 text-teal-700 text-center text-xs font-bold">📞 اتصال</a>
            <a href="https://wa.me/${s.phone}" target="_blank" class="flex-1 py-1.5 rounded-xl bg-emerald-50 text-emerald-700 text-center text-xs font-bold">💬 واتساب</a>
          </div>
        </div>
      `).join('');
    }

    function openStakeholderModal() { document.getElementById('stk-modal').classList.remove('hidden'); }
    function closeStakeholderModal() { document.getElementById('stk-modal').classList.add('hidden'); }
    function handleSaveStakeholder(e) {
      e.preventDefault();
      state.stakeholders.push({
        id: 's_' + Date.now(),
        name: document.getElementById('stk-name').value.trim(),
        org: document.getElementById('stk-org').value.trim(),
        phone: document.getElementById('stk-phone').value.trim(),
        email: document.getElementById('stk-email').value.trim()
      });
      e.target.reset();
      closeStakeholderModal();
      renderAll();
    }
    function deleteStakeholder(id) {
      state.stakeholders = state.stakeholders.filter(s => s.id !== id);
      renderAll();
    }

    // ================= إدارة الأعضاء والحسابات =================
    function openMembersModal() {
      renderMembersManageList();
      document.getElementById('members-modal').classList.remove('hidden');
    }
    function closeMembersModal() { document.getElementById('members-modal').classList.add('hidden'); }
    function renderMembersManageList() {
      document.getElementById('members-list-manage').innerHTML = state.members.map(m => `
        <div class="flex items-center justify-between p-3 rounded-xl bg-slate-50 border border-slate-200 text-xs">
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-lg bg-teal-600 text-white font-bold flex items-center justify-center">${m.name.charAt(0)}</div>
            <div>
              <div class="font-black text-slate-900">${m.name} <span class="text-[10px] text-teal-600">(${m.role})</span></div>
              <div class="text-[11px] text-slate-500" dir="ltr">Username: <b>${m.username}</b> | PIN: <b>${m.pass}</b></div>
            </div>
          </div>
          ${state.members.length > 1 ? `<button onclick="deleteMember('${m.id}')" class="text-rose-500 hover:text-rose-700 font-bold">حذف</button>` : ''}
        </div>
      `).join('');
    }
    function handleSaveMember(e) {
      e.preventDefault();
      state.members.push({
        id: 'm_' + Date.now(),
        name: document.getElementById('mem-name').value.trim(),
        username: document.getElementById('mem-user').value.trim(),
        pass: document.getElementById('mem-pass').value.trim(),
        role: document.getElementById('mem-role').value,
        color: 'bg-teal-600'
      });
      e.target.reset();
      renderMembersManageList();
      renderAll();
    }
    function deleteMember(id) {
      state.members = state.members.filter(m => m.id !== id);
      renderMembersManageList();
      renderAll();
    }

    // ================= إدارة المشاريع =================
    function openProjectModal() {
      const name = prompt('اسم المشروع أو القناة الجديدة:');
      if (!name) return;
      const id = 'p_' + Date.now();
      state.projects.push({ id, name: name.trim(), desc: 'مشروع عمل مشترك' });
      state.activeProjectId = id;
      renderAll();
    }
    function editCurrentProject() {
      const p = state.projects.find(x => x.id === state.activeProjectId);
      if (!p) return;
      const newName = prompt('تعديل اسم المشروع:', p.name);
      if (newName) {
        p.name = newName.trim();
        renderAll();
      }
    }

    // ================= بوابة الـ AI ومتصفح الـ AI =================
    function refreshAiSnapshot() {
      const snap = document.getElementById('ai-context-snapshot');
      if (!snap) return;
      const summary = {
        currentUser: currentUser ? { name: currentUser.name, username: currentUser.username, role: currentUser.role } : null,
        activeProject: state.projects.find(p => p.id === state.activeProjectId),
        tasks: state.tasks.filter(t => t.projectId === state.activeProjectId),
        stakeholders: state.stakeholders,
        recentChats: state.chats.filter(c => c.projectId === state.activeProjectId).slice(-10)
      };
      snap.value = JSON.stringify(summary, null, 2);
    }

    function copyAiSnapshot() {
      const snap = document.getElementById('ai-context-snapshot');
      snap.select();
      document.execCommand('copy');
    }

    function executeAiCommand() {
      const raw = document.getElementById('ai-command-input').value.trim();
      const resBox = document.getElementById('ai-command-result');
      if (!raw) return;

      let msg = '';
      if (raw.startsWith('{')) {
        try {
          const cmd = JSON.parse(raw);
          if (cmd.action === 'add_task') {
            state.tasks.unshift({ id: 't_' + Date.now(), projectId: state.activeProjectId, title: cmd.title || 'مهمة من AI', assigneeId: 'm1', status: 'new', priority: 'high', stakeholderId: '', estHours: cmd.hours || 1, dueDate: todayStr, fileId: '' });
            msg = '✅ قام الـ AI بإضافة المهمة عبر JSON بنجاح.';
          } else if (cmd.action === 'clear_chat') {
            clearChannelChat();
            msg = '✅ قام الـ AI بمسح محادثة القناة.';
          }
        } catch (err) {
          msg = '⚠️ صيغة JSON غير صحيحة.';
        }
      } else if (raw.includes('أضف مهمة') || raw.includes('اضف مهمة')) {
        const cleanTitle = raw.replace(/أضف مهمة:?|اضف مهمة:?/g, '').split('|')[0].trim();
        state.tasks.unshift({
          id: 't_' + Date.now(),
          projectId: state.activeProjectId,
          title: cleanTitle || 'مهمة جديدة من المساعد الذكي',
          assigneeId: currentUser ? currentUser.id : 'm1',
          status: 'doing',
          priority: 'high',
          stakeholderId: state.stakeholders[0]?.id || '',
          estHours: 1.5,
          dueDate: todayStr,
          fileId: ''
        });
        msg = `✅ تم تنفيذ أمر الـ AI وإضافة المهمة: "${cleanTitle}"`;
      } else if (raw.includes('لخص') || raw.includes('ملخص')) {
        aiQuickSummaryToChat();
        msg = '✅ تم إعداد ملخص مهام اليوم وإرساله في المحادثة.';
      } else {
        state.chats.push({
          id: 'c_' + Date.now(),
          projectId: state.activeProjectId,
          senderId: 'm_ai',
          text: '🤖 تنفيذ توجيه الـ AI: ' + raw,
          time: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })
        });
        msg = '✅ تم إرسال توجيه الـ AI في محادثة المشروع.';
      }

      resBox.textContent = msg;
      resBox.classList.remove('hidden');
      document.getElementById('ai-command-input').value = '';
      renderAll();
    }

    function aiQuickSummaryToChat() {
      const pTasks = state.tasks.filter(t => t.projectId === state.activeProjectId);
      const done = pTasks.filter(t => t.status === 'done').length;
      const waiting = pTasks.filter(t => t.status === 'waiting').length;
      const hours = pTasks.reduce((a, b) => a + (parseFloat(b.estHours) || 0), 0);
      state.chats.push({
        id: 'c_' + Date.now(),
        projectId: state.activeProjectId,
        senderId: 'm_ai',
        text: `📊 ملخص المساعد الذكي (G'day AI): إجمالي المهام (${pTasks.length}) | المكتملة (${done}) | بانتظار رد الجهات (${waiting}) | إجمالي الوقت المقدر (${hours} ساعة).`,
        time: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })
      });
      state.mainView = 'workspace';
      state.subTab = 'chat';
      renderAll();
    }

    function aiAutoPrioritize() {
      const order = { high: 1, med: 2, low: 3 };
      state.tasks.sort((a, b) => (order[a.priority] || 2) - (order[b.priority] || 2));
      const resBox = document.getElementById('ai-command-result');
      resBox.textContent = '✅ تم إعادة ترتيب جميع المهام حسب الأولوية القصوى تلقائياً.';
      resBox.classList.remove('hidden');
      renderAll();
    }

    // تشغيل المنصة
    initAuth();
  </script>
</body>
</html>
"""

components.html(GDAY_APP_HTML, height=960, scrolling=False)