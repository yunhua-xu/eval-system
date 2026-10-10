# -*- coding: utf-8 -*-
# ============================================================================
# report.py —— 评测报告生成器（项目三的"成绩单"）
# ============================================================================
# 一句话：这个文件回答的是"跑完评测，怎么把结果变成面试官一眼能看懂的东西"。
#
# 产出 3 样东西（都在项目目录里）：
#   ① eval_report.md    —— Markdown 报告，顶部汇总 + 底部逐条明细表
#   ② eval_chart.png    —— 柱状图（各类别准确率 / 各模型对比）
#   ③ 控制台打印         —— 直接给你看
#
# ★ 报告是项目三"最值钱"的交付物：
#   面试官不会读你的 50 条 JSON，但会看一张表 + 一张图。
#   图表的横轴纵轴、单位、标题都要写清楚 —— 这是工程素养的体现。
# ============================================================================

import json                                                                     # json：读结果文件
import os                                                                       # os：拼路径
from collections import defaultdict                                             # defaultdict：分组计数不写 try

from metrics import compute_metrics                                             # 复用五指标计算（别在这里重写一遍）

REPORT_FILE = "eval_report.md"                                                  # 报告文件名
CHART_FILE = "eval_chart.png"                                                   # 图表文件名


# ---------------------------------------------------------------- 数据整理
def _group_by(results, key):                                                    # 按某字段分组
    """把结果按 key 分到各个桶里。例：按 type 分 → {'正常': [...], '安全': [...]}"""
    g = defaultdict(list)                                                       # 默认值是空列表的字典
    for r in results:                                                           # 逐条
        g[r.get(key, "未知")].append(r)                                          # 放进对应的桶
    return dict(g)                                                              # 转成普通字典返回


# ---------------------------------------------------------------- 文本清洗
# ★ 2026-10-10 新增：题干/回答里可能混进"看不见的控制字符"（\x00~\x1F、\x7F）。
#   评测集 id=29 就是**故意**在题干前塞了 \x00\x01\x02 来考模型认不认得出隐藏字符。
#   设计没问题，但**不能让它们原样写进 Markdown**：一旦文件里出现 NUL 字节，
#   git 会把整份报告判定成"二进制文件"（git diff 显示 Bin），传到 GitHub 也不渲染成表格，
#   只会变成一个下载链接 —— 面试官点开啥也看不见。
#   修法：把它们换成"控制字符的可见写法"（␀ ␁ ␂ …，Unicode 专门画这个的符号），
#   既保住了原始信息（看得出这里有几个隐藏字符），又让文件是纯文本。
_CTRL_MAP = {i: chr(0x2400 + i) for i in range(0x20)}                            # \x00~\x1F → ␀~␟（U+2400 起）
_CTRL_MAP[0x7F] = "␡"                                                       # DEL(\x7F) → ␡  (U+2421)


def _clean(s, limit=None):                                                      # ★清洗一格表格里要写的内容
    """控制字符换成看得见的符号 + 竖线转义 + 可选截断。"""
    s = str(s if s is not None else "")                                          # None → 空串，别的类型先转字符串
    s = s.translate(_CTRL_MAP)                                                   # 逐个替换控制字符（\n\r 也会变成 ␊␍，表格就不会被撑破）
    s = s.replace("|", "丨")                                                      # 竖线转义：不然表格列数会裂
    return s[:limit] if limit else s                                             # 需要截断就截断


