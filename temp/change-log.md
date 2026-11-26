# 数据与规范变更记录

## 2026-11-26 · P1 / P2 · SCOPE-0001 / CP-0001

- 依据明确启动指令执行P1/P2，规范基线README v1.1保持；P3–P6只建立队列。
- 初始化实体、来源准入、固定关系、字段Schema、实际文件哈希、书目、中文概括与研究视图。
- P1允许的字段定义补充：查询时点确实不可得时，queried_at_utc为null并强制query_time_status=unavailable_exact、recorded_at_utc、queried_date，状态partial。不是重建或伪造精确查询时间，不能据此证明覆盖。条件字段unknown规则保持。
- 主体导出关系补充role固定枚举及work_id外键，以区分authorship、byline_affiliation_at_publication、present_address_at_publication；不把出版日期当雇佣起止。
- 以官方身份元数据核准S01日期、S02权威会议书目、S16编辑/机构、S17作者稿与VOR、S19/S20独立身份及部分文本层问题。保留来源冲突与审计缺口。
- 候选产物验证中发现并修复：来源web_search漏注册、API字段白名单缺项、BibTeX DOI/URL下划线转义、独立报告/学位论文页码空值语义、请求endpoint未进入规范参数导致潜在缓存键碰撞。正式数据验证事件保留修正历史。
- UI测试首次系统浏览器包装器指向缺失二进制，后改用独立测试浏览器；测试脚本接口误用已修正。这些测试工具问题不等于产品功能已通过，最终结果以p2-ui-validation.json为准。
- 原始PDF、带受限正文的API/网页缓存、运行脚本及依赖不提交；temp审计数据纳入Git。所有真实样本在隔离scope运行，未增加正式Work或Upload。

- 最终作者字段复核从已取得的 Crossref 作者元数据补录7个 ORCID，并为其记录 reported 状态及来源；其余空值说明限定于所核查的具体来源，未将提取遗漏解释为原文未披露。
- 隔离真实样本检查点重跑时发现旧自文件哈希问题：内部产物哈希排除 checkpoint，自文件哈希在写入后单独计算；修正前后记录与重验保存在 validation/sample-repair-history/，样本产物持久化在 validation/samples/。
- 两份根目录输出及五个研究视图重复生成，7个文件字节级哈希一致；README §10 指向唯一进度记录。

## 2026-11-26 · CP-0002 · 验收汇总修正

- 修正 p1-acceptance.md 汇总表遗漏的2项最终文件哈希检查：真实样本及完整性检查合计45项通过，原有43项基础样本检查保持通过。
- CP-0001、其Git历史、样本失败及修复事件保持不可变。CP-0002的父检查点为CP-0001，工作集、来源作用域、科学证据与任务队列未扩展。
- 重新生成当前输出，核验数据、浏览器功能、确定性及检查点文件哈希；README、进度与报告统一指向CP-0002。
