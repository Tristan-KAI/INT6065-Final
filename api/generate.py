# -*- coding: utf-8 -*-
"""Vercel 无服务器函数 /api/generate —— 用 DeepSeek 生成带隐藏科学错误的关卡。零依赖（仅标准库）。"""
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


SUBJECT_HINTS = {
    "语文": "错别字、病句、成语误用、修辞或文学常识错误",
    "数学": "计算错误、公式用错、概念混淆、单位或符号错误",
    "英语": "语法错误、拼写错误、时态错误、词汇搭配误用",
    "物理": "概念倒置、公式错误、因果颠倒、数据错误",
    "化学": "方程式错误、守恒定律误用、物质性质或反应条件错误",
    "生物": "生理过程错误、遗传或生态概念错误、结构功能错配",
}


def gen_sys(subject):
    hint = SUBJECT_HINTS.get(subject, "概念倒置、数据造假、因果颠倒等")
    return (
        "你是一名经验丰富的初中" + subject + "教师，专门设计「找错」关卡：写一段初中" + subject + "的短文/题目，"
        "内嵌 1~2 处隐蔽但确定的错误，让学生找出并质询。\n"
        "本科常见错误类型参考：" + hint + "。\n"
        "要求：错误要「隐蔽但确定」，不能模棱两可；每一处错误点单独放在一个 passage 元素里，方便学生精确定位；其余正确内容也单独成段。"
        "只输出一个 JSON 对象，不要任何其他文字。格式：\n"
        '{"title":"关卡标题","subject":"学科 · 年级",'
        '"passage":[{"t":"第1段","err":false},{"t":"第2段","err":true}],'
        '"errors":[{"seg":1,"wrong":"错误表述","correct":"正确表述","probe":"不直接给答案的苏格拉底式追问"}]}\n'
        "passage 是逐段数组，err=true 表示该段含错误；errors.seg 是 passage 下标（从 0 开始），每个含错段对应一条。"
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
            subject = (b.get("subject", "") or "").strip() or "科学"
            topic = (b.get("topic", "") or "").strip()
            user = ("学科：%s；知识点：%s；难度：%s（入门=错误明显，进阶=较隐蔽，挑战=数据/因果类）。请生成关卡。"
                    % (subject, topic or "随机", b.get("difficulty", "进阶")))
            out = call_json(gen_sys(subject), user, 0.85, 1500)
            self._json(200, out)
        except Exception as e:
            self._json(500, {"error": str(e)})

    def log_message(self, *a):
        pass
