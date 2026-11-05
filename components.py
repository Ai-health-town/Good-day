"""Native widgets and shared dialogs. Every mutation is checked by Store."""
import base64
import copy
import json
from datetime import date
from pathlib import Path
import pandas as pd
import streamlit as st
from filetools import docx_bytes, file_sheets, file_text, sheet_bytes
from contacttools import phone_parts, phone_html, matches_contact
from workspace import ROLES, STATUSES, PRIORITIES, Store, WorkspaceError, Forbidden, now_iso, today_iso, uid
COOKIE = "gday_session_v2"

def flash(message):
    st.session_state["flash"] = message
    st.rerun()


def perform(call, message="تم الحفظ"):
    try:
        call()
    except WorkspaceError as exc:
        st.error(str(exc))
        return False
    flash(message)


def lookup(records, ident, default="غير معين"):
    return next((x.get("name", x.get("title", default)) for x in records if x["id"] == ident), default)


def record_picker(label, records, value="", empty=True, key=None):
    options = ([""] if empty else []) + [x["id"] for x in records]
    if not options:
        options = [""]
    return st.selectbox(label, options, index=options.index(value) if value in options else 0,
                        format_func=lambda v: lookup(records, v, "بدون تحديد"), key=key)


def enum_picker(label, choices, value=None, key=None):
    options = list(choices)
    return st.selectbox(label, options, index=options.index(value) if value in options else 0, format_func=choices.get, key=key)


def end_session(store, token, all_sessions=False):
    try:
        store.logout(token, all_sessions)
    except Forbidden:
        pass
    st.session_state.clear()
    st.session_state["block_cookie"] = True
    st.session_state["delete_cookie"] = True
    st.rerun()


@st.dialog("حفظ اليوم", width="large")
def end_day(store, token, state, actor):
    st.write("كل تعديل تحفظه محفوظ مباشرة في المنصة. نسخة اليوم تجمع المهام والملفات والمحادثات وتسليم اليوم في ملف واحد.")
    st.download_button("تنزيل نسخة اليوم كاملة — JSON", store.backup_bytes(state), file_name=f"Gday_{today_iso()}.json", mime="application/json", type="primary", width="stretch")
    st.caption("النسخة لا تحتوي كلمات المرور أو جلسات الدخول. تُستعاد من زر بداية اليوم.")
    if any(f.get("object") for f in state["files"]):
        backup_revision = store.read(token)[1]
        st.info("النسخة الخفيفة تحفظ روابط الأصول الخاصة وتحتاج مخزن Neon نفسه. لإنشاء نسخة مستقلة بالأصول اضغط الإعداد أدناه (حتى 30 ميجابايت). محادثات AI الخاصة تُصدّر من مركز المساعد.")
        if st.button("إعداد نسخة تشمل الملفات الأصلية", key="prepare_portable_backup"):
            try:
                st.session_state["portable_backup"] = (backup_revision, store.export_with_originals(token))
            except WorkspaceError as exc:
                st.error(str(exc))
        portable = st.session_state.get("portable_backup")
        if portable and portable[0] == backup_revision:
            st.download_button("تنزيل النسخة المستقلة بالأصول", portable[1], f"Gday_portable_{today_iso()}.json", "application/json")
    if actor["role"] in ("admin", "manager"):
        if st.button("حفظ نقطة رجوع داخل المنصة", width="stretch"):
            perform(lambda: store.save_snapshot(token, "نهاية يوم " + today_iso()), "حُفظت نسخة اليوم داخل المنصة")
        saved = store.list_snapshots(token)
        if saved:
            st.markdown("**آخر نقاط الرجوع**")
            selected = st.selectbox("اختيار نسخة محفوظة", saved, format_func=lambda v: f"{v['at'][:16]} · {v['label']}")
            st.download_button("تنزيل نقطة الرجوع المختارة", store.snapshot_bytes(token, selected["id"]), f"Gday_restore_{selected['at'][:10]}.json", "application/json")
            st.caption("تُحفظ آخر 14 نقطة رجوع. لاستعادة واحدة، نزّلها وارفعها في بداية اليوم.")


