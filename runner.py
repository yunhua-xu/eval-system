# -*- coding: utf-8 -*-
# ============================================================================
# runner.py —— 评测运行器（项目三的"考试流程"）
# ============================================================================
# 一句话：这个文件回答的是"怎么把 55 道题一道道跑完，还不怕中途断电"。
#
# 两个核心机制（面试重点）：
#   ① 断点续跑 —— 每跑完一条**立刻写文件**。跑到第 30 条时断网/断电，
#      重跑时前 29 条直接跳过，不重复花钱、不浪费时间。
#   ② 边跑边落盘 —— 结果是 JSONL 格式（一行一条 JSON），
#      坏了一行不影响其他行，比整份 JSON 文件安全得多。
#
# ★ 原代码有一个会让程序直接崩的 bug，本文件已修（详见文末）
# ============================================================================

import json                                                                     # json：把结果存成 JSONL
import os                                                                       # os：判断文件在不在
import time                                                                     # time：打时间戳

from eval_dataset import load_dataset                                           # 评测集
from metrics import judge                                                       # ★判分总入口（判分逻辑统一放 metrics.py，别在这里重写）
from adapter import available_models, ALL_MODELS                                # 模型清单

RESULT_FILE = "eval_results.jsonl"                                              # ★结果文件名（一行一条）
                                                                                #   叫 jsonl 不叫 json，是因为它"一行一个完整 JSON"

# ---------------------------------------------------------------- 结果字段说明
# 每条结果存这些字段。★ 关键：存全！少存一个字段，下游的 metrics.py / report.py 就会 KeyError 崩掉。
RESULT_FIELDS = [
    "id",           # 题目编号（0 起）
    "model",        # ★哪個模型答的（三个模型对比时，全靠这个字段区分）
    "type",         # 类别：正常/投诉/边界/安全/多轮/对抗
    "difficulty",   # 难度：easy/medium/hard
    "domain",       # 领域
    "q",            # 问题原文
    "reference",    # 参考答案（report 要拿它做对比）
    "a",            # 模型回答
    "ok",           # ★判分结果：True/False（metrics 算准确率就靠它）
    "reason",       # 判定理由（为什么过/为什么不过）
    "how",          # 判分方式：rule / llm / rule+llm
    "t",            # ★耗时秒数（metrics 算延迟靠它）
    "tokens",       # ★token 数（metrics 算成本靠它）
    "ts",           # 时间戳
]


# ---------------------------------------------------------------- 读已完成的
def load_done():                                                                # 读"哪些题已经跑过了"
    """返回已完成的集合，元素是 (题目id, 模型名) 二元组。

    ★ 为什么 key 里要带模型名？
      原代码只用题目 id 做 key（`if i in done`）。那样只测一个模型没问题，
      但项目要求"3 个模型全量跑通" —— 用 id 做 key 的话，
      DeepSeek 跑完第 0 题后，智谱的第 0 题会被当成"跑过了"直接跳过，结果全丢。
      这是本项目里最隐蔽的一个 bug。
    """
    done = set()                                                                # 空集合
    if not os.path.exists(RESULT_FILE):                                         # 结果文件还不存在 = 第一次跑
        return done                                                             # 返回空集合
    with open(RESULT_FILE, encoding="utf-8") as f:                              # ★用 with 打开，自动关文件
        for line_no, line in enumerate(f, 1):                                   # 逐行读
            line = line.strip()                                                 # 去掉首尾空白
            if not line:                                                        # 空行
                continue                                                        # 跳过
            try:                                                                # 试着解析
                obj = json.loads(line)                                          # 一行 = 一个完整 JSON
            except json.JSONDecodeError:                                        # ★这一行坏了（比如上次写到一半断电）
                print(f"  [警告] {RESULT_FILE} 第 {line_no} 行不是合法 JSON，已跳过")   # 提示但不崩
                continue                                                        # 继续读下一行
            done.add((obj.get("id"), obj.get("model")))                          # ★记下 (题目id, 模型名) 组合
    return done                                                                 # 返回


