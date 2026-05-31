# 🎨 InsAuto — Instagram AI 内容自动化

一键生成产品图片 + AI 文案，自动发布到 Instagram。

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 启动
```bash
# Web 仪表盘（推荐）
streamlit run app.py

# 或桌面面板
python launcher.py
```

浏览器打开 http://localhost:8501 即可使用。

## 两种使用模式

### 🎮 离线模式（无需任何配置）
- 点击「离线模式」登录
- 🎬 **图片工作室** → 选产品 → 生成图片（免费 Pollinations.ai）
- 文案使用内置模板
- ❌ 不能发布到 Instagram

### 🔐 完整模式

1. **图片生成**
   - 默认使用 Pollinations.ai（免费，无需 API Key）
   - 可选 OpenRouter（DALL-E 3 等高质量模型），需配置 API Key

2. **AI 文案**（可选）
   - 去 [openrouter.ai/keys](https://openrouter.ai/keys) 注册获取 Key
   - 在项目目录创建 `.env` 文件：
   ```
   OPENROUTER_API_KEY=sk-or-v1-你的密钥
   ```

3. **Instagram 发布**
   - 登录页填写用户名 + Session ID
   - Session ID 获取：浏览器打开 Instagram → F12 → Application → Cookies → 复制 sessionid

## 功能

| 功能 | 说明 |
|------|------|
| 🎬 图片工作室 | 选产品、自定义 Prompt、批量生成 |
| 🖼️ 图片库 | 浏览所有生成图片 |
| 📋 发布队列 | 管理待发布内容、编辑文案 |
| ⏱ 定时发布 | 按间隔自动生成+发布 |
| 🎨 多引擎 | Pollinations(免费) / OpenRouter DALL-E 3 |
| 📐 多比例 | 1:1 / 4:5 / 9:16 / 16:9 / 3:2 / 2:3 |
| 🏷️ 多品类 | 厨房、家居、健身、美妆 40+ 产品 |

## 项目结构

```
├── app.py              # Streamlit Web 仪表盘
├── launcher.py         # Tkinter 桌面面板
├── requirements.txt    # Python 依赖
└── ins账号自动化/       # 核心包
    ├── content.py      # 图片生成 + AI 文案
    ├── bot.py          # Instagram 发布
    ├── automation.py   # 定时自动化
    ├── db.py           # SQLite 存储
    └── config.py       # 配置
```