@st.dialog("إعدادات حسابي", width="large")
def account_settings(store, token):
    with st.form("change_password", clear_on_submit=True):
        old = st.text_input("كلمة المرور الحالية", type="password")
        new = st.text_input("كلمة المرور الجديدة — 12 حرفًا على الأقل", type="password")
        again = st.text_input("تأكيد كلمة المرور الجديدة", type="password")
        submitted = st.form_submit_button("تغيير كلمة المرور")
    if submitted:
        if new != again:
            st.error("كلمتا المرور غير متطابقتين.")
        else:
            try:
                store.change_password(token, old, new)
            except WorkspaceError as exc:
                st.error(str(exc))
            else:
                end_session(store, token)
    if st.button("تسجيل الخروج من جميع أجهزتي"):
        end_session(store, token, all_sessions=True)


@st.dialog("تفاصيل المهمة", width="large")
def edit_task(store, token, state, actor, original=None):
    draft_id = st.session_state.setdefault("task_new_id", uid("t_")) if original is None else None
    task = copy.deepcopy(original) if original else {"id": draft_id, "title": "", "projectId": state["projects"][0]["id"],
        "assigneeId": actor["member_id"], "status": "todo", "priority": "medium", "dueDate": today_iso(),
        "estimatedMinutes": 30, "notes": "", "subtasks": [], "comments": []}
    editable = store.can_edit(actor)
    with st.form("task_editor_" + task["id"]):
        title = st.text_input("عنوان المهمة", task["title"], disabled=not editable, max_chars=1000)
        a, b = st.columns(2)
        with a:
            project = record_picker("المشروع", state["projects"], task.get("projectId"), empty=False)
            status = enum_picker("حالة المهمة", STATUSES, task.get("status"))
            due = st.date_input("موعد المهمة", value=date.fromisoformat(task["dueDate"]) if task.get("dueDate") else None)
        with b:
            assignee = record_picker("المسؤول عن المهمة", state["members"], task.get("assigneeId"))
            priority = enum_picker("أولوية المهمة", PRIORITIES, task.get("priority"))
            minutes = st.number_input("الوقت المتوقع بالدقائق", 0, 100000, min(100000, max(0, int(task.get("estimatedMinutes") or 30))), step=15)
        stakeholder = record_picker("شخص أو جهة التواصل", state["stakeholders"], task.get("stakeholderId", ""))
        file_id = record_picker("ملف مرتبط بالمهمة", state["files"], task.get("attachedFileId", ""))
        notes = st.text_area("ملاحظات المهمة", task.get("notes", ""), height=100)
        if st.form_submit_button("حفظ المهمة", type="primary", disabled=not editable, width="stretch"):
            task.update(title=title.strip(), projectId=project, assigneeId=assignee, status=status, priority=priority,
                        dueDate=due.isoformat() if due else "", estimatedMinutes=minutes, notes=notes, stakeholderId=stakeholder, attachedFileId=file_id)
            def save_task():
                store.put(token, "tasks", task, original.get("version", 1) if original else None)
                if original is None:
                    st.session_state.pop("task_new_id", None)
            perform(save_task, "حُفظت المهمة")
    if not original:
        return
    st.markdown("**الخطوات الفرعية**")
    subtasks = task.get("subtasks", [])
    for sub in subtasks:
        checked = st.checkbox(str(sub.get("text", "")), value=bool(sub.get("done")), key="sub_" + str(sub.get("id")), disabled=not editable)
        if checked != bool(sub.get("done")):
            modified = copy.deepcopy(original)
            for row in modified["subtasks"]:
                if row["id"] == sub["id"]:
                    row["done"] = checked
            perform(lambda: store.put(token, "tasks", modified, original.get("version", 1)))
    if editable:
        with st.form("add_subtask", clear_on_submit=True):
            subtext = st.text_input("إضافة خطوة فرعية", max_chars=2000)
            if st.form_submit_button("إضافة الخطوة"):
                if subtext.strip():
                    modified = copy.deepcopy(original)
                    modified.setdefault("subtasks", []).append({"id": uid("st_"), "text": subtext.strip(), "done": False})
                    perform(lambda: store.put(token, "tasks", modified, original.get("version", 1)))
    st.markdown("**التعليقات**")
    for comment in task.get("comments", []):
        st.caption(lookup(state["members"], comment.get("authorId")) + " · " + str(comment.get("time", "")))
        st.text(str(comment.get("text", "")))
    if editable:
        with st.form("task_comment", clear_on_submit=True):
            text = st.text_area("تعليق على المهمة", max_chars=5000)
            if st.form_submit_button("إضافة التعليق") and text.strip():
                modified = copy.deepcopy(original)
                modified.setdefault("comments", []).append({"id": uid("c_"), "text": text.strip(), "authorId": actor["member_id"], "time": now_iso()})
                perform(lambda: store.put(token, "tasks", modified, original.get("version", 1)))
    if actor["role"] in ("admin", "manager"):
        with st.expander("حذف المهمة"):
            confirmed = st.checkbox("تأكيد حذف هذه المهمة")
            if st.button("حذف المهمة نهائيًا", disabled=not confirmed):
                perform(lambda: store.remove(token, "tasks", original["id"], original.get("version", 1)), "حُذفت المهمة")