# ---------------------------------------------------------------- 写一条结果
def save_result(row):                                                           # ★每条结果立即写文件
    """把一条结果追加到 JSONL。★ 用 'a'（追加）模式，不是 'w'（覆盖）——
    用 'w' 的话每写一条就把前面的全冲掉，跑完只剩最后一条。"""
    with open(RESULT_FILE, "a", encoding="utf-8") as f:                         # 追加模式打开
        f.write(json.dumps(row, ensure_ascii=False) + "\n")                     # ★ensure_ascii=False：让中文原样存，不转成 \uXXXX


# ---------------------------------------------------------------- 读全部结果
def load_results(model=None):                                                   # 读全量结果（给 report/metrics 用）
    """把所有结果读成列表。model 传了就只读那一个模型的。"""
    rows = []                                                                   # 结果列表
    if not os.path.exists(RESULT_FILE):                                         # 文件不存在
        return rows                                                             # 返回空
    with open(RESULT_FILE, encoding="utf-8") as f:                              # 打开
        for line in f:                                                          # 逐行
            line = line.strip()                                                 # 去空白
            if not line:                                                        # 空行跳过
                continue                                                        # 继续
            try:                                                                # 试着解析
                obj = json.loads(line)                                          # 解析
            except json.JSONDecodeError:                                        # 坏行
                continue                                                        # 跳过
            if model and obj.get("model") != model:                             # 只要指定模型的
                continue                                                        # 不是就跳过
            rows.append(obj)                                                    # 收下
    return rows                                                                 # 返回


# ---------------------------------------------------------------- 主流程
def run_all(models=None, limit=None, use_llm=False, resume=True):               # ★跑全部评测
    """把评测集在指定模型上跑一遍。

    参数：
      models   要测哪些模型，不传就自动用"配了 key 的"
      limit    只跑前 N 条（调试用，正式跑传 None）
      use_llm  是否启用 LLM 判分（更准，但要多花一倍 token）
      resume   是否断点续跑（默认开）
    """
    dataset = load_dataset()                                                    # 加载 55 道题
    if limit:                                                                   # 调试模式
        dataset = dataset[:limit]                                               # 只取前 N 条
    if models is None:                                                          # 没指定模型
        models = available_models()                                             # 自动挑配了 key 的
    if not models:                                                              # 一个都没有
        print("★ 没有可用模型：请先把 .env.example 复制成 .env 并填入 API key。")      # 明确告诉他怎么办
        return []                                                               # 直接返回，不报错

    done = load_done() if resume else set()                                     # ★已完成的集合
    todo = [(i, item) for i, item in enumerate(dataset)]                        # 给每道题编号
    total_plan = len(todo) * len(models)                                        # 计划总调用次数
    print("=" * 56)                                                             # 分隔线
    print(f"  评测开始｜题目 {len(todo)} 条 × 模型 {len(models)} 个 = 计划 {total_plan} 次调用")  # 报计划
    print(f"  模型：{[m.name for m in models]}")                                  # 列出模型
    print(f"  结果文件：{os.path.abspath(RESULT_FILE)}")                          # 告诉他结果存哪
    print("=" * 56)                                                             # 分隔线

    n_ok = n_fail = n_skip = 0                                                  # 三个计数器
    t_start = time.time()                                                       # 整体计时开始

    for m in models:                                                            # 逐个模型
        print(f"\n---- 模型 {m.name} ({m.model}) ----")                           # 分组标题
        for i, item in todo:                                                    # 逐道题
            if (i, m.name) in done:                                             # ★这个"题+模型"组合跑过了
                n_skip += 1                                                     # 计数
                print(f"  [{i+1:>2}/{len(todo)}] 跳过（已完成）")                  # 提示（断点续跑生效）
                continue                                                        # 跳到下一题

            q = item["question"]                                                # 取问题
            history = item.get("history") or []                                 # ★多轮题的"上文"；没有 history 字段的题就是空列表
                                                                                #   为什么要这行：多轮题问的是"再详细讲讲第二点"，
                                                                                #   不给上文就无从回答。原来只发本条问话，这一类题全测不准。
            messages = list(history) + [{"role": "user", "content": q}]         # ★上文 + 本轮问话 拼成完整对话再发
            t0 = time.time()                                                    # 单条计时
            try:                                                                # ★调模型一定要包 try：网络抖一下不能让整轮评测崩掉
                r = m.complete_ex(messages)                                     # 调模型（带耗时/token）
            except Exception as e:                                              # 出错
                r = {"text": f"[调用失败] {type(e).__name__}: {e}", "t": round(time.time() - t0, 3), "tokens": 0}  # 把错误当回答记下来
            answer = r["text"]                                                  # 取出回答

            ok, reason, how = judge(item, answer, use_llm=use_llm, judge_model=m)  # ★判分（用被测模型之外的？这里就用它自己，便于对比）
            row = {                                                             # ★组装完整一行结果
                "id": i,                                                        # 题目编号
                "model": m.name,                                                # ★哪个模型
                "type": item["type"],                                           # 类别
                "difficulty": item["difficulty"],                               # 难度
                "domain": item["domain"],                                       # 领域
                "q": q,                                                         # 问题
                "reference": item["reference_answer"],                          # 参考答案
                "a": answer,                                                    # 回答
                "ok": ok,                                                       # ★判分结果
                "reason": reason,                                               # 理由
                "how": how,                                                     # 判分方式
                "t": r["t"],                                                    # ★耗时
                "tokens": r["tokens"],                                          # ★token
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),                       # 时间戳
            }
            save_result(row)                                                    # ★★立即落盘（防中途挂掉全丢）

            if ok:                                                              # 判过了
                n_ok += 1                                                       # 计数
                flag = "✅"                                                      # 对勾
            else:                                                               # 没过
                n_fail += 1                                                     # 计数
                flag = "❌"                                                      # 叉
            print(f"  [{i+1:>2}/{len(todo)}] {flag} {item['type']:<2} {r['t']:>5.2f}s | {q[:26] or '(空输入)'}")  # 实时进度

    used = time.time() - t_start                                                # 总耗时
    print("\n" + "=" * 56)                                                      # 分隔线
    print(f"  全部跑完：通过 {n_ok}｜未通过 {n_fail}｜跳过 {n_skip}｜用时 {used:.1f} 秒")   # 汇总
    print(f"  结果已存入：{os.path.abspath(RESULT_FILE)}")                         # 结果位置
    print("  下一步（看报告）：python eval_cli.py report")                          # 指向下一步
    print("=" * 56)                                                             # 分隔线
    return load_results()                                                       # 返回全量结果，方便调用方接着用


