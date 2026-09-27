# -*- coding: utf-8 -*-
# ============================================================================
# adapter.py —— 统一模型接口（★适配器模式）
# ============================================================================
# 一句话：这个文件回答的是"怎么用同一套代码去调不同的模型"。
#
# 为什么需要它（面试必问）：
#   3 个模型的 SDK、参数名、返回结构都不一样。如果评测代码里写 3 个分支，
#   以后加第 4 个模型就要改评测代码 —— 这叫"改一处、牵全身"。
#   适配器把这些差异全部关在类里面，对外只暴露一个 .complete(messages) 方法。
#   评测代码永远只调 .complete()，加模型 = 加一行，评测代码一个字都不用改。
#
# ★ 原代码有 2 个坑，本文件已修（详见文末"本文件修了什么"）
# ============================================================================

import os                                                                       # os：读环境变量
import time                                                                     # time：算响应耗时（延迟指标要用）
from dotenv import load_dotenv                                                  # load_dotenv：把 .env 文件里的密钥读进环境变量
from openai import OpenAI                                                       # OpenAI：官方客户端；国内模型基本都做了"OpenAI 兼容"接口，所以也能用它调

load_dotenv()                                                                   # ★执行一次，把 .env 里的 key 加载进来（放模块级，只跑一次）


# ---------------------------------------------------------------- 适配器本体
class LLMAdapter:                                                               # ★适配器：屏蔽不同模型之间的差异
    """统一的模型调用口。对外只有 complete() 和 complete_ex() 两个方法。"""

    def __init__(self, name, model, base_url, api_key):                         # 初始化
        """name=模型代号（日志里显示用）；model=模型名；base_url=接口地址；api_key=密钥。"""
        self.name = name                                                        # 记下代号，比如 "deepseek"
        self.model = model                                                      # 记下模型名，比如 "deepseek-chat"
        self.base_url = base_url                                                # 记下接口地址
        self.api_key = api_key                                                  # 记下密钥
        self.available = bool(api_key)                                          # ★有没有 key —— 没 key 的模型直接标成"不可用"，评测时跳过，不报错
        # ★★ 关键：必须"有 key 才建客户端"。
        #    因为新版 openai 库在 api_key 为空时会直接抛异常：
        #        openai.OpenAIError: Missing credentials. Please pass an `api_key` ...
        #    如果无条件新建，那么只要 .env 里少配一个 key，
        #    整个 adapter.py 连 import 都过不去 —— 评测系统当场全崩，一个模型都测不了。
        self.client = OpenAI(api_key=api_key, base_url=base_url) if api_key else None  # 有 key 才建客户端，没有就留 None

    def complete(self, messages):                                               # ★统一接口：传 messages 列表，返回文本字符串
        """和其他框架对齐的简洁写法：只返回回答文本。"""
        return self.complete_ex(messages)["text"]                               # 内部转调 complete_ex，只把文本挑出来

    def complete_ex(self, messages, temperature=0.3):                           # ★带统计的调用：额外返回耗时和 token
        """返回字典：{'text': 回答内容, 't': 耗时秒数, 'tokens': 总 token 数}。
        评测要算「延迟」和「成本」两个指标，所以必须在这里把数据抓下来。"""
        if self.client is None:                                                 # ★这个模型没配 key
            raise RuntimeError(                                                 # 明确报错，不要让它悄悄去调别的模型
                f"模型 {self.name} 没配 API key，不能调用。"
                f"请在 .env 里补上 {self.name.upper()}_API_KEY。"
            )
        t0 = time.time()                                                        # 打表：开始时间
        resp = self.client.chat.completions.create(                             # ★真正发请求
            model=self.model,                                                   # 用哪个模型
            messages=messages,                                                  # 对话消息列表
            temperature=temperature,                                            # 温度：评测要稳定复现，所以调低（0.3），不要天马行空
        )                                                                       # 请求结束
        cost_s = time.time() - t0                                               # 耗时 = 结束 - 开始（秒）
        usage = getattr(resp, "usage", None)                                    # 用量对象（有的兼容接口可能不返回，所以要防御）
        tokens = getattr(usage, "total_tokens", 0) if usage else 0              # ★总 token 数；拿不到就记 0，绝不因为统计失败把评测搞崩
        return {                                                                # 打包返回
            "text": resp.choices[0].message.content,                            # 回答正文
            "t": round(cost_s, 3),                                              # 耗时，保留 3 位小数
            "tokens": tokens,                                                   # token 总数
        }

    def __repr__(self):                                                         # 打印对象时好看（调试用）
        state = "有key" if self.available else "无key(跳过)"                      # 有没有配 key
        return f"<LLMAdapter {self.name} model={self.model} {state}>"           # 例：<LLMAdapter deepseek model=deepseek-chat 有key>


