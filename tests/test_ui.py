from pathlib import Path

from streamlit.testing.v1 import AppTest


def element(elements, label):
    return next(x for x in elements if x.label == label)


def healthy(app):
    assert not list(app.exception), [x.message for x in app.exception]
    assert not list(app.error), [x.value for x in app.error]


def test_native_streamlit_member_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "ui.db"))
    monkeypatch.setenv("GDAY_LOCAL_MODE", "true")
    monkeypatch.setenv("GDAY_ADMIN_USERNAME", "ui_admin")
    monkeypatch.setenv("GDAY_ADMIN_PASSWORD", "UI-test-password-736!")
    monkeypatch.setenv("GDAY_ADMIN_NAME", "مدير الاختبار")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()
    healthy(app)
    element(app.text_input, "اسم المستخدم").set_value("ui_admin")
    element(app.text_input, "كلمة المرور").set_value("UI-test-password-736!")
    element(app.button, "دخول إلى مساحة العمل").click().run()
    healthy(app)
    for page in ["المهام", "المشاريع", "الملفات", "الجهات", "الدردشات", "مركز المساعد", "الأعضاء", "سجل النشاط"]:
        app.radio(key="navigation").set_value(page).run()
        healthy(app)
    app.radio(key="navigation").set_value("المهام").run()
    element(app.button, "＋ مهمة").click().run()
    healthy(app)
    assert any(x.label == "عنوان المهمة" for x in app.text_input)
    app.radio(key="navigation").set_value("نظرة اليوم").run()
    element(app.text_area, "وين وصلنا؟").set_value("اكتملت مراجعة اليوم")
    element(app.text_area, "الخطوة التالية").set_value("التواصل مع الفريق صباحًا")
    element(app.button, "حفظ تسليم اليوم").click().run()
    healthy(app)
    assert element(app.text_area, "الخطوة التالية").value == "التواصل مع الفريق صباحًا"
    app.radio(key="navigation").set_value("الملفات").run()
    element(app.text_input, "اسم الملف الجديد").set_value("مستند الفريق")
    element(app.button, "إنشاء الملف").click().run()
    healthy(app)
    app.radio(key="navigation").set_value("الدردشات").run()
    element(app.text_area, "رسالة للفريق").set_value("رسالة اختبار محفوظة")
    element(app.button, "إرسال الرسالة").click().run()
    healthy(app)
    assert any(x.value == "رسالة اختبار محفوظة" for x in app.text)
    element(app.button, "نعم، احذف").click().run()
    healthy(app)
    assert not any(x.value == "رسالة اختبار محفوظة" for x in app.text)
    element(app.button, "↓ حفظ اليوم").click().run()
    healthy(app)
    assert any(x.label == "تنزيل نسخة اليوم كاملة — JSON" for x in app.get("download_button"))


def test_dialog_submission_in_isolated_streamlit_run(tmp_path, monkeypatch):
    """AppTest reruns whole scripts, so keep the dialog mounted in this harness."""
    from workspace import Store
    database_url = "sqlite:///" + str(tmp_path / "dialog.db")
    monkeypatch.setenv("DATABASE_URL", database_url)
    store = Store(database_url)
    store.bootstrap("ui_admin", "UI-test-password-736!", "المدير")
    token = store.login("ui_admin", "UI-test-password-736!")
    source = '''
import streamlit as st
import os
from app import edit_task, edit_directory, edit_file
from workspace import Store
store = Store(os.environ['DATABASE_URL'])
token = st.session_state.get('test_token')
if token:
    state, _ = store.read(token)
    mode = st.session_state.get('test_mode', 'task')
    if mode == 'task':
        edit_task(store, token, state, store.actor(token))
    elif mode == 'project':
        edit_directory(store, token, state, store.actor(token), 'projects')
    elif mode == 'file':
        edit_file(store, token, state, store.actor(token), state['files'][0])
'''
    app = AppTest.from_string(source, default_timeout=15)
    app.session_state["test_token"] = token
    app.run()
    element(app.text_input, "عنوان المهمة").set_value("مهمة من اختبار الواجهة")
    element(app.button, "حفظ المهمة").click().run()
    healthy(app)
    assert store.read(token)[0]["tasks"][0]["title"] == "مهمة من اختبار الواجهة"
    app.session_state["test_mode"] = "project"
    app.run()
    element(app.text_input, "الاسم").set_value("مشروع جديد من الواجهة")
    element(app.button, "حفظ البيانات").click().run()
    healthy(app)
    assert any(p["name"] == "مشروع جديد من الواجهة" for p in store.read(token)[0]["projects"])
    store.put(token, "files", {"id": "f1", "title": "مستند", "type": "doc", "text": "نص أولي", "projectId": "p_general", "comments": []})
    app.session_state["test_mode"] = "file"
    app.run()
    element(app.text_area, "محتوى المستند").set_value("محتوى الملف بعد التعديل")
    element(app.button, "حفظ تعديلات الملف").click().run()
    healthy(app)
    assert store.read(token)[0]["files"][0]["text"] == "محتوى الملف بعد التعديل"
