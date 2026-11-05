"""Private, branch-scoped Neon Object Storage. Credentials never enter records."""
from __future__ import annotations

import base64
import copy
import hashlib
import re
from urllib.parse import urlsplit

from workspace import WorkspaceError

MAX_FILE = 8 * 1024 * 1024


def neon_host(value):
    value = str(value or "").strip().rstrip("/")
    url = urlsplit(value)
    try:
        port = url.port
    except ValueError:
        raise WorkspaceError("عنوان Neon غير صالح.") from None
    if (url.scheme != "https" or not url.hostname or not url.hostname.endswith(".neon.tech")
            or url.username or url.password or port not in (None, 443)
            or url.path or url.query or url.fragment):
        raise WorkspaceError("انسخ عنوان الخدمة الأساسي HTTPS من Neon Connect دون أي مسار أو مفاتيح.")
    return value


def validate_object(ref):
    if not isinstance(ref, dict) or set(ref) != {"version", "endpoint", "bucket", "key", "sha256", "size"}:
        raise WorkspaceError("مرجع الملف السحابي غير صالح.")
    neon_host(ref["endpoint"])
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", str(ref["bucket"])):
        raise WorkspaceError("اسم مخزن الملفات غير صالح.")
    digest = ref["sha256"]
    if (ref["version"] != 1 or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or ref["key"] != "gday/v1/" + digest
            or type(ref["size"]) is not int or not 0 <= ref["size"] <= MAX_FILE):
        raise WorkspaceError("بصمة الملف السحابي أو حجمه غير صالح.")
    return ref


class NeonStorage:
    def __init__(self, endpoint, bucket, access_key, secret_key, region, client=None):
        self.endpoint = neon_host(endpoint)
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", str(bucket)):
            raise WorkspaceError("اسم مخزن الملفات غير صالح.")
        self.bucket = bucket
        if client is None:
            import boto3
            from botocore.config import Config
            client = boto3.client("s3", endpoint_url=self.endpoint, region_name=region,
                aws_access_key_id=access_key, aws_secret_access_key=secret_key,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                    retries={"total_max_attempts": 1}, connect_timeout=10, read_timeout=30))
        self.client = client

    def check(self):
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            raise WorkspaceError("تعذر الوصول إلى مخزن الملفات. تحقق من المنطقة واسم المخزن وصلاحية storage:read/write.") from None

    def externalize(self, record):
        result = copy.deepcopy(record)
        if not result.get("blob"):
            return result
        try:
            raw = base64.b64decode(result["blob"], validate=True)
        except (ValueError, TypeError):
            raise WorkspaceError("الملف الأصلي غير صالح.") from None
        if len(raw) > MAX_FILE:
            raise WorkspaceError("الحد الأقصى لكل ملف 8 ميجابايت.")
        digest = hashlib.sha256(raw).hexdigest()
        key = "gday/v1/" + digest
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=raw,
                ContentType="application/octet-stream", Metadata={"sha256": digest})
        except Exception:
            raise WorkspaceError("لم ينجح رفع الملف إلى Neon؛ لم يُحفظ رابط بديل لملف ناقص. أعد المحاولة بعد فحص الاتصال.") from None
        result["object"] = {"version": 1, "endpoint": self.endpoint, "bucket": self.bucket,
                            "key": key, "sha256": digest, "size": len(raw)}
        result.pop("blob", None)
        return result

    def download(self, ref):
        validate_object(ref)
        if ref["endpoint"] != self.endpoint or ref["bucket"] != self.bucket:
            raise WorkspaceError("هذا الأصل مرتبط بمخزن مختلف. أعد إعداد مخزنه الأصلي أو استورد نسخة تشمل الأصول.")
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=ref["key"])
            stream = response["Body"]
            try:
                raw = stream.read(MAX_FILE + 1)
            finally:
                stream.close()
        except Exception:
            raise WorkspaceError("تعذر تنزيل الملف من Neon. تحقق من الاتصال وبقاء الأصل في المخزن.") from None
        if len(raw) != ref["size"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise WorkspaceError("فشل التحقق من سلامة الملف الأصلي.")
        return raw


STORAGE_KEYS = ("AWS_ENDPOINT_URL_S3", "NEON_STORAGE_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION")


def storage_from_settings(setting):
    values = [str(setting(k, "")).strip() for k in STORAGE_KEYS]
    if not any(values):
        return None, "لم يُفعّل التخزين المنفصل؛ تبقى الملفات الصغيرة محفوظة في قاعدة البيانات."
    if not all(values) or any(v.startswith(("REPLACE", "YOUR_", "https://YOUR_")) for v in values):
        return None, "إعدادات تخزين الملفات غير مكتملة في Secrets."
    try:
        return NeonStorage(*values), ""
    except WorkspaceError as exc:
        return None, str(exc)