# ---------------------------------------------------------------- 三个模型实例
# ★ 模型名和地址全部走环境变量，默认值只是"常见配置"，不是写死的结论。
#   换模型/换地址 = 改 .env，不用动代码。
#
# ★★ 重要提醒（原代码的坑）：
#   原代码写的是 "deepseek-v4-flash"，这个名字**官方并不存在**。
#   不存在的模型名有的厂商会**静默回退**到某个默认模型 —— 你以为在测 A，其实在测 B，
#   评测结论就全废了。所以这里默认值用官方文档里真实存在的名字，
#   并且 run_all() 结束后会把实际用的模型名打进结果文件，方便回溯。

deepseek = LLMAdapter(                                                          # ★模型 1：DeepSeek
    name="deepseek",                                                            # 代号
    model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),                         # 模型名，默认 deepseek-chat
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),        # 接口地址
    api_key=os.getenv("DEEPSEEK_API_KEY"),                                      # 密钥（从 .env 读，绝不写死在代码里）
)

zhipu = LLMAdapter(                                                             # ★模型 2：智谱 GLM
    name="zhipu",                                                               # 代号
    model=os.getenv("ZHIPU_MODEL", "glm-4-flash"),                              # 模型名，默认 glm-4-flash（免费档，适合练手）
    base_url=os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),  # 接口地址
    api_key=os.getenv("ZHIPU_API_KEY"),                                         # 密钥
)

third = LLMAdapter(                                                             # ★模型 3：可替换（通义/月之暗面/任何 OpenAI 兼容服务）
    name=os.getenv("THIRD_NAME", "third"),                                      # 代号，默认叫 third
    model=os.getenv("THIRD_MODEL", ""),                                         # 模型名 —— 留空，等你按厂商文档填
    base_url=os.getenv("THIRD_BASE_URL", ""),                                   # 接口地址 —— 留空
    api_key=os.getenv("THIRD_API_KEY"),                                         # 密钥
)
# ★ 这里不写死"月之暗面"的具体地址：我没在你的机器上验证过那家的接口，
#   按规矩不能编。你要用哪家，照它官方文档把上面 3 个变量填进 .env 就行。
#   填了就会自动参与评测，没填就会被标成"无key(跳过)"。


ALL_MODELS = [deepseek, zhipu, third]                                           # ★模型清单：加模型只改这一行


def available_models():                                                         # 挑出"配了 key 的"模型
    """返回真正能用的模型列表。这三个里通常只有一两个配了 key。"""
    return [m for m in ALL_MODELS if m.available]                               # 过滤掉没 key 的


if __name__ == "__main__":                                                      # 直接运行本文件 = 自检（★注意：不再联网，不会误花钱）
    print("=" * 60)                                                             # 分隔线
    print("模型适配层自检")                                                       # 标题
    print("=" * 60)                                                             # 分隔线
    for m in ALL_MODELS:                                                        # 逐个看
        print(" ", m)                                                           # 打印适配器状态
    print("-" * 60)                                                             # 分隔线
    ready = available_models()                                                  # 能用的有几个
    if not ready:                                                               # 一个都没配
        print("  一个模型都没配 key。")                                           # 提示
        print("  下一步：把 .env.example 复制成 .env，填进你的 API key。")         # 告诉他怎么办
    else:                                                                       # 有配好的
        print(f"  可用模型 {len(ready)} 个：{[m.name for m in ready]}")            # 列出来
        print("  真实调用请跑：python eval_cli.py run")                            # 指向真正的入口
    print("-" * 60)                                                             # 分隔线
    print("  用法：所有模型共用同一个 .complete(messages)，评测代码不用改。")       # 点题


# ============================================================================
# 本文件修了原代码的什么（对照第9周练习网页版）
# ============================================================================
# 【原坑 1】模块级直接 print(deepseek.complete(...))
#   问题：这行在文件被 import 的时候就会执行 —— runner.py 一 import 你，
#         立刻发一次真实请求。跑 50 条评测会莫名其妙多花一次钱，
#         而且没配 key 时 import 就直接崩（评测还没开始就挂）。
#   修法：import 时不发任何请求；想试直接跑 python adapter.py 走 __main__ 自检。
#
# 【原坑 2】模型名 "deepseek-v4-flash" 官方不存在
#   问题：见上文 ★★ 那条。不存在的模型名可能被静默回退，测的和你以为的不是一个。
#   修法：默认值改成真实存在的名字 + 全部走环境变量 + 结果文件里记录实际模型名。
# ============================================================================
