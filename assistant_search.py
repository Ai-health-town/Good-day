"""Local, project-scoped retrieval. No credentials, SQL, or model calls live here."""
from __future__ import annotations

import heapq
import re
import unicodedata

from filetools import file_sheets, file_text

SEARCH_VERSION = "2026-11-19.1"
_MARKS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeffـ]")
_CHARS = str.maketrans("أإآٱةىئؤ", "ااااهييو")


def normalized(value):
    value = _MARKS.sub("", unicodedata.normalize("NFKC", str(value or ""))).translate(_CHARS).casefold()
    value = value.replace("_", " ").replace("-", " ")
    return " ".join(re.sub(r"[^\w@.+\s]", " ", value).split())


_NOISE = set(normalized("ابغى ابغي ابي ابغاك ابيك بغيت تعطيني اعطني عطني عطنا وش ماهو ماهي ما هي هو هل يوجد موجود الموجود الموجودة المتاح متاح لو سمحت فضلا ارجوك من في الى على عن لدى لكل كل جميع بين مع عند لهذا هذا هذه ذلك التي الذي ان ثم او و فقط لي لنا ما ذا رقمهم ارقامهم اسماء اسم ايميلات ايميل وايميلات البريد بريد الالكتروني الإلكتروني ايميلاتهم بريدهم مدراء مدير مديري مدرائها مدراؤها المدراء المدير ومدرائها المركز المراكز للمراكز مراكز صحي الصحية الصحي مركز جهة جهات الاشخاص اتصال التواصل هاتف هواتف ارقام جوال جوالات رقم للمدير للمركز بالمنصة المنصة المشروع طلبك طلب البيانات بيانات لخص تلخيص ملف الملفات جدول جداول اكسل excel xlsx docx pdf").split())
_CHANGES = set(normalized("اضف اضافة انشئ انشاء احفظ حفظ حذف احذف امسح عدل تعديل حدث تحديث ارسل ارسال اكتب كتابة جهز تجهيز صغ صياغة رسالة رساله تقرير مهام مهمة لخص تلخيص حلل تحليل قارن مقارنة خطة خطه").split())


def query_words(value):
    words = set(re.findall(r"[\w]{2,}", normalized(value)))
    return {w for w in words if w not in _NOISE and not w.startswith(("ايميل", "وايميل"))}


def contact_intent(question):
    text = normalized(question)
    return any(term in text for term in ("ايميل", "بريد", "هاتف", "جوال", "اتصال", "مدير", "مدراء"))


def center_name(record):
    return str(record.get("centerName") or (record.get("name") if "مركز" in str(record.get("name", "")) else "") or "").strip()


def _core(record):
    value = normalized(center_name(record))
    value = re.sub(r"^مركز\s+(?:الرعايه\s+(?:الصحيه|الصحه)(?:\s+الاوليه)?\s*|صحي\s*)?", "", value).strip()
    city = normalized(record.get("city", ""))
    if city and value != city:
        for suffix in (" بب" + city, " ب" + city, " " + city):
            if value.endswith(suffix):
                value = value[:-len(suffix)].strip()
                break
    return value


def _phrase_in(phrase, text):
    return bool(phrase) and (" " + phrase + " " in " " + text + " " or
                            len(phrase.replace(" ", "")) >= 5 and phrase.replace(" ", "") in text.replace(" ", ""))


def _location_in(city, query):
    return bool(city) and bool(re.search(r"(?:^|\s)(?:ب|ل)?" + re.escape(city) + r"(?=\s|$)", query))


def contact_score(record, question):
    query, words = normalized(question), query_words(question)
    core = _core(record)
    name = normalized(record.get("name", ""))
    identity = normalized(" ".join(str(record.get(k, "")) for k in ("name", "org", "centerName", "city")))
    score = 50 * _phrase_in(core, query) + 35 * _phrase_in(name, query)
    score += 18 * _location_in(normalized(record.get("city", "")), query)
    score += 9 * len(words & query_words(core)) + 5 * len(words & query_words(identity))
    score += 25 * sum(normalized(record.get(k, "")) in query and bool(record.get(k))
                      for k in ("email", "centerEmail", "phone"))
    if score:
        score += int(bool(record.get("centerName"))) + int(bool(record.get("centerEmail")))
    return score