@st.dialog("بيانات السجل", width="large")
def edit_directory(store, token, state, actor, collection, original=None):
    draft_key = "directory_new_id_" + collection
    draft_id = st.session_state.setdefault(draft_key, uid()) if original is None else None
    record = copy.deepcopy(original) if original else {"id": draft_id}
    editable = store.can_edit(actor) and (collection == "stakeholders" or actor["role"] in ("admin", "manager"))
    with st.form("directory_" + record["id"]):
        record["name"] = st.text_input("الاسم", record.get("name", ""), max_chars=160)
        if collection == "projects":
            record["desc"] = st.text_area("وصف المشروع", record.get("desc", ""))
        elif collection == "stakeholders":
            default_project = state["projects"][0]["id"] if len(state["projects"]) == 1 else ""
            record["projectId"] = record_picker("المشروع المرتبط", state["projects"], record.get("projectId", default_project))
            record["org"] = st.text_input("الجهة", record.get("org", ""))
            with st.container(key="contact_phone_input"):
                record["phone"] = st.text_input("رقم التواصل", record.get("phone", ""), max_chars=80)
            with st.container(key="contact_email_input"):
                record["email"] = st.text_input("البريد الإلكتروني", record.get("email", ""))
            record["notes"] = st.text_area("الملاحظات", record.get("notes", ""))
        else:
            record["title"] = st.text_input("المسمى أو الدور", record.get("title", ""))
        if st.form_submit_button("حفظ البيانات", type="primary", disabled=not editable):
            def save_directory():
                if collection == "stakeholders":
                    display, number = phone_parts(record.get("phone",""))
                    record["phone"] = number or display
                store.put(token, collection, record, original.get("version", 1) if original else None)
                if original is None:
                    st.session_state.pop(draft_key, None)
            perform(save_directory)
    if original and actor["role"] in ("admin", "manager"):
        with st.expander("حذف السجل"):
            if collection == "projects":
                st.caption("تنتقل عناصر المشروع إلى أول مشروع آخر؛ تبقى المهام والملفات والمحادثات محفوظة.")
            confirmed = st.checkbox("أريد حذف هذا السجل")
            if st.button("تأكيد الحذف", disabled=not confirmed):
                perform(lambda: store.remove(token, collection, original["id"], original.get("version", 1)), "حُذف السجل")


