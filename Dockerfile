# ============================================================================
# Dockerfile —— 评测系统的"打包说明书"
# ============================================================================
# 一句话：把"Python 环境 + 我的代码 + 依赖"打成一个可以到处跑的盒子。
#
# 构建 + 运行（在cmd里做，打开cmd：按 Win 键 → 输入 cmd → 回车）：
#   cd /d "E:\8月3日Ai学习计划\每日练习\eval_system"
#   docker build -t eval-system:v1 .
#   docker run --rm --env-file .env eval-system:v1
#
# ★ --env-file .env 的意思是"把密钥从外面传进去"，
#   这样镜像里**不含任何密钥**，可以放心分享给任何人 —— 这是密钥管理的正确做法。
# ============================================================================

# ---------- 基础镜像：Python 3.10 精简版 ----------
# 选 3.10 的原因：本机就是 3.10.11，版本对上才不会出现"我这儿能跑你那儿报错"。
# 选 slim 而不是完整版：体积从 1GB 降到 150MB 左右。
FROM python:3.10-slim

# ---------- 装中文字体 ----------
# ★ 这行看着不起眼，但**不能省**：
#   slim 镜像里只有西文字体，report.py 画出来的图，中文会全部变成"方框豆腐块"。
#   这是容器化最容易被忽略的坑之一。
#   如果你暂时不要图表，可以把下面两行删掉，能省约 60MB。
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*
# rm -rf /var/lib/apt/lists/* 是清掉 apt 的缓存索引，否则白占几十 MB。
# 这三行必须写在同一条 RUN 里 —— 分开写的话，前面层的缓存文件还是会留在镜像里，
# 这叫"镜像分层"，是 Docker 面试的常考题。

# ---------- 设工作目录 ----------
WORKDIR /app
# 之后所有命令都在 /app 里执行，不用写一堆长路径。

# ---------- 先装依赖，再拷代码（★ 顺序不能反）----------
# ★ 这是 Dockerfile 最经典的一个优化，面试必问：
#   Docker 是分层缓存的。如果先 COPY . . 再装依赖，
#   那么你**改一行代码**，上面的 COPY 层就失效，
#   导致下面 pip install 全部重跑一遍 —— 每次改代码等 3 分钟。
#   反过来写：依赖清单没变 → 这一层命中缓存 → 改代码后重建只要 2 秒。
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# --no-cache-dir：不保留 pip 下载缓存，镜像更小。

# ---------- 再拷代码 ----------
# .dockerignore 会自动过滤掉 .env、__pycache__ 等不该进镜像的东西。
COPY . .

# ---------- 设时区（不然报告里的时间戳是 UTC，比北京时间差 8 小时）----------
ENV TZ=Asia/Shanghai

# ---------- 容器启动时默认干什么 ----------
# 默认跑一次全量评测（--limit 0 = 不限条数，跑全部 55 条）。
# 想跑别的命令，在 docker run 后面加，比如：
#   docker run --rm --env-file .env eval-system:v1 python eval_cli.py stat
CMD ["python", "eval_cli.py", "run", "--limit", "0"]