if __name__ == "__main__":                                                      # 直接运行本文件 = 正式开跑
    import sys                                                                  # sys：改标准输出编码用
    try:                                                                        # ★ 修 Windows 控制台：输出被重定向/管道时，emoji 会触发 UnicodeEncodeError
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")              # 照抄 eval_cli.py 的 _fix_console_encoding()，让 5 个自检命令在任何情况下都能跑完
    except Exception:                                                           # Python 3.6 及以下没有 reconfigure
        pass                                                                    # 老版本就跳过，不影响主流程
    run_all()                                                                   # 跑全部


# ============================================================================
# 本文件修了原代码的什么（对照第9周练习网页版）
# ============================================================================
# 【原坑 1】★最严重：只存 {id, q, a}，下游却读 ok / t / tokens / type / reference
#   原代码 save_result 写的是： {"id": i, "q": q, "a": ans}
#   但 metrics.py 要读 r["ok"]、r["t"]、r["tokens"]，
#      report.py  要读 r["type"]、r["ok"]。
#   后果：跑完 50 条评测，一执行 report 立刻 KeyError: 'ok' 崩掉。
#        辛苦跑的钱和时间全在文件里，但一行结果都看不到。
#   修法：save_result 存满 RESULT_FIELDS 全部 14 个字段（见文件上方清单）。
#
# 【原坑 2】断点续跑只用题目 id 做 key
#   原代码： done.add(json.loads(line)["id"])  然后 if i in done: continue
#   后果：测第 2 个模型时，第 0 题被当成"已完成"直接跳过 —— 三个模型对比少两个模型的数据。
#   修法：key 改成 (题目id, 模型名) 二元组。
#
# 【原坑 3】判分逻辑空缺
#   原代码 runner 里没有判分这一步：模型答完直接存，"对不对"完全没判。
#   那 metrics 里的准确率 r["ok"] 从哪来？答案：没有来源。整个评测链条是断的。
#   修法：接上 metrics.judge()，规则判分打底，可选叠加 LLM 判分。
# ============================================================================