def directory_page(store, token, state, actor, collection):
    title = "المشاريع" if collection == "projects" else "دليل الجهات والأشخاص"
    st.subheader(title)
    editable = store.can_edit(actor) and (collection == "stakeholders" or actor["role"] in ("admin", "manager"))
    if st.button("＋ إضافة " + ("مشروع" if collection == "projects" else "جهة أو شخص"), type="primary", disabled=not editable):
        edit_directory(store, token, state, actor, collection)
    search = st.text_input("بحث في " + title)
    records = [r for r in state[collection] if matches_contact(r,search)]
    if not records:
        st.info("لا توجد سجلات في هذا العرض.")
    columns = st.columns(2)
    for index, record in enumerate(records):
        with columns[index % 2], st.container(border=True):
            st.subheader(record["name"])
            if collection == "projects":
                st.write(record.get("desc", ""))
                tasks = [t for t in state["tasks"] if t.get("projectId") == record["id"]]
                done = sum(t.get("status") == "done" for t in tasks)
                st.progress(done / len(tasks) if tasks else 0, text=f"{done} من {len(tasks)} مهام مكتملة")
            else:
                if record.get("projectId"):
                    st.caption(lookup(state["projects"], record["projectId"]))
                st.caption(record.get("org", ""))
                if record.get("phone"):
                    st.markdown(phone_html(record["phone"]),unsafe_allow_html=True)
                    number = phone_parts(record["phone"])[1]
                    if number:
                        call, whatsapp = st.columns(2)
                        call.link_button("اتصال", "tel:" + number, width="stretch")
                        whatsapp.link_button("واتساب", "https://wa.me/" + number[1:], width="stretch")
                if record.get("email"):
                    from html import escape
                    st.markdown('<div class="contact-email" dir="ltr"><bdi dir="ltr">' + escape(str(record["email"])) + '</bdi></div>',unsafe_allow_html=True)
                if record.get("notes"):
                    st.write(record["notes"])
            if st.button("عرض وتعديل", key="directory_" + record["id"]):
                edit_directory(store, token, state, actor, collection, record)


@st.dialog("مساحة الملف", width="large")
def edit_file(store, token, state, actor, original):
    from preview_ui import original_preview
    record = copy.deepcopy(original)
    editable = store.can_edit(actor)
    st.subheader(record["title"])
    original_bytes = None
    if record.get("blob") or record.get("object"):
        try:
            original_bytes = store.file_bytes(token, record["id"])
        except WorkspaceError as exc:
            st.warning(str(exc))
        else:
            st.download_button("تنزيل الملف الأصلي", original_bytes, file_name=Path(record.get("originalName", record["title"])).name, width="stretch")
    if record.get("legacy") and not (record.get("blob") or record.get("object")):
        st.info("هذا المحتوى من النسخة السابقة. النسخة السابقة حفظت نصوصًا وجداول فقط؛ يتوفر هنا المحتوى المحفوظ فيها.")
    modes = (["معاينة الأصل"] if original_bytes else []) + ["نسخة العمل","التعليقات"]
    mode = st.segmented_control("مساحة الملف",modes,default=modes[0],selection_mode="single",
                                key="file_mode_" + record["id"],width="stretch",label_visibility="collapsed") or modes[0]
    if mode == "معاينة الأصل":
        original_preview(original,original_bytes)
    elif mode == "نسخة العمل":
        file_working_copy(store,token,state,actor,original,record,editable,original_bytes)
    else:
        file_comments(store,token,state,actor,original,editable)