def rank_contacts(records, question, limit=30):
    ranked = sorted(enumerate(records), key=lambda pair: (contact_score(pair[1], question), -pair[0]), reverse=True)
    return [record for _, record in ranked[:limit]]


def compact_contact(record):
    result = {k: record.get(k, "") for k in
              ("id", "name", "org", "centerName", "city", "title", "phone", "email", "centerEmail", "version")}
    result["version"] = record.get("version", 1)
    result["notes"] = str(record.get("notes", ""))[:700]
    return result


def contact_ref(record, ref):
    return {"ref": ref, "kind": "contact", "contact_id": record["id"],
            "title": "دليل الجهات · " + (center_name(record) or str(record["name"])),
            "chunk": 1, "version": record.get("version", 1)}


def _cell(value):
    value = _MARKS.sub("", str(value or "")).replace("\n", " ").strip()
    for char in ("\\", "|", "[", "]", "<", ">", "`", "!"):
        value = value.replace(char, "\\" + char)
    return value


def quick_contact_answer(question, records):
    """Answer narrow directory lookups without inference; unknown fields use normal retrieval."""
    text = normalized(question)
    raw_words = set(text.split())
    if not contact_intent(question) or raw_words & _CHANGES or any(
        word.startswith(("واضف","وعدل","وارسل","واحفظ","واكتب","وانشئ","واحدث","وحدث","واحذف")) for word in raw_words):
        return None
    want_email = "ايميل" in text or "بريد" in text
    want_phone = any(word in text for word in ("هاتف", "جوال", "ارقام", "رقم التواصل"))
    if not want_email and not want_phone:
        return None
    bracket = re.search(r"[（(]([^()（）]{2,1000})[）)]", question)
    target_text = bracket.group(1) if bracket else " ".join(w for w in text.split() if w not in _NOISE)
    targets = [re.sub(r"^[\s\d٠-٩۰-۹.\-–]+", "", t).strip() for t in re.split(r"[,،;؛\n]+", target_text)]
    targets = [t for t in targets if query_words(t)]
    if not 1 <= len(targets) <= 12:
        return None
    selected, table, warnings = [], [], []
    for target in targets:
        ranked = rank_contacts(records, target, 8)
        if not ranked or contact_score(ranked[0], target) < 10:
            return None
        top = ranked[0]
        top_core = _core(top)
        # Two real centers with the same name need a location; never pick one silently.
        peers = [r for r in ranked if contact_score(r, target) >= contact_score(top, target)-2]
        peer_cities = {normalized(r.get("city")) for r in peers if _core(r) == top_core and r.get("city")}
        query = normalized(target)
        if len(peer_cities) > 1 and not any(_location_in(city, query) for city in peer_cities):
            return None
        if not top.get("centerName") and center_name(top):
            # Prefer the named manager over a duplicate center-only entry.
            managers = [r for r in ranked if r.get("centerName") and _core(r) == top_core]
            if managers: top = managers[0]
        official = str(top.get("centerEmail") or "").strip()
        personal = str(top.get("email") or "").strip()
        manager_requested = any(w in text for w in ("مدير", "مدراء", "مدرا", "مدرائها"))
        if want_email and (not official or manager_requested and (not personal or normalized(personal) == normalized(official))):
            return None
        if want_phone and not top.get("phone"):
            return None
        identity = query_words(" ".join(str(top.get(k, "")) for k in ("name", "org", "centerName", "city")))
        desired = query_words(target)
        desired = {w[1:] if len(w)>2 and w[0] in "بل" and w[1:] in identity else w for w in desired}
        residual = desired - identity
        label = center_name(top) or str(top.get("name", ""))
        if top.get("city"): label += " — " + str(top["city"])
        if residual:
            warnings.append("ورد في طلبك «" + target + "»؛ أقرب سجل في دليل المشروع هو «" + label + "». الاسم غير مطابق حرفيًا؛ تحقق منه قبل استخدام بياناته.")
            label += " (أقرب اسم؛ يحتاج تحققًا)"
        if top["id"] not in {r["id"] for r in selected}:
            selected.append(top)
        ref = "C" + str(next(i+1 for i,r in enumerate(selected) if r["id"] == top["id"]))
        fields = [label, str(top.get("name", ""))]
        if want_email:
            fields.append(official)
            if manager_requested: fields.append(personal)
        if want_phone: fields.append(str(top.get("phone", "")))
        table.append("| " + " | ".join(_cell(x) for x in fields) + " | [" + ref + "] |")
    headers = ["المركز أو الجهة", "الاسم"]
    if want_email:
        headers.append("بريد المركز الرسمي")
        if any(w in text for w in ("مدير", "مدراء", "مدرا", "مدرائها")): headers.append("بريد المدير")
    if want_phone: headers.append("رقم التواصل")
    headers.append("المصدر")
    answer = "من دليل الجهات في المشروع:\n\n| " + " | ".join(headers) + " |\n|" + "---|"*len(headers) + "\n" + "\n".join(table)
    if warnings: answer += "\n\n" + "\n\n".join(warnings)
    return answer, selected, warnings


