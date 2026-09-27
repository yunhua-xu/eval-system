# -*- coding: utf-8 -*-
# ============================================================================
# eval_cli.py —— 命令行工具（项目三的"总开关"）
# ============================================================================
# 一句话：这个文件回答的是"怎么用一条命令把整个评测跑完"。
#
# ★ 为什么要有 CLI（面试讲这句就够了）：
#   "能跑"和"能一键跑"是两回事。面试官看到 `python eval_cli.py run` 一条命令
#   跑完 55 条评测 + 出报告 + 出图，这就是"自动化工程能力"的直接证据。
#
# 用法（在 cmd 里做，打开 cmd：按 Win 键 → 输入 cmd → 回车）：
#   python eval_cli.py run               跑全部评测（默认只跑前 5 条试水）
#   python eval_cli.py run --limit 0     跑全部 55 条（0 = 不限条数）
#   python eval_cli.py run --model zhipu 只跑智谱一个模型
#   python eval_cli.py run --llm        启用 LLM 判分（更准，多花一倍 token）
#   python eval_cli.py report           出报告 + 出图（不重跑评测）
#   python eval_cli.py all              跑评测 + 出报告，一步到位
#   python eval_cli.py stat             只看评测集分布，不跑模型
# ============================================================================

import argparse                                                                 # argparse：Python 自带，不用装
import sys                                                                      # sys：改标准输出编码用


def _fix_console_encoding():                                                    # 修 Windows 控制台中文乱码
    """★ Windows 的 cmd 默认按 GBK 显示，代码里有 ✅ emoji 会报 UnicodeEncodeError。
    这里把输出流改成 utf-8，让中文和 emoji 都能正常打出来。"""
    try:                                                                        # 试着改
        sys.stdout.reconfigure(encoding="utf-8")                                # Python 3.7+ 支持
        sys.stderr.reconfigure(encoding="utf-8")                                # 报错流也改
    except Exception:                                                           # 改不了（老版本 Python）
        pass                                                                    # 就算了，不影响主流程


def cmd_stat(args):                                                             # 子命令：看评测集
    from eval_dataset import stats                                              # 延迟 import
    stats()                                                                     # 打印分布
    return 0                                                                    # 返回码 0 = 正常


def cmd_run(args):                                                              # 子命令：跑评测
    from runner import run_all                                                  # 延迟 import
    from adapter import ALL_MODELS                                              # 模型清单

    models = None                                                               # ★默认自动选"配了 key 的"
    if args.model:                                                              # ★用户指定了模型名
        models = [m for m in ALL_MODELS if m.name == args.model]                # 从清单里按名字找
        if not models:                                                          # 名字写错了
            names = [m.name for m in ALL_MODELS]                                # 列出合法名字
            print(f"★ 没有叫 {args.model!r} 的模型。可选：{names}")               # 明确报错而不是静默跑空
            return 2                                                            # 返回码 2 = 参数错
    limit = args.limit if args.limit and args.limit > 0 else None               # ★0 或不传 = 不限条数
    run_all(models=models, limit=limit, use_llm=args.llm)                       # 开跑
    return 0                                                                    # 正常结束


def cmd_report(args):                                                           # 子命令：出报告
    from report import build_all                                                # 延迟 import
    from runner import load_results                                             # 读结果
    results = load_results(args.model) if args.model else load_results()        # ★按模型过滤
    if not results:                                                             # 一条结果都没有
        print("★ 还没有评测结果。先跑：python eval_cli.py run")                     # 告诉他先干什么
        return 1                                                                # 返回码 1 = 失败
    build_all(results)                                                          # 生成报告 + 图
    return 0                                                                    # 正常结束


def cmd_all(args):                                                              # 子命令：跑评测 + 出报告
    rc = cmd_run(args)                                                          # 先跑
    if rc != 0:                                                                 # 跑失败了
        return rc                                                               # 直接把错误码传出去
    print()                                                                     # 空一行
    return cmd_report(args)                                                     # 再出报告


def build_parser():                                                             # 搭命令行解析器
    p = argparse.ArgumentParser(                                                # 建解析器
        prog="eval_cli",                                                        # 程序名（帮助信息里显示）
        description="AI 模型评测命令行工具：一条命令跑完评测、出报告、出图表。",       # 描述
    )
    p.add_argument(                                                             # 位置参数：动作
        "action",                                                               # 参数名
        choices=["run", "report", "all", "stat"],                                # ★限定取值，写错会自动报错
        help="run=跑评测｜report=出报告｜all=跑评测并出报告｜stat=看评测集分布",      # 帮助文字
    )
    p.add_argument("--model", default=None,                                     # ★可选：指定模型
                   help="只跑/只统计某个模型（名字见 adapter.py：deepseek / zhipu / third）")
    p.add_argument("--limit", type=int, default=5,                              # ★可选：跑几条
                   help="只跑前 N 条，默认 5（先试水，免得一次烧太多钱）；传 0 = 跑全部 55 条")
    p.add_argument("--llm", action="store_true",                                # ★开关：是否用 LLM 判分
                   help="启用 LLM 判分（更准，但每条多一次模型调用）")
    return p                                                                    # 返回解析器


def main(argv=None):                                                            # 主函数
    _fix_console_encoding()                                                     # 先修编码
    args = build_parser().parse_args(argv)                                      # ★解析命令行参数
    handlers = {                                                                # 动作 → 函数的映射表
        "run": cmd_run,                                                         # 跑评测
        "report": cmd_report,                                                   # 出报告
        "all": cmd_all,                                                         # 一条龙
        "stat": cmd_stat,                                                       # 看数据
    }
    return handlers[args.action](args)                                          # ★按动作调用对应函数（比一长串 if 清爽）


if __name__ == "__main__":                                                      # 直接运行时
    sys.exit(main())                                                            # ★把返回码交给系统（0=成功，方便写脚本串起来）
