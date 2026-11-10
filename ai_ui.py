"""Streamlit surfaces for the Neon-backed assistant and connection checks."""
from __future__ import annotations

import json
import logging
import hashlib

import pandas as pd
import streamlit as st

from ai_service import AICreditsRequired, AIGatewayLimit, AIConfig, NeonAI, build_context
from ai_store import AIStore
from components import lookup, perform
from workspace import WorkspaceError, Store, now_iso, uid


@st.cache_resource
def repository(identity, _store):
    return AIStore(_store)


def reviewed_proposal(repo, store, token, run_id, state, actor):
    proposal, decision = repo.proposal(token, run_id)
    if not proposal:
        return
    if decision != "pending":
        st.caption("✓ طُبّق المقترح وحُفظ" if decision == "applied" else "تُرك المقترح دون تطبيق")
        return
    kinds = {"task_create": "إضافة مهمة", "task_update": "تحديث مهمة", "document_create": "إضافة مستند", "handover_update": "تحديث تسليم اليوم المشترك"}
    names = {"title": "العنوان", "notes": "الملاحظات", "assigneeId": "المسؤول", "status": "المرحلة",
             "priority": "الأولوية", "dueDate": "الموعد", "estimatedMinutes": "الوقت بالدقائق",
             "text": "محتوى المستند", "summary": "وين وصلنا", "decisions": "القرارات", "next_step": "الخطوة التالية"}
    from workspace import STATUSES, PRIORITIES
    with st.expander(f"راجع {len(proposal)} تغييرات مقترحة — لم تُحفظ بعد", expanded=True):
        for index, item in enumerate(proposal):
            target = lookup(state["tasks"], item["id"], "") if item["kind"] == "task_update" else ""
            st.markdown("**" + kinds[item["kind"]] + (" · " + target if target else "") + "**")
            for key, value in item["values"].items():
                if key == "assigneeId": value = lookup(state["members"], value)
                elif key == "status": value = STATUSES.get(value, value)
                elif key == "priority": value = PRIORITIES.get(value, value)
                if key in ("text", "notes", "summary", "decisions", "next_step"):
                    st.text_area(names[key], value, height=100, disabled=True, key=f"proposal_{run_id}_{index}_{key}")
                else:
                    st.text(names[key] + ": " + str(value or "بدون تحديد"))
            st.divider()
        confirm = st.checkbox("راجعت المقترح وأريد حفظ هذه التغييرات", key="approve_" + run_id)
        a, b = st.columns(2)
        if a.button("تطبيق وحفظ", key="apply_" + run_id, type="primary", disabled=not confirm or not Store.can_edit(actor), width="stretch"):
            perform(lambda: repo.decide(token, run_id, apply=True), "طُبّق المقترح مرة واحدة وحُفظ في مساحة العمل")
        if b.button("ترك المقترح", key="dismiss_" + run_id, width="stretch"):
            perform(lambda: repo.decide(token, run_id, apply=False), "تُرك المقترح دون تغيير العمل")