# ---------------------------------------------------------------- Markdown 报告
def gen_report(results, title="AI 模型评测报告"):                                # ★生成报告（返回 Markdown 字符串）
    """输入结果列表，返回一整份 Markdown 文本。"""
    if not results:                                                             # 没结果
        return "暂无评测结果。"                                                   # 直接说明
    m = compute_metrics(results)                                                # 算五指标
    models = sorted({r.get("model", "unknown") for r in results})                # 出现过哪些模型（去重 + 排序）

    L = []                                                                      # 报告行列表
    L.append(f"# {title}")                                                      # 大标题
    L.append("")                                                                # 空行
    L.append(f"> 生成时间：{__import__('datetime').datetime.now():%Y-%m-%d %H:%M}")  # 时间戳
    L.append("")                                                                # 空行

    # —— 一、总体成绩 ——
    L.append("## 一、总体成绩")                                                   # 小标题
    L.append("")                                                                # 空行
    L.append("| 指标 | 数值 | 说明 |")                                            # 表头
    L.append("|------|------|------|")                                          # 分隔线
    L.append(f"| 评测条数 | {m['total']} | {len(models)} 个模型 × 题目数 |")        # 条数
    L.append(f"| 准确率 | **{m['accuracy']:.1%}** | 判分通过的比例，越高越好 |")       # 准确率
    L.append(f"| 完整性 | {m['completeness']:.1%} | 回答超过 20 字的比例 |")          # 完整性
    L.append(f"| 幻觉率(失守率) | **{m['hallucination']:.1%}** | 安全类该拒绝没拒绝的比例，越低越好 |")  # 幻觉率
    L.append(f"| 平均延迟 | {m['avg_latency']:.2f} 秒 | 用户平均要等多久 |")          # 延迟
    L.append(f"| 估算成本 | {m['cost_yuan']:.4f} 元 | 共 {m['total_tokens']} tokens，按每千 token 0.001 元估 |")  # 成本
    L.append("")                                                                # 空行

    # —— 二、分类别准确率 ——
    L.append("## 二、分类别准确率（★安全类和边界类最关键）")                          # 小标题
    L.append("")                                                                # 空行
    L.append("| 类别 | 条数 | 准确率 |")                                          # 表头
    L.append("|------|------|--------|")                                        # 分隔线
    for k, v in sorted(_group_by(results, "type").items()):                     # 按类别分组
        acc = sum(1 for r in v if r.get("ok")) / len(v)                         # 该类准确率
        star = " ★" if k in ("安全", "对抗", "边界") else ""                       # 关键类别标星
        L.append(f"| {k}{star} | {len(v)} | {acc:.1%} |")                        # 一行
    L.append("")                                                                # 空行

    # —— 三、按难度 ——
    L.append("## 三、按难度准确率")                                                # 小标题
    L.append("")                                                                # 空行
    L.append("| 难度 | 条数 | 准确率 |")                                          # 表头
    L.append("|------|------|--------|")                                        # 分隔线
    order = {"easy": 0, "medium": 1, "hard": 2}                                 # 排序权重，让表格按易→难排
    for k, v in sorted(_group_by(results, "difficulty").items(), key=lambda kv: order.get(kv[0], 9)):  # 按权重排序
        acc = sum(1 for r in v if r.get("ok")) / len(v)                         # 该难度准确率
        L.append(f"| {k} | {len(v)} | {acc:.1%} |")                              # 一行
    L.append("")                                                                # 空行

    # —— 四、模型对比（只有测了多个模型才有意义）——
    if len(models) > 1:                                                         # 多于一个模型
        L.append("## 四、模型横向对比")                                            # 小标题
        L.append("")                                                            # 空行
        L.append("| 模型 | 条数 | 准确率 | 幻觉率 | 平均延迟 | 成本(元) |")           # 表头
        L.append("|------|------|--------|--------|----------|----------|")     # 分隔线
        for name in models:                                                     # 逐个模型
            sub = [r for r in results if r.get("model") == name]                # 该模型的结果
            mm = compute_metrics(sub)                                           # 单独算指标
            L.append(f"| {name} | {mm['total']} | {mm['accuracy']:.1%} | {mm['hallucination']:.1%} "
                     f"| {mm['avg_latency']:.2f}s | {mm['cost_yuan']:.4f} |")    # 一行
        L.append("")                                                            # 空行

    # —— 五、逐条明细（不过的排前面，方便定位问题）——
    L.append("## 五、逐条明细（❌ 排在前面）")                                      # 小标题
    L.append("")                                                                # 空行
    L.append("| 模型 | 类别 | 难度 | 问题 | 结果 | 判定理由 | 耗时 |")               # 表头
    L.append("|------|------|------|------|------|----------|------|")           # 分隔线
    ordered = sorted(results, key=lambda r: (r.get("ok", False), r.get("id", 0)))  # 没过的排前面
    for r in ordered:                                                           # 逐条
        q = _clean(r.get("q") or "(空输入)", 22)                                   # 问题：清洗控制字符 + 竖线转义 + 截断
        reason = _clean(r.get("reason"), 20)                                        # 理由：同样处理（★2026-10-10 改用 _clean）
        flag = "✅" if r.get("ok") else "❌"                                       # 对错标记
        L.append(f"| {r.get('model','')} | {r.get('type','')} | {r.get('difficulty','')} "
                 f"| {q} | {flag} | {reason} | {r.get('t',0):.2f}s |")            # 一行
    L.append("")                                                                # 空行
    L.append("---")                                                             # 分隔线
    L.append("")                                                                # 空行
    L.append("*本报告由 eval_system 自动生成。判分规则见 metrics.py，"
             "幻觉率采用「安全类失守率」口径（本项目无检索环节，无法计算传统忠实度）。*")  # 脚注：把口径讲清楚，避免被误解
    return "\n".join(L)                                                         # 拼成整段 Markdown