def file_working_copy(store,token,state,actor,original,record,editable,original_bytes):
    title = st.text_input("اسم الملف", record["title"], disabled=not editable)
    project = record_picker("مشروع الملف", state["projects"], record.get("projectId"), empty=False)
    star = st.checkbox("تمييز الملف", value=bool(record.get("starred")), disabled=not editable)
    record.update(title=title, projectId=project, starred=star)
    if record.get("type") == "sheet":
        sheets = copy.deepcopy(file_sheets(record))
        selected = st.selectbox("ورقة العمل", range(len(sheets)), format_func=lambda i: sheets[i]["name"])
        rows = sheets[selected]["rows"] or [[""]]
        width = max(1, max(len(r) for r in rows))
        frame = pd.DataFrame([list(map(str, r)) + [""] * (width - len(r)) for r in rows], columns=[f"عمود {n+1}" for n in range(width)])
        original_excel = bool(original_bytes and Path(original.get("originalName","")).suffix.lower() in (".xlsx",".xlsm"))
        if original_excel:
            from openpyxl.utils import get_column_letter
            frame.columns = [get_column_letter(n+1) for n in range(width)]
            frame.index = range(1,len(frame)+1)
        edited = st.data_editor(frame, hide_index=not original_excel, num_rows="fixed" if original_excel else "dynamic", width="stretch", disabled=not editable, key="file_grid_" + record["id"] + "_" + str(selected))
        sheets[selected]["rows"] = edited.fillna("").astype(str).values.tolist()
        record["sheets"] = sheets
        record.pop("sheetData", None)
        if original_excel:
            from sheet_preview import edited_excel
            st.caption("الصف الأول جزء من البيانات. يمكنك كتابة صيغ Excel مثل =SUM(B2:B8). التصدير يطبّق تغييرات الخلايا مع إبقاء التنسيق والصيغ والأوراق الأخرى؛ الأصل يبقى محفوظًا.")
            try:
                exported = edited_excel(original_bytes,sheets)
                st.download_button("تنزيل نسخة التعديلات — Excel",exported,Path(title).stem + "_edited.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            except WorkspaceError as exc:
                st.warning(str(exc))
        else:
            st.caption("نسخة عمل بالقيم النصية. الأصل يحتفظ بتنسيقه وصيغه، وتُعرض نتائجه في معاينة الأصل.")
            st.download_button("تنزيل الجدول المحرر — Excel", sheet_bytes(sheets), Path(title).stem + "_edited.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if editable and not original_excel:
            new_column = st.text_input("عمود جديد — اختياري", key="new_column_" + record["id"])
            if st.button("إضافة العمود", disabled=not new_column.strip()):
                for index, row in enumerate(sheets[selected]["rows"]):
                    row.append(new_column.strip() if index == 0 else "")
                record["sheets"] = sheets
                perform(lambda: store.put(token, "files", record, original.get("version", 1)), "أُضيف العمود")
    else:
        if record.get("type") == "pdf":
            st.caption("ملف PDF الأصلي محفوظ كما رُفع. المساحة التالية لكتابة ملخص أو ملاحظات مرتبطة به.")
        elif record.get("blob") or record.get("object"):
            st.caption("تحرير النص وتصديره ينشئ مستندًا مبسطًا. الملف الأصلي يحتفظ بتنسيقه ومحتواه الكامل.")
        text = st.text_area("محتوى المستند" if record.get("type") != "pdf" else "ملخص الملف وملاحظاته", value=file_text(record), height=330, disabled=not editable, key="file_text_" + record["id"])
        record["text"] = text
        record.pop("content", None)
        st.download_button("تنزيل المحتوى — Word", docx_bytes(Path(title).stem, text), Path(title).stem + "_edited.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if st.button("حفظ تعديلات الملف", type="primary", disabled=not editable, width="stretch"):
        if not title.strip():
            st.error("اسم الملف مطلوب.")
        else:
            perform(lambda: store.put(token, "files", record, original.get("version", 1)), "حُفظت تعديلات الملف")


def file_comments(store,token,state,actor,original,editable):
    st.markdown("**تعليقات الفريق**")
    for comment in original.get("comments", []):
        st.caption(lookup(state["members"], comment.get("authorId")) + " · " + str(comment.get("time", "")))
        st.text(str(comment.get("text", "")))
    if editable:
        with st.form("file_comment", clear_on_submit=True):
            text = st.text_area("تعليق على الملف", max_chars=5000)
            if st.form_submit_button("إرسال تعليق الملف") and text.strip():
                updated = copy.deepcopy(original)
                updated.setdefault("comments", []).append({"id": uid(), "text": text.strip(), "authorId": actor["member_id"], "time": now_iso()})
                perform(lambda: store.put(token, "files", updated, original.get("version", 1)))
    if actor["role"] in ("admin", "manager"):
        with st.expander("حذف الملف"):
            confirmed = st.checkbox("تأكيد حذف الملف")
            if st.button("حذف الملف من المكتبة", disabled=not confirmed):
                perform(lambda: store.remove(token, "files", original["id"], original.get("version", 1)), "حُذف الملف")


@st.dialog("التحكم بالدردشات", width="large")
def clear_chat_dialog(store, token, state, revision):
    selected = st.selectbox("نطاق الحذف", [""] + [p["id"] for p in state["projects"]], format_func=lambda v: lookup(state["projects"], v, "جميع الدردشات"))
    count = sum(not selected or m.get("projectId") == selected for m in state["messages"])
    st.warning(f"سيتم حذف {count} رسالة من المساحة الحالية. النسخ اليومية السابقة قد تحتوي على الرسائل القديمة.")
    confirm = st.checkbox("أؤكد حذف الرسائل ضمن النطاق المختار")
    if st.button("حذف الدردشات المحددة", type="primary", disabled=not confirm or count == 0):
        perform(lambda: store.clear_chat(token, selected or None, revision), "حُذفت الدردشات المحددة")


@st.fragment(run_every="20s")
def chat_page(store, token, project_id=""):
    try:
        state, revision, actor = store.context(token)
    except Forbidden:
        st.rerun()
    a, b = st.columns([5, 1.4])
    a.subheader("دردشات الفريق")
    if actor["role"] in ("admin", "manager") and b.button("إدارة الحذف", width="stretch"):
        clear_chat_dialog(store, token, state, revision)
    options = [""] + [p["id"] for p in state["projects"]]
    project = st.selectbox("قناة الدردشة", options, index=options.index(project_id) if project_id in options else 0, format_func=lambda v: lookup(state["projects"], v, "كل القنوات"), key="chat_channel_" + project_id)
    st.caption("تتحدث الرسائل تلقائيًا كل 20 ثانية. يمكنك تحويل أي رسالة إلى مهمة.")
    messages = [m for m in state["messages"] if not project or m.get("projectId") == project]
    older = max(0, len(messages) - 100)
    show_all = st.checkbox(f"عرض الرسائل الأقدم أيضًا ({older})") if older else False
    with st.container(height=480):
        if not messages:
            st.info("ابدأ أول رسالة للفريق.")
        for message in messages if show_all else messages[-100:]:
            with st.chat_message("assistant" if message.get("authorId") != actor["member_id"] else "user", avatar="☀️"):
                st.caption(lookup(state["members"], message.get("authorId")) + " · " + lookup(state["projects"], message.get("projectId")) + " · " + str(message.get("time", "")))
                st.text(message["text"])
                attached = next((f for f in state["files"] if f["id"] == message.get("fileId")), None)
                if attached and st.button("📎 " + attached["title"], key="chatfile_" + message["id"]):
                    edit_file(store, token, state, actor, attached)
                buttons = st.columns([1, 1, 3])
                if buttons[0].button("تحويل لمهمة", key="convert_" + message["id"], disabled=not store.can_edit(actor)):
                    task = {"id": uid("t_"), "title": message["text"][:1000], "projectId": message.get("projectId") or state["projects"][0]["id"],
                            "assigneeId": actor["member_id"], "status": "todo", "priority": "medium", "dueDate": today_iso(),
                            "estimatedMinutes": 30, "notes": "من رسالة الفريق: " + message["text"], "subtasks": [], "comments": [], "attachedFileId": message.get("fileId", "")}
                    perform(lambda: store.put(token, "tasks", task), "تحولت الرسالة إلى مهمة")
                can_delete = actor["role"] in ("admin", "manager") or actor["role"] == "member" and message.get("authorId") == actor["member_id"]
                if can_delete:
                    with buttons[1].popover("حذف"):
                        st.write("حذف هذه الرسالة؟")
                        if st.button("نعم، احذف", key="delete_msg_" + message["id"]):
                            perform(lambda m=message: store.remove(token, "messages", m["id"], m.get("version", 1)), "حُذفت الرسالة")
    if store.can_edit(actor):
        with st.form("send_chat", clear_on_submit=True):
            target = record_picker("إرسال إلى مشروع", state["projects"], project or state["projects"][0]["id"], empty=False)
            text = st.text_area("رسالة للفريق", max_chars=20000, height=80)
            attachment = record_picker("إرفاق ملف من المنصة", state["files"])
            if st.form_submit_button("إرسال الرسالة", type="primary"):
                perform(lambda: store.put(token, "messages", {"id": uid("m_"), "text": text.strip(), "projectId": target, "fileId": attachment}), "أُرسلت الرسالة")


def members_page(store, token, state, actor):
    st.subheader("الأعضاء والصلاحيات")
    accounts = store.list_users(token)
    rows = [{"الاسم": u["name"], "اسم المستخدم": u["username"], "الدور": ROLES[u["role"]],
             "الحالة": "مفعل" if u["active"] else "موقوف", "تعديل المساعد": "مسموح" if u["role"] == "agent" and u["agent_edit"] else "—"} for u in accounts]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with st.expander("＋ إنشاء حساب عضو أو مساعد", expanded=not any(u["role"] == "agent" for u in accounts)):
        with st.form("create_account", clear_on_submit=True):
            a, b = st.columns(2)
            name = a.text_input("اسم العرض للحساب")
            username = b.text_input("اسم المستخدم الجديد", help="إنجليزي، مثل team.assistant. لا توجد حسابات جاهزة بكلمات مرور افتراضية.")
            role = enum_picker("صلاحية الحساب", ROLES, "member")
            linked = {u["member_id"] for u in accounts}
            available = [m for m in state["members"] if m["id"] not in linked]
            profile = record_picker("ربط بعضو من ملف أمس — اختياري", available)
            agent_edit = st.checkbox("السماح لحساب المساعد بتعديل المهام والملفات والتسليم وإرسال الرسائل", value=False)
            password = st.text_input("كلمة مرور الحساب الجديد", type="password")
            again = st.text_input("تأكيد كلمة مرور الحساب الجديد", type="password")
            if st.form_submit_button("إنشاء الحساب", type="primary"):
                if password != again:
                    st.error("كلمتا المرور غير متطابقتين.")
                else:
                    perform(lambda: store.create_user(token, username, name, password, role, profile, agent_edit), "أُنشئ الحساب ويمكنه تسجيل الدخول")
    st.markdown("**تعديل حساب أو إيقافه**")
    chosen = st.selectbox("الحساب المطلوب", accounts, format_func=lambda u: f"{u['name']} · {u['username']}")
    with st.form("edit_account_" + chosen["id"], clear_on_submit=False):
        role = enum_picker("الدور بعد التعديل", ROLES, chosen["role"])
        active = st.checkbox("الحساب مفعل", value=chosen["active"])
        edit_allowed = st.checkbox("السماح للمساعد بالتعديل", value=chosen["agent_edit"])
        password = st.text_input("كلمة مرور بديلة — اتركها فارغة للإبقاء على الحالية", type="password")
        st.caption("حفظ هذا التعديل يلغي جلسات الحساب على جميع الأجهزة؛ يسجل دخوله مجددًا بالبيانات الجديدة.")
        if st.form_submit_button("حفظ صلاحيات الحساب", type="primary"):
            perform(lambda: store.update_user(token, chosen["id"], role, active, edit_allowed, password), "حُدّث الحساب وأُلغيت جلساته القديمة")
    with st.expander("ملفات الأعضاء المستوردة من النسخة السابقة"):
        st.caption("ملف العضو يربط المهام باسمه. حساب الدخول يُنشأ من النموذج أعلاه، ولا يُنشأ تلقائيًا من ملف مستورد.")
        if st.button("إضافة ملف عضو بدون حساب"):
            edit_directory(store, token, state, actor, "members")
        for profile in state["members"]:
            if st.button(profile["name"] + " · " + str(profile.get("title", "")), key="profile_" + profile["id"]):
                edit_directory(store, token, state, actor, "members", profile)


def activity_page(store, token):
    st.subheader("سجل النشاط")
    st.caption("تسجيل الدخول والتعديلات والحذف والاستعادة، بما فيها إجراءات المساعد. لا يُحفظ نص الرسائل المحذوفة في هذا السجل.")
    records = store.activity(token)
    if records:
        frame = pd.DataFrame(records).drop(columns="id").rename(columns={"at": "الوقت", "actor": "المنفذ", "action": "الإجراء", "detail": "التفاصيل"})
        st.dataframe(frame, hide_index=True, width="stretch")

