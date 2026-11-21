"""让 scoped runtime 家在**路由组内**失败后也能顺延到下一个候选。

问题形状
--------
`provider_loop.rs` 的会话式分支里，scoped runtime 家（13 家：cursor / devin /
factory / zed / grok / minimax-code / minimax-code-global / qwenwork /
qwenwork-intl / qwenwork-enterprise / kimi-work / opendesign / nous-portal）除
「限额」外的任何错误都直接 `return Err(error)`，不顺延。

单家直连时这条是对的：那一家只有自己的账号，顺延也换不出别的东西，而它的原生
loader 已经拥有单次 token 恢复。

但路由组里候选来自**不同的家**。组里排在第一位的是 qwenwork 时，它一失败整组
就作废 —— 实测 `requests.route.orderedTotal = 27`，`attempts = 1`，27 个候选
只试了第 1 个就返回 502。这就是「路由组不会自动切换」的直接原因。

修法
----
早退条件加上「不在路由组里」。组内顺延只换候选（换家 / 换账号），不碰该家的
凭证与 refresh，与「loader 自己恢复」那条并不冲突 —— 那是同一家内部的补救，
这里是跨家的兜底。
"""

from base import must_absent, must_present, must_replace

TITLE = "路由组内 scoped runtime 家失败后顺延到下一个候选"

PATH = "desktop-tauri/src-tauri/server/src/server/core/upstream/provider_loop.rs"

OLD = """                    let class = adapter.classify_conversation_error(&error);
                    // Scoped runtime 的原生 loader 已拥有单次 token 恢复；宿主不再消费
                    // refresh，也不把 Fatal/权限/WAF/取消/超时改成账号顺延。
                    if strict_runtime && !matches!(&class, UpstreamErrorClass::QuotaLimited { .. }) {
                        return Err(error);
                    }
"""

NEW = """                    let class = adapter.classify_conversation_error(&error);
                    // Scoped runtime 的原生 loader 已拥有单次 token 恢复；宿主不再消费
                    // refresh，也不把 Fatal/权限/WAF/取消/超时改成账号顺延。
                    //
                    // 路由组是例外：组里的候选来自**不同的家**，这个家失败不代表下一个
                    // 家也会失败。此时不顺延等于把整组作废（实测 orderedTotal=27 的组
                    // 只试了第 1 个就返回 502）。组内顺延只换候选、不碰该家的凭证与
                    // refresh，与上面那条「loader 自己恢复」不冲突 —— 那是同一家内部
                    // 的补救，这里是跨家的兜底。
                    if strict_runtime
                        && ctx.routing.group.is_none()
                        && !matches!(&class, UpstreamErrorClass::QuotaLimited { .. })
                    {
                        return Err(error);
                    }
"""


def apply(root: str) -> str:
    path = root + "/" + PATH
    must_present(path, OLD, label="会话式分支的 scoped runtime 早退")
    must_replace(path, OLD, NEW, label="scoped runtime 早退加路由组例外")
    # 反向自检：改完之后这一段必须真的带上组判据，且不能重复出现。
    must_present(path, "&& ctx.routing.group.is_none()", label="组判据")
    must_absent(path, "if strict_runtime && !matches!", label="旧的一行式早退")
    return "会话式分支：scoped runtime 在路由组内改为顺延"
