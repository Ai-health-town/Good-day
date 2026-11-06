"""A single request box and a private, durable result inbox."""
from __future__ import annotations

import hashlib
import time
from datetime import datetime
from dataclasses import replace

import streamlit as st
from sqlalchemy import select

from ai_service import AIConfig, NeonAI
from ai_store import threads
from assistant_desk import ACTIVE, AssistantDesk, DeskWorker
from components import edit_file, edit_task, lookup
from filetools import docx_bytes
from workspace import WorkspaceError, uid, ZONE


@st.cache_resource
def resources(identity, _store, _config):
    desk = AssistantDesk(_store)
    return desk, DeskWorker(desk, _config, client_factory=NeonAI)


def _render_request(desk, worker, store, token, job):
    details, ident = job["details"], job["id"]
    st.text(details["question"])
    if job["status"] in ACTIVE:
        label = "وصل طلبك إلى gday.assistant" if job["status"] == "queued" else "المساعد يقرأ المطلوب وينفّذه…"
        st.info(label + " يمكنك التنقل؛ النتيجة تبقى محفوظة هنا.")
    elif job["status"] in ("waiting", "failed", "deferred"):
        st.warning(details.get("error") or "طلبك محفوظ ويحتاج إعادة المحاولة.")
        if job["status"] == "deferred":
            st.caption("أقرب استكمال: " + datetime.fromtimestamp(job["started"], ZONE).strftime("%I:%M %p") + " بتوقيت الرياض. الاستكمال تلقائي أثناء تشغيل المنصة، وتبقى الطلبات محفوظة إذا أعيد تشغيلها.")
        if st.button("إعادة المحاولة", key="desk_retry_" + ident, disabled=job["status"] == "deferred" and job["started"] > time.time()):
            try: desk.retry(token, ident)
            except WorkspaceError as exc: st.error(str(exc))
            else:
                worker.kick()
                st.rerun()
    else:
        with st.chat_message("assistant", avatar="✳"):
            st.markdown(job["answer"].replace("![", "\\!["), unsafe_allow_html=False)
        count = job["meta"].get("executed", 0)
        if count: st.success(f"حُفظت {count} تغييرات في المشروع بواسطة gday.assistant.")
        a, b = st.columns(2)
        a.download_button("تنزيل الرد — Word", docx_bytes("نتيجة طلب المساعد", job["answer"]),
            file_name="Gday_Assistant_Result.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="desk_download_" + ident, width="stretch")
        if b.button("فتح مهمة الطلب", key="desk_task_" + ident, width="stretch"):
            state, _, actor = store.context(token)
            task = next((t for t in state["tasks"] if t["id"] == details["task_id"]), None)
            if task: edit_task(store, token, state, actor, task)
            else: st.info("حُذفت مهمة الطلب؛ يبقى الرد محفوظًا هنا.")
        for file_id in details.get("result_files", []):
            if st.button("فتح المستند المحفوظ", key="desk_file_" + ident + file_id):
                state, _, actor = store.context(token)
                record = next((f for f in state["files"] if f["id"] == file_id), None)
                if record: edit_file(store, token, state, actor, record)
        if job["meta"].get("sources") or job["meta"].get("warnings"):
            with st.expander("المصادر وتفاصيل القراءة"):
                for source in job["meta"].get("sources", []): st.caption(f"[{source['ref']}] {source['title']} · مقتطف {source['chunk']}")
                for warning in job["meta"].get("warnings", []): st.caption(warning)


def help_center(store, token, state, actor, setting):
    if st.session_state.pop("desk_clear_input", False): st.session_state["desk_question"] = ""
    st.markdown("""<style>
.st-key-assistant_desk_intro{background:linear-gradient(115deg,#f3f0f8,#edf8f4);border:1px solid #dfeae5;border-radius:18px;padding:22px 26px;margin-bottom:14px;}
.st-key-assistant_desk_intro h3{font-size:1.65rem!important;color:#21443f;}
.st-key-assistant_desk_compose{background:#fff;border-radius:18px;}
.st-key-assistant_desk_compose textarea{font-size:1rem;line-height:1.9;}
</style>""", unsafe_allow_html=True)
    config, _ = AIConfig.load(setting)
    if config:
        config = replace(config, model=str(setting("GDAY_ASSISTANT_MODEL", "gpt-6-luna")), output_tokens=min(2400, config.output_tokens))
    fingerprint = hashlib.sha256((config.base_url + config.token + config.model + str(config.output_tokens)).encode()).hexdigest() if config else "unconfigured"
    desk, worker = resources(str(id(store)) + ":" + str(id(AssistantDesk)) + ":" + str(id(NeonAI)) + ":" + fingerprint, store, config)
    projects = state["projects"]
    if not projects:
        st.info("أضف مشروعًا أولًا ليعمل المساعد على سياقه.")
        return
    actual = [p for p in projects if p["id"] != "p_general"]
    if len(actual) == 1:
        project_id = actual[0]["id"]
    elif len(projects) == 1:
        project_id = projects[0]["id"]
    else:
        project_id = st.selectbox("المشروع", [p["id"] for p in projects], format_func=lambda i: lookup(projects, i), key="desk_project")
    with st.container(key="assistant_desk_intro"):
        st.markdown("### طلبك واضح. والباقي على المساعد ✳")
        st.write("اكتب ما تحتاجه، وسيتولى **gday.assistant** القراءة والتنفيذ ويرجع لك بالنتيجة هنا.")
        st.caption("المشروع: " + lookup(projects, project_id) + " · مهام، مستندات، ملفات، وجهات اتصال")
    with st.container(border=True, key="assistant_desk_compose"):
        examples = st.columns(3)
        for col, label, prompt in zip(examples, ["✳ ملخص المشروع", "◷ ترتيب المتابعة", "▤ تلخيص الملفات"], [
            "لخص وضع المشروع وأهم ما يحتاج متابعتي اليوم دون تعديل أي بيانات.",
            "رتب أولويات المهام الحالية، واقترح علي الخطوة التالية دون تعديلها.",
            "لخص الملفات المرتبطة بالمشروع مع أهم الاستنتاجات ومصادرها، دون تعديل البيانات."]):
            if col.button(label, key="desk_example_" + label, width="stretch"):
                st.session_state["desk_question"] = prompt
        with st.form("assistant_request", clear_on_submit=False):
            question = st.text_area("وش تحتاج من المساعد؟", key="desk_question", height=115, max_chars=4000,
                placeholder="مثال: جهز لي ملخصًا تنفيذيًا من ملفات المشروع، أو أضف مهمة متابعة لخالد…")
            submit = st.form_submit_button("إرسال إلى المساعد ←", type="primary", width="stretch")
        st.caption("طلبك يُحفظ كمهمة في المشروع مسندة للمساعد. يقرأ سياق المشروع ومقتطفات الملفات ذات الصلة، وتظهر النتيجة لحسابك هنا.")
        if submit:
            request_id = st.session_state.setdefault("desk_request_id", uid("desk_"))
            try: desk.submit(token, project_id, question, request_id)
            except WorkspaceError as exc: st.error(str(exc))
            else:
                st.session_state.pop("desk_request_id", None)
                st.session_state["desk_clear_input"] = True
                st.session_state["desk_selected_result"] = request_id
                worker.kick()
                st.rerun()
    jobs = desk.list_requests(token, project_id)
    def phase(items):
        return "active" if any(j["status"] in ACTIVE for j in items) else "deferred" if any(j["status"] == "deferred" for j in items) else "idle"
    initial_phase = phase(jobs)
    worker.kick()

    @st.fragment(run_every={"active": "2s", "deferred": "30s"}.get(initial_phase))
    def inbox():
        current = desk.list_requests(token, project_id)
        current_phase = phase(current)
        if current_phase != initial_phase: st.rerun()
        if current_phase != "idle": worker.kick()
        st.markdown("#### طلباتك ونتائجها")
        if not current:
            st.info("ابدأ أول طلب. يتولى المساعد الباقي، وتبقى النتيجة محفوظة للرجوع لها.")
        labels = {"queued": "وصل للمساعد", "pending": "جارٍ التنفيذ", "complete": "اكتمل", "waiting": "بانتظار الاستكمال", "deferred": "محفوظ للاستكمال التلقائي", "failed": "يحتاج إعادة المحاولة"}
        selected = st.session_state.get("desk_selected_result")
        if selected not in {j["id"] for j in current}: selected = current[0]["id"] if current else ""
        for index, job in enumerate(current):
            with st.expander(labels.get(job["status"], job["status"]) + " · " + job["details"]["question"][:90], expanded=job["id"] == selected):
                if job["id"] == selected:
                    _render_request(desk, worker, store, token, job)
                elif st.button("عرض الطلب والنتيجة", key="desk_show_" + job["id"]):
                    st.session_state["desk_selected_result"] = job["id"]
                    st.rerun()
    inbox()
    with store.engine.connect() as conn:
        archived = conn.execute(select(threads.c.id, threads.c.title).where(threads.c.owner_id == actor["id"],
            threads.c.project_id == project_id, ~threads.c.id.like("desk_%")).order_by(threads.c.at.desc()).limit(10)).mappings().all()
    if archived:
        with st.expander("المحادثات السابقة"):
            saved = st.selectbox("المحادثة السابقة", [r["id"] for r in archived], format_func=lambda i: next(r["title"] for r in archived if r["id"] == i))
            for message in desk.legacy_history(token, saved):
                with st.chat_message(message["role"]): st.markdown(message["content"].replace("![", "\\!["), unsafe_allow_html=False)