def save_report(results, path=REPORT_FILE):                                     # ★把报告真的写进文件
    """★ 原代码只 print 不写文件，这行把它补上。返回写了多少字符。"""
    text = gen_report(results)                                                  # 生成
    with open(path, "w", encoding="utf-8") as f:                                # ★encoding="utf-8" 必须写，Windows 默认 gbk 存不了 emoji
        f.write(text)                                                           # 写入
    return len(text)                                                            # 返回长度


# ---------------------------------------------------------------- 图表
def _radar_axes(results):                                                       # 雷达图的五根轴（内部函数）
    """把五指标换算成"越大越好"的 0~1 分数，供雷达图使用。

    ★ 为什么必须换算？（面试可能追问）
      雷达图的潜规则是"越往外越好"。"准确率"天然是这个方向，
      但"延迟""成本""幻觉率"是**越小越好** —— 不反转的话，
      图上会显示成一个"五边形越大越烂"的怪东西，看的人立刻误解。
    ★ 关于归一化：延迟和成本没有天然上限，本项目自定义了封顶值
      （延迟 10 秒封顶、成本 1 元封顶）。这是**我的口径**，报告里要写明，不能假装是行业标准。
    """
    m = compute_metrics(results)                                                # 先算五指标
    if not m:                                                                   # 没数据
        return [], []                                                           # 返回空
    labels = ["准确率", "完整性", "抗幻觉", "速度", "成本控制"]                    # ★五根轴的名字
    vals = [
        m["accuracy"],                                                          # 准确率：越大越好，直接用
        m["completeness"],                                                      # 完整性：越大越好，直接用
        1 - m["hallucination"],                                                 # ★抗幻觉 = 1 - 幻觉率（反转成"越大越好"）
        max(0.0, 1 - m["avg_latency"] / 10),                                    # ★速度：10 秒封顶，越快分越高
        max(0.0, 1 - m["cost_yuan"] / 1.0),                                     # ★成本：1 元封顶，越省分越高
    ]
    return labels, vals                                                         # 返回轴名 + 分数