def _row_text(row):
    return " | ".join(str(value if value is not None else "").replace("\n", " ")[:500] for value in row)


def _diverse(candidates, limit):
    chosen, covered = [], set()
    candidates = list(candidates)
    while candidates and len(chosen)<limit:
        best = max(candidates, key=lambda c: (len(c["words"]-covered)*8+c["score"], -c["index"]))
        chosen.append(best)
        covered |= best["words"]
        candidates.remove(best)
    return chosen


def sheet_snippets(record, question, limit=3):
    query, candidates, sequence = query_words(question), [], 0
    for sheet in file_sheets(record):
        rows = sheet.get("rows", [])
        headers = [_row_text(r) for r in rows[:3]]
        headers = "\n".join(h for h in headers if h.strip(" |"))[:700]
        hits = []
        for number,row in enumerate(rows):
            line = _row_text(row)
            if not line.strip(" |"):
                continue
            overlap = query & query_words(line)
            hits.append({"index": number, "score":len(overlap), "words":overlap, "line":line})
        # Keep candidates from the entire sheet, including rows beyond 100k text.
        shortlist = heapq.nlargest(max(12,limit*4),hits,key=lambda c:(c["score"],-c["index"]))
        if not any(h["score"] for h in shortlist) and hits:
            shortlist = [hits[i] for i in sorted({0,len(hits)//2,len(hits)-1})]
        for hit in shortlist:
            sequence += 1
            label = f"ورقة: {sheet['name']} · صف {hit['index']+1}"
            value = label + "\n" + ("عناوين وبداية الورقة:\n"+headers+"\n" if hit["index"]>=3 else "") + hit["line"]
            candidates.append(hit | {"index":sequence,"text":value[:2200],"sheet":sheet["name"],"row":hit["index"]+1})
    return [{k:c[k] for k in ("text","sheet","row")} for c in _diverse(candidates,limit)]


def text_snippets(text, question, limit=3):
    query = query_words(question)
    candidates = []
    for index,start in enumerate(range(0,len(text),1400)):
        chunk = text[start:start+1600]
        overlap = query & query_words(chunk)
        candidates.append({"index":index,"words":overlap,"score":len(overlap),"text":chunk})
    return [{"text":c["text"],"chunk":c["index"]+1} for c in _diverse(candidates,limit)]


def rank_files(records, question, limit=5):
    words, directory = query_words(question), contact_intent(question)
    def score(record):
        title = normalized(record.get("title", ""))
        title_score = len(words & query_words(title))
        body = file_text(record)
        header = ""
        if record.get("type") == "sheet":
            header = " ".join(str(s.get("name", ""))+" "+" ".join(_row_text(r) for r in s.get("rows", [])[:4]) for s in file_sheets(record))
            snippets = sheet_snippets(record,question,1)
            body = snippets[0]["text"] if snippets else ""
        directory_score = int(directory and any(term in normalized(title+" "+header) for term in ("ايميل", "بريد", "email", "مدراء", "جهات", "@")))
        return (directory_score, title_score*4+len(words & query_words(body)), title_score)
    return sorted(records,key=score,reverse=True)[:limit]
