"""Safe phone formatting for the Arabic contact directory."""
import re
from html import escape

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_DIRECTION_MARKS = dict.fromkeys(map(ord,"\u200b\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff"))


def phone_parts(value):
    """Return readable text and an optional international dial target; never reverse digits."""
    text = str(value or "").translate(_DIGITS).translate(_DIRECTION_MARKS).strip()
    if not text or not re.fullmatch(r"[+\d\s().-]+", text):
        return text, ""
    digits = re.sub(r"\D", "", text)
    if text.startswith("00"):
        number = "+" + digits[2:]
    elif text.startswith("+") and text.count("+") == 1:
        number = "+" + digits
    elif re.fullmatch(r"966[15]\d{8}", digits):
        number = "+" + digits
    elif re.fullmatch(r"0[15]\d{8}", digits):
        number = "+966" + digits[1:]
    else:
        number = ""
    if not re.fullmatch(r"\+[1-9]\d{7,14}", number):
        return text, ""
    if re.fullmatch(r"\+966[15]\d{8}", number):
        digits = number[4:]
        return f"+966 {digits[:2]} {digits[2:5]} {digits[5:]}", number
    return number, number


def phone_html(value):
    display, number = phone_parts(value)
    label = escape(display)
    if number:
        label = f'<a href="tel:{escape(number,quote=True)}">{label}</a>'
    return f'<div class="contact-phone" dir="ltr"><bdi dir="ltr">{label}</bdi></div>' if display else ""


def matches_contact(record, query):
    query = str(query or "").translate(_DIGITS).strip()
    if not query:
        return True
    text = " ".join(str(record.get(k,"")) for k in ("name","org","phone","email"))
    if query.casefold() in text.casefold():
        return True
    if re.fullmatch(r"[+\d\s().-]+",query):
        digits = re.sub(r"\D","",query)
        if len(digits) >= 3:
            canonical = phone_parts(query)[1]
            target = phone_parts(record.get("phone",""))[1] or str(record.get("phone",""))
            key = re.sub(r"\D","",canonical) if canonical else digits.lstrip("0")
            return bool(key) and key in re.sub(r"\D","",target)
    return False