def assistant_chat(store, token, state, actor, setting):
    config, config_error = AIConfig.load(setting)
    repo = repository(str(id(store)), store)
    st.subheader("اسأل مساعدك من نفس مساحة العمل")
    st.caption("محادثاتك محفوظة لحسابك في قاعدة البيانات. المساعد يقرأ ما تختاره، ويقترح التغييرات للمراجعة.")
    options = [p["id"] for p in state["projects"]]
    if st.session_state.get("ai_project") not in options: st.session_state.pop("ai_project", None)
    project_id = st.selectbox("مشروع المحادثة", options, format_func=lambda i: lookup(state["projects"], i), key="ai_project")
    saved = repo.list_threads(token, project_id)
    ids = [t["id"] for t in saved]
    choices = {t["id"]: t["title"] for t in saved}
    pending = st.session_state.pop("select_ai_thread", None)
    if pending in ids: st.session_state["ai_thread"] = pending
    if st.session_state.get("ai_thread") not in ids: st.session_state.pop("ai_thread", None)
    a, b = st.columns([4, 1])
    thread_id = a.selectbox("محادثاتي المحفوظة", ids or [""], format_func=lambda i: choices.get(i, "ابدأ محادثة جديدة"), key="ai_thread")
    if b.button("＋ محادثة جديدة", width="stretch"):
        try:
            new_thread = repo.create_thread(token, project_id)
        except WorkspaceError as exc:
            st.error(str(exc))
        else:
            st.session_state["select_ai_thread"] = new_thread
            st.rerun()
    if thread_id:
        with st.expander("تصدير المحادثة أو حذفها"):
            st.download_button("تنزيل محادثتي — JSON", repo.export_thread(token, thread_id), "Gday_AI_" + thread_id + ".json", "application/json")
            confirm_delete = st.checkbox("أريد حذف هذه المحادثة الخاصة ومقترحاتها", key="delete_ai_check_" + thread_id)
            if st.button("حذف المحادثة", disabled=not confirm_delete, key="delete_ai_" + thread_id):
                perform(lambda: repo.delete_thread(token, thread_id), "حُذفت المحادثة الخاصة؛ التغييرات التي طُبّقت على العمل تبقى محفوظة")
    if config:
        st.caption(f"النموذج: {config.model} · طلبات حسابك اليوم: {repo.daily_count(token)} / {config.daily_limit}")
    else:
        st.info(config_error + " يستمر حفظ العمل والدخول المعتاد دون الذكاء الاصطناعي.")
    available = [f for f in state["files"] if f.get("projectId") == project_id]
    file_names = {f["id"]: f["title"] for f in available}
    with st.expander("المحتوى الذي سيرافق سؤالك", expanded=True):
        include_work = st.checkbox("إرسال مهام المشروع وتسليم اليوم المشترك وأسماء أعضاء الفريق", value=True)
        selected = st.multiselect("ملفات أسمح للمساعد بقراءتها مع هذا الطلب", list(file_names), format_func=file_names.get,
                                  max_selections=5, key="ai_files_" + project_id)
        st.caption("عند الإرسال تُرسل مقتطفات نصية فقط إلى النموذج عبر Neon AI Gateway. الملفات الأخرى ودردشات الفريق وكلمات المرور ومفاتيح الاتصال لا تُرسل.")
        allow_actions = st.checkbox("السماح باقتراح مهام ومستندات وتحديثات للمراجعة", value=Store.can_edit(actor), disabled=not Store.can_edit(actor))
    history = repo.history(token, thread_id) if thread_id else []
    for message in history:
        with st.chat_message(message["role"]):
            # Prevent model-authored remote images from being fetched by the client.
            st.markdown(message["content"].replace("![", "\\!["), unsafe_allow_html=False)
            meta = message["meta"]
            if meta.get("sources"):
                st.caption("المصادر: " + " · ".join(f"[{s['ref']}] {s['title']} — مقتطف {s['chunk']}" for s in meta["sources"]))
            for warning in meta.get("warnings", []): st.caption(warning)
            if meta.get("proposal_error"): st.warning("لم يُعتمد المقترح: " + meta["proposal_error"])
            if meta.get("proposal_count"):
                reviewed_proposal(repo, store, token, meta["run_id"], state, actor)
    question = st.chat_input("اسأل، أو اطلب إعداد مهام أو مستند للمراجعة…", disabled=config is None, max_chars=4000)
    if question:
        run_id = uid("req_")
        begun = False
        try:
            with st.spinner("يقرأ المساعد السياق ويجهّز الرد…"):
                # Revalidate the account and scope immediately before the paid call.
                fresh, revision, current_actor = store.context(token)
                data, refs, warnings = build_context(store, token, fresh, project_id, selected, question, include_work)
                if not thread_id:
                    thread_id = repo.create_thread(token, project_id)
                    st.session_state["select_ai_thread"] = thread_id
                repo.begin(token, thread_id, run_id, question, config.model, data, refs, revision, config.daily_limit)
                begun = True
                answer, actions, usage = NeonAI(config).answer(question, data, history, allow_actions and Store.can_edit(current_actor))
                repo.finish(token, run_id, answer, actions, usage, warnings)
        except WorkspaceError as exc:
            if begun:
                repo.fail(token, run_id, str(exc))
            else:
                st.error(str(exc))
                return
        except Exception:
            logging.error("AI request failed unexpectedly; sensitive exception detail omitted")
            if begun: repo.fail(token, run_id, "تعذر حفظ رد المساعد. لم تُطبّق أي تغييرات؛ راجع الاتصال قبل المحاولة مجددًا.")
            else:
                st.error("تعذر بدء المحادثة؛ تحقق من الاتصال.")
                return
        st.rerun()


