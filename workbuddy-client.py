#!/usr/bin/env python3
"""CRM只读请求助手。凭证只从环境读取；任务文件只存编号、限流和名单元数据。"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ORIGIN = "https://jiasujiaoyu.cn"
PREFIX = "/api/workbuddy"
CUSTOMER = re.compile(r"/(?:customer)/([1-9][0-9]*)(?:/|$)")
LISTS = {"/my-customers", "/my-customers/followups", "/customers/search", "/pool/claimable",
         "/analytics/customers", "/analytics/customers/followups", "/private-team/customers",
         "/private-team/customers/notes", "/private-team/customers/followups"}


class Stop(Exception):
    def __init__(self, code, **details):
        self.result = {"ok": False, "error": code, **details}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def exchange(url, token, task=None):
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    if task:
        headers.update({"X-WorkBuddy-Task-ID": task["task_id"], "X-WorkBuddy-Task-Purpose": task["task_purpose"]})
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.build_opener(NoRedirect()).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        response = error
    except (urllib.error.URLError, TimeoutError, OSError):
        raise Stop("network_unavailable", retryable=False)
    with response:
        # 限定单次内存占用，禁止跟随重定向把凭证送到其他地址。
        raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise Stop("response_too_large", retryable=False)
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            raise Stop("invalid_response", http_status=response.code, retryable=False)
        return response.code, data, response.headers


def relative(value, full=False):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment or not parsed.path.startswith("/"):
        raise Stop("relative_workbuddy_path_required")
    path = parsed.path[len(PREFIX):] if parsed.path.startswith(PREFIX + "/") else parsed.path
    if "\\" in path or "%" in path or any(x in (".", "..") for x in path.split("/")) or path.startswith("/admin"):
        raise Stop("unsupported_path")
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if any(k in ("task_id", "task_purpose") for k, _ in query):
        raise Stop("task_context_is_managed")
    if re.fullmatch(r"/customer/[1-9][0-9]*/profile", path):
        query = [(k, v) for k, v in query if k != "view"] + [("view", "full" if full else "summary")]
    return path, query


class Client:
    def __init__(self, state, token, transport=exchange):
        self.state, self.token, self.transport = state, token, transport

    def get(self, value, full=False):
        path, query = relative(value, full)
        remaining = int(self.state.get("next_allowed_at", 0) - time.time() + 0.999)
        if remaining > 0:
            raise Stop("wait_before_next_request", retry_after_seconds=remaining)
        target = CUSTOMER.search(path)
        if target and self.state.get("invalid_batch") and target[1] not in self.state.get("confirmed_ids", []):
            raise Stop("invalid_customer_batch_stopped", retryable=False, next_action="refresh_authorized_list")
        status, data, headers = self.transport(ORIGIN + PREFIX + path + ("?" + urllib.parse.urlencode(query) if query else ""), self.token, self.state)
        self.state["requests"] = self.state.get("requests", 0) + 1
        if status == 429:
            try:
                wait = int(data.get("retry_after_seconds") or headers.get("Retry-After") or 60)
            except (ValueError, TypeError, AttributeError):
                wait = 60
            self.state["next_allowed_at"] = time.time() + max(1, min(wait, 86400))
        if status == 404 and target:
            self.state["invalid_batch"] = True
            self.state["confirmed_ids"] = []
        if status >= 400 or not isinstance(data, dict) or data.get("ok") is False:
            # 原响应照实保留给调用者；没有自动重试或自动切换账号。
            raise Stop("request_failed", http_status=status, response=data, retryable=False)
        if path in LISTS and isinstance(data.get("list"), list):
            ids = [str(row.get("客户编号")) for row in data["list"] if isinstance(row, dict) and isinstance(row.get("客户编号"), int) and row["客户编号"] > 0]
            self.state["confirmed_ids"] = list(dict.fromkeys(self.state.get("confirmed_ids", []) + ids))[-5000:]
        return data

    def collect(self, value, max_pages, emit):
        path, query = relative(value)
        if path not in LISTS - {"/customers/search"}:
            raise Stop("collect_requires_batch_list")
        values = dict(query)
        page = int(values.get("page", "1"))
        if page < 1:
            raise Stop("bad_page")
        first_page = page
        for _ in range(max_pages):
            values["page"] = str(page)
            data = self.get(path + "?" + urllib.parse.urlencode(values))
            emit({"page": page, "data": data})
            rows = data.get("list")
            if not isinstance(rows, list):
                raise Stop("pagination_metadata_missing")
            has_more = data.get("has_more", data.get("hasMore"))
            if has_more is None and isinstance(data.get("total"), int):
                size = data.get("pageSize", data.get("page_size", values.get("page_size")))
                if size is not None and int(size) > 0:
                    has_more = page * int(size) < data["total"]
            if has_more is False:
                return {"ok": True, "complete": first_page == 1, "reached_end": True,
                        "first_page": first_page, "last_page": page}
            if has_more is not True or not rows:
                raise Stop("pagination_metadata_missing", complete=False)
            next_page = data.get("nextPage", data.get("next_page", page + 1))
            if not isinstance(next_page, int) or next_page <= page:
                raise Stop("pagination_not_advancing", complete=False)
            page = next_page
        return {"ok": True, "complete": False, "first_page": first_page, "next_page": page, "reason": "page_limit"}


def save(file, state):
    temporary = file.with_name(file.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
        os.replace(temporary, file)
    finally:
        if temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("begin").add_argument("purpose")
    get = sub.add_parser("get"); get.add_argument("path"); get.add_argument("--full", action="store_true")
    collect = sub.add_parser("collect"); collect.add_argument("path"); collect.add_argument("--max-pages", type=int, default=10)
    args = parser.parse_args()
    token = os.environ.get("WORKBUDDY_TOKEN", "")
    if not token:
        raise Stop("WORKBUDDY_TOKEN_required")
    file = args.state.expanduser()
    if file.is_symlink():
        raise Stop("state_symlink_forbidden")
    lock = file.with_name(file.name + ".lock")
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise Stop("task_busy", retryable=False)
    os.close(fd)
    state = None
    emit = lambda item: print(json.dumps(item, ensure_ascii=False), flush=True)
    fingerprint = hashlib.sha256(token.encode()).hexdigest()
    try:
        if args.command == "begin":
            if file.exists():
                raise Stop("use_new_task_file")
            status, data, _ = exchange(ORIGIN + PREFIX + "/guide?" + urllib.parse.urlencode({"task_purpose": args.purpose}), token)
            if status != 200 or not isinstance(data, dict) or not data.get("task_context"):
                raise Stop("task_start_failed", http_status=status)
            state = {**data["task_context"], "credential_fingerprint": fingerprint, "requests": 1}
            emit(data)
        else:
            with open(file, encoding="utf-8") as stream:
                state = json.load(stream)
            if state.get("credential_fingerprint") != fingerprint:
                state = None
                raise Stop("task_account_changed")
            client = Client(state, token)
            if args.command == "get":
                emit(client.get(args.path, args.full))
            else:
                if not 1 <= args.max_pages <= 100:
                    raise Stop("max_pages_out_of_range")
                emit(client.collect(args.path, args.max_pages, emit))
    finally:
        try:
            if state is not None:
                save(file, state)
        finally:
            lock.unlink()


if __name__ == "__main__":
    try:
        main()
    except Stop as error:
        print(json.dumps(error.result, ensure_ascii=False)); sys.exit(2)
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"ok": False, "error": "invalid_local_task_state"})); sys.exit(2)