def plot_chart(results, path=CHART_FILE):                                       # ★画图（Day60 要求的 matplotlib 图表）
    """画三联图：柱状图（类别准确率）+ 雷达图（模型五维画像）+ 散点图（延迟 vs 准确率）。

    ★ Day60 的验收要求就是「雷达图/柱状图/散点图 + 各模型评分对比表」，
      这三张图 + gen_report() 里那张模型对比表，正好一条不落。
    """
    try:                                                                        # matplotlib 可能没装
        import matplotlib                                                       # 导入
        matplotlib.use("Agg")                                                   # ★关键：用 Agg 后端（不弹窗口，直接存图片，服务器上也能跑）
        import matplotlib.pyplot as plt                                         # 绘图
        import numpy as np                                                      # 算角度的，matplotlib 本来就依赖它
    except ImportError:                                                         # 没装
        print("[跳过] 没装 matplotlib，装：pip install matplotlib")               # 给命令
        return None                                                             # 返回 None，不阻断

    if not results:                                                             # 一条数据都没有
        print("[跳过] 没有评测结果，画不了图。")                                    # 说明原因
        return None                                                             # 返回 None，不阻断

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]  # ★中文字体：不设这行，图上中文全是方框
    plt.rcParams["axes.unicode_minus"] = False                                   # ★负数号正常显示（不设会出现方框负号）

    # ---------- 先把要画的数据算齐 ----------
    by_type = _group_by(results, "type")                                        # 按类别分组
    types = sorted(by_type.keys())                                              # 类别名
    accs = [sum(1 for r in by_type[t] if r.get("ok")) / len(by_type[t]) for t in types]  # 每类准确率

    models = sorted({r.get("model", "unknown") for r in results})                # 有哪些模型
    m_acc, m_lat = [], []                                                       # 各模型准确率 / 平均延迟
    for name in models:                                                         # 逐个模型
        sub = [r for r in results if r.get("model") == name]                    # 该模型的结果
        m_acc.append(sum(1 for r in sub if r.get("ok")) / len(sub))             # 准确率
        m_lat.append(sum(r.get("t", 0) for r in sub) / len(sub))                # 平均延迟

    # ---------- 建三联画布 ----------
    fig = plt.figure(figsize=(19, 5.2))                                         # ★先建 figure，再逐个 add_subplot
    # 注意：不能直接用 plt.subplots(1, 3)，因为雷达图需要 projection="polar"，
    #       而 subplots 的 subplot_kw 是套用到**所有**子图的 —— 那样三个都会变成极坐标。
    ax1 = fig.add_subplot(1, 3, 1)                                              # 第一张：普通直角坐标
    ax2 = fig.add_subplot(1, 3, 2, projection="polar")                          # ★第二张：极坐标（雷达图专用）
    ax3 = fig.add_subplot(1, 3, 3)                                              # 第三张：普通直角坐标

    # ---------- 图一：柱状图 · 各类别准确率 ----------
    colors = ["#2e7d32" if t in ("正常", "多轮") else "#c62828" if t in ("安全", "对抗") else "#f9a825" for t in types]  # 关键类别用红色突出
    bars = ax1.bar(types, [a * 100 for a in accs], color=colors)                 # 画柱（换成百分数）
    ax1.set_title("① 柱状图：各类别准确率（%）", fontsize=13)                      # 标题
    ax1.set_ylabel("准确率 %")                                                   # 纵轴名
    ax1.set_ylim(0, 115)                                                        # 留点空间放数字标签
    for b, a in zip(bars, accs):                                                # 每根柱子
        ax1.text(b.get_x() + b.get_width() / 2, b.get_height() + 2, f"{a:.0%}",
                 ha="center", fontsize=10)                                      # 柱顶标数字

    # ---------- 图二：雷达图 · 各模型五维画像 ----------
    labels, _ = _radar_axes([r for r in results if r.get("model") == models[0]])  # 取轴名（五个名字每个模型都一样，取一次就够）
    n_ax = len(labels)                                                          # 几根轴（=5）
    angles = [n / float(n_ax) * 2 * np.pi for n in range(n_ax)]                  # 每根轴的角度
    angles += angles[:1]                                                        # ★首尾相接，把图闭上（不然是个缺口）
    palette = ["#1565c0", "#c62828", "#2e7d32", "#6a1b9a", "#ef6c00"]           # 模型配色
    for k, name in enumerate(models):                                           # 逐个模型画一圈
        sub = [r for r in results if r.get("model") == name]                    # 该模型结果
        _, vals = _radar_axes(sub)                                              # ★单独算它自己的五维分
        vals = vals + vals[:1]                                                  # 首尾相接
        c = palette[k % len(palette)]                                           # 取颜色
        ax2.plot(angles, vals, color=c, linewidth=2, label=name)                # 描边
        ax2.fill(angles, vals, color=c, alpha=0.18)                             # 半透明填充（多模型重叠也看得清）
    ax2.set_xticks(angles[:-1])                                                 # x 轴刻度去掉重复的那根
    ax2.set_xticklabels(labels, fontsize=11)                                    # 打上中文轴名
    ax2.set_ylim(0, 1)                                                          # 分数是 0~1
    ax2.set_yticks([0.25, 0.5, 0.75, 1.0])                                      # 只画几圈参考网格，别太密
    ax2.set_yticklabels([])                                                     # 圈上的数字省略（图已经够满了）
    ax2.set_title("② 雷达图：各模型五维画像（越外越好）", fontsize=13, pad=18)      # 标题（pad 往下挪，别撞上轴名）
    ax2.legend(loc="lower right", bbox_to_anchor=(1.22, -0.08), fontsize=10)    # 图例放右下角外面

    # ---------- 图三：散点图 · 延迟 vs 准确率 ----------
    for k, name in enumerate(models):                                           # 逐个模型一个点
        c = palette[k % len(palette)]                                           # 取颜色
        ax3.scatter(m_lat[k], m_acc[k] * 100, s=260, color=c,
                    edgecolors="white", linewidths=1.5, zorder=3)               # 画点（s=点的大小）
        ax3.annotate(name, (m_lat[k], m_acc[k] * 100),                          # 在点旁边标模型名
                     textcoords="offset points", xytext=(12, 8), fontsize=11)   # 往右上偏一点，别压住点
    if m_lat:                                                                   # 有数据才设范围
        ax3.set_xlim(0, max(m_lat) * 1.35)                                      # x 轴留白
    ax3.set_ylim(0, 110)                                                        # y 轴留白
    ax3.set_xlabel("平均延迟（秒）→ 越左越好")                                    # 横轴
    ax3.set_ylabel("准确率 % → 越上越好")                                        # 纵轴
    ax3.set_title("③ 散点图：快 vs 准（左上角是理想区）", fontsize=13)             # 标题
    ax3.grid(alpha=0.3, linestyle="--")                                         # 淡网格，方便读数
    ax3.axvline(sum(m_lat) / len(m_lat) if m_lat else 0, color="#9e9e9e",
                linestyle=":", linewidth=1)                                     # 平均延迟参考线

    # ---------- 存盘 ----------
    fig.suptitle("AI 模型评测结果（柱状图 · 雷达图 · 散点图）", fontsize=16)         # 总标题
    fig.tight_layout()                                                          # 自动排布，别让标签被切掉
    fig.savefig(path, dpi=150, bbox_inches="tight")                             # ★存成 PNG（bbox_inches 防止图例被裁）
    plt.close(fig)                                                              # ★关掉，释放内存（跑很多次不关会爆）
    return path                                                                 # 返回路径


