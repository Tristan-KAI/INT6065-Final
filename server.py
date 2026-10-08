# -*- coding: utf-8 -*-
"""
AI 科学小侦探 · 云端后端（零依赖，仅 Python 标准库）
部署到 Render / Railway 后得到一个公网链接，所有人打开即可使用真 AI。

启动命令： python3 server.py
环境变量： DEEPSEEK_API_KEY = 你的 DeepSeek Key（只在服务器端，访问者看不到）
          PORT（平台自动注入，默认 8000）
"""
import json, os, ssl, threading, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8000"))
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(BASE_DIR, "index.html")

api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()

# 简单限流：每 10 分钟最多 60 次 AI 调用，防止公网滥用烧你的余额
_lock = threading.Lock()
_times = []
def _rate_ok(max_calls=60, window=600):
    with _lock:
        now = time.time()
        while _times and now - _times[0] > window:
            _times.pop(0)
        if len(_times) >= max_calls:
            return False
        _times.append(now)
        return True


class BadJSONError(Exception):
    pass


def _make_ssl_context():
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


_SSL_CONTEXT = _make_ssl_context()


def call_deepseek(messages, temperature=0.8, max_tokens=1500):
    if not api_key:
        raise RuntimeError("服务器未配置 DEEPSEEK_API_KEY 环境变量")
    body = json.dumps({"model": MODEL, "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=90, context=_SSL_CONTEXT) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        if e.code in (401, 403):
            raise RuntimeError("API Key 无效或没有余额/权限（HTTP " + str(e.code) + "）")
        raise RuntimeError("DeepSeek 返回错误 " + str(e.code) + "：" + detail[:200])
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLError):
            raise RuntimeError("SSL 证书校验失败：" + str(e.reason))
        raise RuntimeError("网络错误：连不上 api.deepseek.com —— " + str(e.reason))
    return data["choices"][0]["message"]["content"]


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
    last_err = None
    for attempt in range(retries):
        try:
            text = call_deepseek([{"role": "system", "content": system},
                                  {"role": "user", "content": user}], temperature, max_tokens)
            return extract_json(text)
        except BadJSONError as e:
            last_err = e
            user += ("\n\n【重要提醒】你上一次的输出不是合法 JSON。"
                     "请务必只输出一个 JSON 对象，不要任何多余文字、不要代码块围栏、不要注释。")
    raise RuntimeError("连续 " + str(retries) + " 次都未返回合法 JSON：" + str(last_err))


GEN_SYS = (
    "你是一名经验丰富的初中科学教师，专门设计「科学找错」关卡。"
    "写一段初中科学短文（3~6 个短句/短语），内嵌 1~2 处隐蔽的科学错误（概念倒置、数据造假、因果颠倒等）。"
    "要求：每一处错误点单独放在一个 passage 元素里，方便学生精确定位；其余正确内容也单独成段。"
    "只输出一个 JSON 对象，不要任何其他文字。格式：\n"
    '{"title":"关卡标题","subject":"学科 · 年级",'
    '"passage":[{"t":"第1段","err":false},{"t":"第2段","err":true}],'
    '"errors":[{"seg":1,"wrong":"错误表述","correct":"正确表述","probe":"不直接给答案的苏格拉底式追问"}]}\n'
    "passage 是逐段数组，err=true 表示该段含科学错误；errors.seg 是 passage 下标（从 0 开始），每个含错段对应一条。"
)


def gen_level(topic, difficulty):
    user = ("知识点：%s；难度：%s（入门=错误明显，进阶=较隐蔽，挑战=数据/因果类）。请生成关卡。" % (topic, difficulty))
    return call_json(GEN_SYS, user, 0.85, 1500)


EVAL_SYS = (
    "你是苏格拉底式科学导师，点评学生对一道「科学找错」关卡的质询。"
    "原则：先肯定定位，再指出证据是否充分；绝不直接说出全部标准答案，而是抛一个引导学生自己想明白的追问。"
    "只输出一个 JSON 对象。格式：\n"
    '{"rating":2,"feedback":["定位准确","但证据可以更足，请补上正确说法和依据"],"probe":"一个不直接给答案的追问"}\n'
    "rating 取值 1~3：3=错误全找到且证据充分，2=基本找到但证据不足或有误标，1=只找到部分。feedback 1~3 条中文短句。"
)


def eval_level(passage, errors, highlighted, reason):
    user = ("题目句子（逐段）：\n" + json.dumps(passage, ensure_ascii=False) +
            "\n标准错误：\n" + json.dumps(errors, ensure_ascii=False) +
            "\n学生标记的可疑段下标：" + json.dumps(highlighted, ensure_ascii=False) +
            "\n学生的质疑：" + (reason if reason.strip() else "（学生没有写质疑）"))
    return call_json(EVAL_SYS, user, 0.3, 800)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                with open(HTML_FILE, "rb") as f:
                    html = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            except FileNotFoundError:
                self._send(404, {"error": "找不到 index.html，请确认它与 server.py 在同一目录"})
        else:
            self._send(404, {"error": "Not Found"})

    def do_POST(self):
        try:
            b = self._body()
            if self.path == "/api/generate":
                if not _rate_ok():
                    self._send(429, {"error": "请求过于频繁，请稍后再试（为保护 API 配额）"})
                    return
                self._send(200, gen_level(b.get("topic", "随机科学知识"), b.get("difficulty", "进阶")))
            elif self.path == "/api/evaluate":
                if not _rate_ok():
                    self._send(429, {"error": "请求过于频繁，请稍后再试（为保护 API 配额）"})
                    return
                self._send(200, eval_level(b.get("passage", []), b.get("errors", []),
                                           b.get("highlighted", []), b.get("reason", "")))
            else:
                self._send(404, {"error": "未知接口"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    if not os.path.exists(HTML_FILE):
        print("⚠️  找不到 index.html，请把它和 server.py 放在同一目录。")
    print("=" * 52)
    print("  🔍 AI 科学小侦探 · 云端后端已启动")
    print("  端口：%d（平台会通过 PORT 环境变量注入）" % PORT)
    print("  打开站点首页即可使用真 AI")
    print("=" * 52)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
