# AI 科学小侦探 · 云端部署步骤

把下面 **4 个文件** 上传到云平台，就能得到一个公网链接，所有人打开即可用真 AI：

- `server.py`（后端）
- `index.html`（前端，云端版，无需访客填 key）
- `requirements.txt`（空依赖声明）
- 本 README（可不上传）

> 关键安全点：你的 DeepSeek API Key 只放在平台的「环境变量」里（服务器端），访问者**看不到、拿不到**，不会泄露。

---

## 方式一：Render（推荐，最稳）

1. 注册 **GitHub**（如果没有）：https://github.com → 新建一个仓库（比如 `ai-detective`），把上面 4 个文件传进去。
2. 注册 **Render**（用 GitHub 登录）：https://render.com
3. 点 **New + → Web Service** → 连接你刚建的 GitHub 仓库。
4. 配置：
   - Environment：**Python**
   - Build Command：留空（或 `pip install -r requirements.txt`）
   - Start Command：`python3 server.py`
5. 点 **Advanced → Environment Variables**，加一条：
   - Key：`DEEPSEEK_API_KEY`
   - Value：你的 DeepSeek Key（`sk-...`）
6. 点 **Create Web Service**，等 1–2 分钟部署完。
7. 得到链接 `https://xxx.onrender.com` —— 发给谁都能直接用真 AI。

⚠️ Render 免费版 15 分钟没人访问会「休眠」，下次打开会等约 30–60 秒才醒，正常现象。

## 方式二：Railway（备选）

1. 注册 **Railway**（GitHub 登录）：https://railway.app
2. **New Project → Deploy from GitHub repo** → 选你的仓库。
3. 加环境变量 `DEEPSEEK_API_KEY`，Start Command 填 `python3 server.py`。
4. 生成公网链接。

---

## 重要提醒

- **余额**：这是公网链接，谁都能点「生成新题」，会消耗你 DeepSeek 的余额。建议去 platform.deepseek.com 设一个**消费上限**，或只把链接发在班级小范围内。
- **限流**：后端已内置「每 10 分钟最多 60 次 AI 调用」，防止被人刷爆。
- **Key 安全**：key 只放环境变量，别贴进群、别写进 `index.html`。
- 想改题目/界面，改完重新 push 到 GitHub，Render/Railway 会自动重新部署。