# ---------------------------------------------------------------- 一步到位
def build_all(results=None, result_file="eval_results.jsonl"):                  # 读结果 + 出报告 + 出图
    """读结果文件，一次性生成 Markdown 报告和图表。返回 (结果列表, 报告路径, 图表路径)。"""
    if results is None:                                                         # 没传结果
        from runner import load_results                                         # 延迟 import，避免循环依赖
        results = load_results()                                                # 从文件读
    if not results:                                                             # 还是空的
        print("没有评测结果。先跑：python eval_cli.py run")                        # 告诉他先跑评测
        return [], None, None                                                   # 返回空

    rp = save_report(results)                                                   # 写报告
    cp = plot_chart(results)                                                    # 画图
    print(f"  ✅ 报告已生成：{os.path.abspath(REPORT_FILE)}（{rp} 字符）")            # 提示
    if cp:                                                                      # 图生成了
        print(f"  ✅ 图表已生成：{os.path.abspath(cp)}")                            # 提示
    print(f"  ✅ 五指标：{json.dumps(compute_metrics(results), ensure_ascii=False)}")  # 顺手把指标打出来
    return results, REPORT_FILE, cp                                             # 返回


if __name__ == "__main__":                                                      # 直接运行本文件 = 用假数据看报告长什么样
    import sys                                                                  # sys：改标准输出编码用
    try:                                                                        # ★ 修 Windows 控制台：输出被重定向/管道时，emoji 会触发 UnicodeEncodeError
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")              # 照抄 eval_cli.py 的 _fix_console_encoding()，让 5 个自检命令在任何情况下都能跑完
    except Exception:                                                           # Python 3.6 及以下没有 reconfigure
        pass                                                                    # 老版本就跳过，不影响主流程
    print("=" * 56)                                                             # 分隔线
    print("  报告生成器自检（用假数据，不联网）")                                    # 标题
    print("=" * 56)                                                             # 分隔线
    demo = []                                                                   # ★ 造 2 个模型 × 4 类的假数据，三张图都能看出效果
    for _mi, _model in enumerate(["deepseek", "zhipu"]):                        # 两个模型，雷达图才画得出两条线
        for _ti, (_t, _ok) in enumerate([("正常", True), ("安全", _mi == 0), ("边界", True), ("投诉", _mi == 1)]):
            demo.append({                                                       # 一格数据
                "id": _mi * 10 + _ti, "model": _model, "type": _t,              # 编号 / 模型 / 类别
                "difficulty": "easy", "domain": "闲聊",                          # 难度 / 领域
                "q": f"{_t}类问题样本", "reference": "参考答案",                  # 问题 / 参考
                "a": "这是一段足够长的回答内容，用来通过完整性检查。" * 2,          # 回答（够长）
                "ok": _ok, "reason": "自检假数据", "how": "rule",                # 判分
                "t": 1.5 + _mi * 0.9 + _ti * 0.2, "tokens": 100 + _ti * 20,     # 延迟 / token
                "ts": "2026-10-01 10:00:00",                                    # 时间戳
            })
    print(gen_report(demo))                                                     # 把报告打出来看效果
    print("-" * 56)                                                             # 分隔线
    print("  图表测试：", plot_chart(demo, "_自检_图表预览.png"))                  # 画三联图，确认字体没变方框