def cloud_page(store, token, state, revision, actor, setting):
    Store.require(store.actor(token), "admin")
    st.subheader("حفظ دائم وربط واضح")
    st.write("قاعدة البيانات تحفظ حسابات الدخول والعمل والمحادثات. Object Storage يحفظ أصول الملفات، وAI Gateway يربط المساعد بالنموذج.")
    config, config_error = AIConfig.load(setting)
    # Keep diagnostic outcomes across reruns, but invalidate them on configuration changes.
    # Only a one-way fingerprint and redacted outcomes enter session state.
    keys = ("AWS_ENDPOINT_URL_S3", "AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
            "NEON_STORAGE_BUCKET", "NEON_AI_GATEWAY_BASE_URL", "NEON_AI_GATEWAY_TOKEN", "NEON_AI_MODEL")
    signature = hashlib.sha256(json.dumps([str(id(store))] + [str(setting(k, "")) for k in keys]).encode()).hexdigest()
    checks = st.session_state.setdefault("cloud_checks", {})
    if checks.get("signature") != signature:
        checks.clear()
        checks["signature"] = signature
    status_area = st.container()
    a, b = st.columns(2)
    if a.button("فحص مخزن الملفات", disabled=store.storage is None, width="stretch"):
        try:
            with st.spinner("يفحص الوصول إلى المخزن الخاص…"):
                store.storage.check()
            checks["storage"] = {"status": "ready", "message": "نجح الوصول إلى المخزن الخاص. لم تُنشأ ملفات ولم تتغير بيانات العمل.", "at": now_iso()}
        except WorkspaceError as exc:
            checks["storage"] = {"status": "error", "message": str(exc), "at": now_iso()}
    if b.button("اختبار تشغيل المساعد", disabled=config is None, width="stretch"):
        try:
            with st.spinner("يطلب إجابة اختبارية قصيرة من النموذج…"):
                NeonAI(config).check_inference()
            checks["ai"] = {"status": "ready", "message": "وصلت إجابة فعلية من النموذج. المساعد جاهز من مركز المساعد.", "at": now_iso()}
        except AICreditsRequired as exc:
            checks["ai"] = {"status": "credits", "message": str(exc), "at": now_iso()}
        except AIGatewayLimit as exc:
            checks["ai"] = {"status": exc.kind, "message": str(exc), "request_id": exc.request_id, "at": now_iso()}
        except WorkspaceError as exc:
            checks["ai"] = {"status": "error", "message": str(exc), "at": now_iso()}
    st.caption("فحص التخزين للقراءة فقط. اختبار المساعد يرسل جملة اختبارية قصيرة دون بيانات الفريق وقد يستهلك مقدارًا صغيرًا من رصيد AI.")
    storage_status = {"ready": "نجح الوصول إلى المخزن الخاص", "error": "تعذر الوصول — راجع نتيجة الفحص"}
    ai_status = {"ready": "جاهز — نجح تشغيل النموذج", "credits": "ينتظر رصيد AI في Neon", "daily_spend": "Neon أوقف التشغيل بسقف الصرف اليومي للحساب", "rate_limit": "حد استخدام مؤقت لدى Neon", "token_rate": "حد الرموز في الدقيقة لدى Neon", "error": "تعذر التشغيل — راجع نتيجة الفحص"}
    with status_area:
        rows = [
            {"الخدمة": "قاعدة البيانات وحسابات الفريق", "الحالة": "متصلة — الحفظ والدخول يعملان" if store.remote else "تجربة محلية — SQLite"},
            {"الخدمة": "أصول الملفات — Object Storage", "الحالة": storage_status.get(checks.get("storage", {}).get("status"), "الإعداد مكتمل — افحص المخزن") if store.storage else store.storage_error or "غير مفعّل"},
            {"الخدمة": "المساعد — AI Gateway", "الحالة": ai_status.get(checks.get("ai", {}).get("status"), "الإعداد مكتمل — اختبر تشغيل النموذج") if config else config_error},
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        for service in ("storage", "ai"):
            if result := checks.get(service):
                show = st.success if result["status"] == "ready" else st.warning if result["status"] == "credits" else st.error
                show(result["message"])
                if result["status"] == "daily_spend":
                    st.link_button("مراجعة سقف الحساب مع دعم Neon", "https://console.neon.tech/app/projects?modal=support")
                    if result.get("request_id"): st.caption("معرّف الفحص للدعم: " + result["request_id"])
                st.caption("آخر فحص في هذه الجلسة: " + result["at"])
    local = [f for f in state["files"] if f.get("blob")]
    cloud = [f for f in state["files"] if f.get("object")]
    a, b, c = st.columns(3)
    a.metric("ملفات بأصول داخل القاعدة", len(local))
    b.metric("أصول في التخزين المنفصل", len(cloud))
    c.metric("سجلات الملفات", len(state["files"]))
    if local:
        with st.container(border=True):
            st.markdown("**نقل أصول الملفات الموجودة إلى Neon Storage**")
            st.caption("تبقى النصوص والروابط والمهام محفوظة. تؤخذ نقطة رجوع قبل النقل، وتظل أصول المخزن متاحة للنسخ القديمة.")
            confirm = st.checkbox(f"أريد نقل أصول {len(local)} ملفات إلى المخزن المجهز لهذا التطبيق")
            if st.button("نقل الملفات الحالية", disabled=not confirm or store.storage is None, type="primary"):
                perform(lambda: store.migrate_originals(token, revision), "نُقلت الأصول إلى Neon Storage وحُفظت روابطها")
    elif not state["files"]:
        st.info("المكتبة جاهزة لأول ملف. ارفعه من قسم الملفات؛ تُحفظ الأصول في المخزن الخاص عند اكتمال إعداده. لا توجد ملفات قديمة تحتاج إلى النقل.")
    else:
        st.caption("لا توجد أصول داخل قاعدة البيانات تحتاج إلى النقل.")
    complete = store.storage is not None and config is not None
    with st.expander("تفاصيل الربط" if complete else "إكمال إعدادات الاتصال"):
        if complete:
            st.write(f"المخزن: {store.storage.bucket} · النموذج: {config.model}")
            st.caption("إعدادات التخزين والمساعد محملة من Secrets. استخدم الفحص أعلاه للتحقق من الوصول وتشغيل النموذج.")
        else:
            st.write("أضف إعدادات الخدمة الناقصة من Neon Connect إلى Streamlit → Settings → Secrets. أبقِ رابط القاعدة وبيانات الحسابات الحالية كما هي.")
        if store.storage is None:
            st.code('''# إعدادات التخزين فقط — استبدل الأمثلة بقيم Neon Connect
AWS_ENDPOINT_URL_S3 = "https://YOUR_STORAGE_HOST.neon.tech"
AWS_REGION = "YOUR_REGION"
AWS_ACCESS_KEY_ID = "REPLACE_WITH_STORAGE_ACCESS_KEY"
AWS_SECRET_ACCESS_KEY = "REPLACE_WITH_STORAGE_SECRET"
NEON_STORAGE_BUCKET = "gday-private"''', language="toml")
        if config is None:
            st.code('''# إعدادات المساعد فقط — استبدل الأمثلة بقيم Neon Connect
NEON_AI_GATEWAY_BASE_URL = "https://YOUR_GATEWAY_HOST.neon.tech"
NEON_AI_GATEWAY_TOKEN = "REPLACE_WITH_GATEWAY_TOKEN"
NEON_AI_MODEL = "COPY_MODEL_ID_FROM_NEON"
GDAY_AI_DAILY_LIMIT = 40
GDAY_AI_MAX_OUTPUT_TOKENS = 1800''', language="toml")
        st.caption("يجب أن يكون المخزن private. Storage يحتاج storage:read وstorage:write، وAI يحتاج ai_gateway:invoke. مفتاح إدارة Neon العام لا يوضع في المنصة.")
        if st.button("عرض النماذج المتاحة", disabled=config is None):
            try:
                models = NeonAI(config).models()
                st.write(models)
                if not models: st.warning("لا توجد نماذج مفعّلة للحساب حاليًا. راجع نتيجة اختبار التشغيل لمعرفة السبب؛ تبديل النموذج لا يرفع سقف الحساب.")
                st.caption("ظهور قائمة النماذج يثبت الوصول إلى البوابة؛ اختبار التشغيل أعلاه يتحقق من إمكانية الحصول على إجابة.")
                if config.model not in models: st.warning("اسم النموذج المحدد غير ظاهر في القائمة؛ تحقق منه في Neon.")
            except WorkspaceError as exc: st.error(str(exc))
