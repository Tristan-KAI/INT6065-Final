# -*- coding: utf-8 -*-
"""Vercel 无服务器函数 /api/evaluate —— 苏格拉底式点评学生对科学找错关卡的质询。零依赖（仅标准库）。"""
import json, os, ssl, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"


def _ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    for p in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
              "/etc/pki/tls/certs/ca-bundle.crt", "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem"):
        if os.path.exists(p):
            try:
                return ssl.create_default_context(cafile=p)
            except Exception:
                continue
    return ssl.create_default_context()


_CTX = _ssl()


class BadJSONError(Exception):
    pass


def call_deepseek(messages, temperature=0.8, max_tokens=1500):
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("服务器未配置 DEEPSEEK_API_KEY 环境变量")
    body = json.dumps({"model": MODEL, "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=50, context=_CTX) as r:
            return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        if e.code in (401, 403):
            raise RuntimeError("API Key 无效或没有余额/权限（HTTP %d）" % e.code)
        raise RuntimeError("DeepSeek 返回错误 %d：%s" % (e.code, detail[:200]))
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLError):
            raise RuntimeError("SSL 证书校验失败：" + str(e.reason))
        raise RuntimeError("网络错误：连不上 api.deepseek.com —— " + str(e.reason))


def extract_json(text):
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1] if "\n" in s else s
        s = s.rstrip("`")
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b == -1 or b <= a:
        raise BadJSONError("模型没有返回 JSON：" + text[:300])
    try:
        return json.loads(s[a:b + 1])
    except json.JSONDecodeError as e:
        raise BadJSONError("JSON 解析失败：" + str(e))


def call_json(system, user, temperature, max_tokens, retries=2):
    last = None
    for _ in range(retries):
        try:
            return extract_json(call_deepseek([{"role": "system", "content": system},
                                               {"role": "user", "content": user}], temperature, max_tokens))
        except BadJSONError as e:
            last = e
            user += ("\n\n【重要提醒】你上一次的输出不是合法 JSON。"
                     "请务必只输出一个 JSON 对象，不要任何多余文字、不要代码块围栏、不要注释。")
    raise RuntimeError("连续 %d 次都未返回合法 JSON：%s" % (retries, last))


EVAL_SYS = (
    "你是苏格拉底式导师，点评学生对一道「找错」关卡的质询。"
    "原则：先肯定定位，再指出证据是否充分；绝不直接说出全部标准答案，而是抛一个引导学生自己想明白的追问。"
    "只输出一个 JSON 对象。格式：\n"
    '{"rating":2,"feedback":["定位准确","但证据可以更足，请补上正确说法和依据"],"probe":"一个不直接给答案的追问"}\n'
    "rating 取值 1~3：3=错误全找到且证据充分，2=基本找到但证据不足或有误标，1=只找到部分。feedback 1~3 条中文短句。"
)


class handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            b = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            user = ("题目句子（逐段）：\n" + json.dumps(b.get("passage", []), ensure_ascii=False) +
                    "\n标准错误：\n" + json.dumps(b.get("errors", []), ensure_ascii=False) +
                    "\n学生标记的可疑段下标：" + json.dumps(b.get("highlighted", []), ensure_ascii=False) +
                    "\n学生的质疑：" + (b.get("reason", "") if b.get("reason", "").strip() else "（学生没有写质疑）"))
            out = call_json(EVAL_SYS, user, 0.3, 800)
            self._json(200, out)
        except Exception as e:
            self._json(500, {"error": str(e)})

    def log_message(self, *a):
        pass
