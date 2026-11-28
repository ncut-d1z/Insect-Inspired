# Insect-Inspired：昆虫启发的视觉自运动估计文献追踪与局限性研究

> 版本：1.1.1；生效日期：2026-11-26。  
> 本文件是最终执行规范，规定文献数据库、递归引文检索、作者/机构/项目追踪、局限性证据分析与验收要求；不包含检索结果、数据文件或运行日志。数据文件与日志按 §8 生成，审计数据与日志保存于 `temp/`。

## 1. 研究背景与任务目标

### 1.1 研究目标

研究问题来源见 §2.1，种子来源见 §2.2。采用系统性引文追踪（citation chasing / snowballing）、研究主体追踪和全文证据分析，建立持续扩展、可追溯、可去重、可增量维护的研究证据库。必须回答：

1. 针对 PPT 各项局限，相关数学方法、神经机制、实验方法及工程实现分别处理了什么问题，在何种条件下成立，仍存在何种困难？
2. 原论文及其他 Work 的作者、大学、研究所、实验室、课题组及相关研究人员有哪些相关成果和研究项目？项目与成果的关联证据是什么？
3. 哪些 Work 实际引用前作，引用作用是继承、改进、验证、质疑、应用还是背景介绍？哪些 Work 独立推进同类问题？
4. 各项研究依赖哪些前期工作？依据已核验的关系重建研究脉络，保留负结果、相互矛盾的证据及未解决问题。
5. 哪些结论对昆虫视觉、自运动估计和纯视觉里程计具有启示？

五个研究问题与机器可读交付物建立强制主映射。每个有效 Checkpoint 必须从规范数据确定性生成以下全部视图；零记录使用合法空集合或仅表头，不填造记录。P7 必须交付这些文件及覆盖说明，字段与对账规则见 §8.4。

| 研究问题 | 固定交付路径 | 对账对象及必须表达的结果 |
| --- | --- | --- |
| Q1 局限性证据及剩余问题 | `temp/exports/evidence_matrix.csv` | 每个有效 Assessment 一行，记录 L、证据路线、量化门禁、条件、结果、反证及定位 |
| Q2 作者、团队、机构与项目成果 | `temp/exports/research_entities.json` | Person、Organization、Project、Work 及带时间、来源、核验状态的关系 |
| Q3 引用关系、引用作用及独立研究 | `temp/exports/citation_graph.json` | 有效 Work 节点、实际引用边及语境；独立进展以 Assessment 关联单列，不虚构引用 |
| Q4 前期研究、继承路线及冲突证据 | `temp/exports/research_paths.json` | 各 L、各 Assessment 的可追溯发现路径与核验关系、反证及路径缺口 |
| Q5 生物、计算模型及工程启示 | `temp/exports/research_implications.csv` | 按 L、路线和 Assessment 表达启示、条件、剩余问题及外推边界 |

根目录提供 `ref.bib`、[主题文献](ref.html)和[其他、背景与待分类文献](misc.html)。离线使用时将两个 HTML 与相邻的 `ref-data/` 目录一起复制。最终报告按 §9.4 汇总研究视图。

每条 Assessment 必须绑定 §7.2 定义的 evidence_route：生物机制、数学/计算模型或工程实现。工程可行性不直接证明动物实现同一计算；神经元响应选择性不直接证明六自由度运动可恢复；仿真结果不直接证明真实系统性能。

本项目仅声明冻结快照和已披露来源内经验证的覆盖范围，不声明穷尽全部数据库、语言、年代和灰色文献。研究结论采用 §9.4 固定模板。

### 1.2 术语表

| 术语 | 定义与标识 |
| --- | --- |
| Seed record（种子记录） | §2.2 中固定编号的规范输入记录，以 seed_id 标识；唯一编号来源为该表 |
| Upload（上传出现项） | 一次文件输入的审计实体，以 upload_id 标识；不等于 Seed record、Work 或 Version |
| Work（规范文献） | 可独立识别、引用的书目实体，以不可复用的 work_id 和稳定 BibTeX key 标识；可具有多个 Version；身份未定者依 §4.3 处理 |
| Version（版本/文件） | Work 的具体出版版本、作者稿、预印本、存档或文件表现形式，以 version_id 标识；文件 SHA-256 标识字节内容，文件与版本不是同一计数口径 |
| Assessment（主题证据） | Work 对特定局限性、证据路线及条件的独立评价，以 assessment_id 标识；记录结论和可核验依据 |
| Checkpoint（检查点） | 同一 scope_id 内经一致性校验提交的可恢复状态，以 checkpoint_id 标识，含队列、游标、统计、产物版本与缺口 |

### 1.3 实体基数与去重级联

有效实体拓扑固定为 Work (1) → Version (1..N) → Upload (0..N)。每个有效 Work 至少一个 Version，每个 Version 必须且只能归属一个 Work。只有书目、尚无全文时建立 bibliographic_only Version，file_records 为空，不虚构 PDF。Version 可无 Upload（例如通过合法外部来源发现），每个已准入且身份核验的 Upload 必须且只能指向一个 Version，其 work_id 必须等于该 Version 的 work_id。Seed record 映射一个 Work；无文件时 Upload 指针为空并登记任务。身份未决的输入为隔离记录，不构成有效所有权关系。被拒文件不进入拓扑；去重 Upload 仅保留审计身份，不增加 Work 或 Version 数。

Assessment 唯一归属 Work 而非 Upload；evidence_locator、provenance_upload_ids、provenance_version_ids 必须支持证据追踪。无 Upload 的合法外部证据通过 Version 或官方来源定位。

Upload 确认重复并生成 duplicate_of_upload_id 时，必须自动执行同一事务内的级联：

1. 核验重复目标、文件/版本身份及无环指针，规范到保留 Upload；禁止将独立出版身份或不同实质内容误判为重复。
2. 枚举受影响的 Assessment、Version/Work、证据定位、原始引文、引文边、任务及别名；映射至保留实体，保存原 Upload/位置历史。
3. 以 work_id、limitation_id、evidence_route、claim_id 所表达的主张、规范化条件、结论及证据定位判定等价性。等价 Assessment 自动合并证据来源，保留 canonical assessment_id，重复记录标为 merged 并记录 superseded_by_assessment_id；条件、结果、反证或路线不等价者分别保留。
4. 经级联仍无可定位有效依据的 Assessment 标为 discarded（废弃），记录原因、原 ID、cascade_event_id 与复查任务；存在定位或身份冲突者标为 pending_review，生成工单。仍有独立有效依据者不得废弃。不得物理删除审计历史。
5. 重算准入、引用关系、T_i/U、导出与统计，核验无悬空外键、重复有效 Assessment 或丢失反证；不通过则回滚，不发布有效 Checkpoint。

未完成级联不得标记去重完成。Work/Version 合并同样执行上述事务；级联仅处理受影响记录。

规范性关键词：必须/不得表示强制约束；允许表示在适用条件内的合法选择。缺失或不确定事实以结构化字段、枚举及证据记录表示，不以推测替代事实。

## 2. 输入材料与种子范围

### 2.1 问题来源

- 《广视域.pptx》第 22 页为局限性分类来源，第 23 页研究方向为辅助检索线索，不增加局限性分类。
- Franz & Krapp（2000）为基准论文，1998 年 Technical Report No. 61 为相关技术报告；对应 Seed record 及关系见 §2.2。两篇分别保留独立书目、Version 和模型证据，不得互相替代，不得以概述代替全文证据。

### 2.2 种子记录（规范输入；不含已去重 Upload）

种子集合固定为下表 S01–S20 共 20 条 Seed record。S19 为 Franz & Krapp（2000）基准论文，S20 为 1998 年 Technical Report No. 61。下表是种子编号、题名及种子身份的唯一事实源。已去重 Upload 不占用 S 编号、不建立额外 Work 或重复 Version；其审计记录仅保存于 `temp/seed-manifest.jsonl`。Seed record、Upload、不同文件哈希、规范 Work、Version 分别按 §4.3 统计。

规范 Work 初判固定为 independent（独立书目身份）或 related_independent（具有相关文献关系的独立书目身份）。初判不是已经生成的 Work ID 或全文核验结果；身份核验由 identity_confidence 和 verification_status 表示。

| S 编号 | 题名 | 文献类型 | 规范 Work 初判 | target_related_id | seed_relation_type | 版本/关系备注 |
| --- | --- | --- | --- | --- | --- | --- |
| S01 | Insect-Inspired Visual Self-Motion Estimation | 学位论文 | related_independent | S15 | contains_publication | 与 S15 存在章节内容关系，独立学位论文 |
| S02 | Linear Combinations of Optic Flow Vectors for Estimating Self-Motion – a Real-World Test of a Neural Model | 会议论文 | related_independent | S17 | preliminary_of | 与 S17 存在前期研究关系，独立书目 |
| S03 | Olfactory Neuromodulation of Motion Vision Circuitry in Drosophila | 期刊论文 | independent | null | null | — |
| S04 | Blowfly flight characteristics are shaped by environmental features and controlled by optic flow information | 期刊论文 | independent | null | null | — |
| S05 | Population Coding of Self-Motion: Applying Bayesian Analysis to a Population of Visual Interneurons in the Fly | 期刊论文 | independent | null | null | — |
| S06 | A competitive disinhibitory network for robust optic flow processing in Drosophila | 期刊论文 | independent | null | null | — |
| S07 | Sharing Receptive Fields with Your Neighbors: Tuning the Vertical System Cells to Wide Field Motion | 期刊论文 | independent | null | null | — |
| S08 | Dynamic Signal Compression for Robust Motion Vision in Flies | 期刊论文 | independent | null | null | — |
| S09 | Disentangling of Local and Wide-Field Motion Adaptation | 期刊论文 | independent | null | null | — |
| S10 | Neural mechanism underlying complex receptive field properties of motion-sensitive interneurons | 期刊论文 | independent | null | null | — |
| S11 | On the computations analyzing natural optic flow: Quantitative model analysis of the blowfly motion vision pathway | 期刊论文 | independent | null | null | 机构库文件含封面及出版版本 |
| S12 | Near-Optimal Decoding of Transient Stimuli from Coupled Neuronal Subpopulations | 期刊论文 | independent | null | null | — |
| S13 | Robust Models for Optic Flow Coding in Natural Scenes Inspired by Insect Biology | 期刊论文 | independent | null | null | — |
| S14 | Depth information in natural environments derived from optic flow by insect motion detection system: a model analysis | 期刊论文 | independent | null | null | — |
| S15 | Insect-Inspired Self-Motion Estimation with Dense Flow Fields—An Adaptive Matched Filter Approach | 期刊论文 | related_independent | S01 | included_in_thesis | 与 S01 存在章节内容关系，独立期刊论文 |
| S16 | Insect-Inspired Odometry by Optic Flow Recorded with Optical Mouse Chips | 书籍章节 | independent | null | null | — |
| S17 | Insect-Inspired Estimation of Egomotion | 期刊论文 | related_independent | S02 | expanded_from | 与 S02 存在扩展研究关系，独立书目；所供文件的版本类型单独核验 |
| S18 | Function of a Fly Motion-Sensitive Neuron Matches Eye Movements during Free Flight | 期刊论文 | independent | null | null | — |
| S19 | Wide-field, motion-sensitive neurons and matched filters for optic flow fields | 期刊论文 | related_independent | S20 | related_report | Franz & Krapp，2000；正式基准论文 |
| S20 | Wide-Field, Motion-Sensitive Neurons and Optimal Matched Filters for Optic Flow | 技术报告 | related_independent | S19 | related_report | Franz & Krapp，1998 年 6 月；Max-Planck-Institut für biologische Kybernetik，Technical Report No. 61；与 S19 分立 |

target_related_id 为可空 Seed record 外键，seed_relation_type 为可空枚举；independent 的两字段均为 null，related_independent 必须具有非空目标及类型。互逆类型固定为 contains_publication ↔ included_in_thesis、preliminary_of ↔ expanded_from、related_report ↔ related_report；目标必须存在、不得自引用，互逆关系只计一个语义关系。

上述指针是初始化硬约束：P1 直接从本表生成带外键的初始化记录，P2 经 seed_id → work_id 映射生成 related_work；不得依赖后续文本算法推断、覆盖或自动改号。关系的来源核验与预置拓扑分开记录；缺文件仍保留预置关系及其核验状态。禁止将这些关系用作合并独立 Work、确认实际引用或科学结论的证据。证据冲突记为 conflicting 并生成复核任务；修改规范拓扑必须经用户批准。

每条 Seed record 必须在 seed-manifest 中有映射。被去重 Upload 使用独立 upload_id，seed_id 为 null，记录原文件名、SHA-256、来源、对应 work_id、version_id、duplicate_of_upload_id 和 verification_status；不得为其另建 Seed record 或 Work。真实关系尚未核验时，相关字段为 null 并标记状态；文件缺失记录于 tasks.jsonl，不得假设可用。完整字段、文件归属和计数规则见 §4.2–§4.3、§8.3。种子表不得由运行数据自动改号或扩充；输入范围变更必须修订规范并经用户批准。

### 2.3 输入准入及边界外文件拦截

任何文件进入正文/参考文献深度解析、Work/Version 创建或 Assessment 提取之前，必须满足以下一种准入条件：seed（按 §2.2 核验 Seed record 和文件身份）；verified_discovery（具备冻结作用域内、连接至已准入 Seed record/Work 的合法且可核验的发现路径）。

discovery_route 枚举：seed、backward_citation、forward_citation、author_publication、institution_publication、project_output。discovery_path 为有序关系边数组，每跳包含 from_entity_id、to_entity_id、discovery_route、source_id、evidence_locator、verification_status、scope_id；路径连续、端点可解析、来源及范围符合 §5–§6。实际引用边和作者/机构/项目关联分开；独立研究不要求直接引用基准论文。文件名、关键词、姓名相似及孤立 URL 不构成合法路径。evidence_route 专用于 §7.2 的科学证据路线，不能代替发现路径。

未列于 §2.2 且无合格 discovery_path 的游离文件立即阻断解析链，不提取正文/参考文献、不创建有效 Upload/Work/Version 或 Assessment、不产生扩展任务；仅允许准入必需的安全文件指纹及最小身份核验。拒绝事件直接追加至 `temp/rejected_uploads.log`（UTF-8 JSONL），字段：rejection_id、upload_id、filename、sha256（无法安全取得则 null）、received_at_utc、scope_id、claimed_seed_id、attempted_discovery_path、reason_code、verification_status、review_condition、related_task_id、decided_at_utc。reason_code 固定为 seed_not_listed、seed_identity_mismatch、missing_discovery_path、unverified_discovery_path、out_of_scope、access_not_authorized、unsafe_or_unreadable_file。提供合格路径、纠正身份或取得授权后以新事件复查；不得覆盖拒绝历史。拒绝日志不是书目或引文证据。

已经通过合法元数据/发现路径识别的 Work，即使某个文件被拒，仍按 DEC-08 入库；文件准入失败不得删除既有合法书目。缺失或待核验的授权种子按 §2.2 记录任务，不假设文件存在。

## 3. 局限性分类与研究问题

PPT 第 22 页的七个一级项目固定细分为 L01–L09。第二个一级项目对应 L02–L04；L06 与 L08 存在交叉但不合并。U00 为非主题文献表，不是局限性。PPT 表述与基准论文的原文存在差异时，保留两者并说明差异，不改写原作者主张。

| ID | PPT 中的局限性（概括） | 需回答的问题 | 纳入判断重点 | 可接受证据类型 | 不可接受推断 |
| --- | --- | --- | --- | --- | --- |
| L01 | 广域求和平均距离依赖，弱化运动视差，不能完整恢复三维运动与结构 | 局部/区域/多尺度整合、主动视觉、时序分离及距离模型能否保留空间信息？ | 邻近度、相对/绝对深度、结构表征与完整重建；平移是否已知 | 深度真值对比、空间分辨率分析、神经响应及行为实验、可辨识性推导 | 将平均邻近度或避障行为等同完整三维重建 |
| L02 | 简化 EMD 模型忽略对比度、空间频率与纹理依赖 | 归一化、增益控制、多尺度滤波、统计模型、ON/OFF 通路能否减少图像因素干扰？ | 对比度、纹理、空间频率分别评价；局部速度与广域响应分别评价 | 控制变量刺激实验、自然图像速度真值对照、理论/模型消融 | 将图案平均响应稳定等同所有局部速度无偏或纹理依赖完全消除 |
| L03 | 简化模型不能充分反映瞬态响应和适应 | 时变、非线性或适应模型如何解释局部与广域适应？ | 时间常数、延迟、刺激历史、瞬态、模型辨识和泛化 | 时序电生理/成像、适应范式、动态模型与数据比较 | 以稳态拟合证明瞬态性能，或由 HSE 直接推广到全部 VS |
| L04 | 简化模型只考虑低速周期性条纹（PPT 表述） | 自然图像、非周期纹理、高速、加速度、自由飞行及动态环境下性能如何？ | 区分基准论文的线性区与平台区；记录刺激、速度、曝光/采样条件 | 自然光流重放、实测飞行轨迹、真实图像或受控高速实验 | 由自然图像验证推出任意高速运动无歧义编码；将基准模型仅描述为低速 |
| L05 | 部分 VS 感受野无法解释，尤其 VS1–VS3、VS7–VS10 | 电耦合、化学突触、其他神经元输入及网络模型能否解释具体感受野特征？ | 物种、编号、LPD/LMS、背腹不对称、额侧响应、未解释特征 | 双细胞记录、消融/干预、连接组、受数据约束的模型与感受野比较 | 将连接存在等同全部感受野已解释；跨物种直接对应同编号细胞 |
| L06 | 单滤波器受其他运动类型激发；距离结构与混合光流限制完整自运动恢复 | 联合滤波、旋转平移解耦、群体解码或神经回路能恢复哪些运动量？ | 旋转轴、旋转方向、旋转速率、平移方向、相对平移、绝对尺度分别评价；串扰、误差及退化 | 可观测性/秩分析、混合运动估计实验、群体解码及因果神经回路验证 | 从单轴响应或纯旋转实验推断一般六自由度恢复；无尺度依据声称绝对平移 |
| L07 | 平台模型不能编码旋转速率；PPT 将方向鲁棒性与角位移大小联系起来 | 其他调谐通道、动态响应、附加信号或改进 EMD 能否补充幅值信息？ | 预设轴响应符号、真实轴与方向、速率与帧间角位移分别评价 | 速度调谐/饱和实验、可辨识性证明、多通道解码及真值幅值比较 | 完全饱和的单输出在无附加信息时恢复丢失的幅值；由方向选择性推出速率或角位移准确性 |
| L08 | 世界模型简单；距离统计与飞行统计缺少充分实测依据，旋转平移可能耦合 | 自然环境深度与飞行运动联合统计如何建模？自适应距离先验能否跨环境工作？ | 测量数据与统计先验、当前环境自适应分开；采样偏差、运动耦合、尺度 | 深度/轨迹实测及统计、模型推导、跨环境对比与消融 | 将固定距离先验当真实当前环境；由仿真直接证明自然飞行统计或绝对尺度可恢复 |
| L09 | Hx 数据不足，缺少与 VS 同等假设检验 | 是否有 Hx 解剖、生理、感受野、平移选择性数据及对匹配滤波假设的直接检验？ | 丽蝇与果蝇分开；功能相似、跨模态调节、同等假设检验分开 | Hx 记录、解剖/连接组、明确统计检验和模型比较 | 以不同物种同名细胞或嗅觉调节证明原 Hx 匹配滤波假设已通过检验 |

### 3.1 最小可判定条件与强类型 Schema

所有 Assessment 的核心字段必须通过 schema.json 强类型验证；required、type、enum、数组唯一性、数值区间、条件依赖、外键检查均为强制约束。核心分类只能使用本节及 §7.2 的枚举，不接受自由文本或隐式类型转换；自由文本仅用于说明、原文证据及备注。

统一类型 `Condition<T>` 为封闭对象：

    status: enum(reported, not_reported, unknown, unknown_review_required, not_applicable)
    value: T | null
    evidence_locator: array<Locator>
    reason: string | null
    unknown_since_utc: UTC timestamp | null
    review_task_id: string | null

reported 要求非空且符合 T 的 value 及支持定位；其余状态 value 必须为 null、reason 必填。not_reported 必须定位已核查的完整相关原文及说明确未披露；not_applicable 必须有不适用依据；unknown 和 unknown_review_required 必须有原始时间及复核工单。未取得全文、解析失败、OCR 错误或尚未检查不能标为 not_reported。

| 条件字段 | 强类型（统一外层 `Condition<T>`） | 值域与约束 |
| --- | --- | --- |
| species | `array<object>` | reported 时至少一项；scientific_name:string、taxon_id:string/null、cell_type:string/null、cell_identifiers:`array<string>`；非生物研究标不适用 |
| motion_type | Enum | pure_rotation、pure_translation、mixed_rotation_translation、stationary、other_specified |
| motion_dof | object | rotation_dof、translation_dof 为 0..3 的整数；estimated_components 为去重枚举数组：rotation_axis、rotation_direction、rotation_rate、rotation_angle、rotation_3d、translation_direction、translation_relative、translation_metric、depth_relative、depth_metric |
| known_translation | Enum | externally_known、partially_known、not_known；附条件来源 |
| speed_range | `array<QuantityRange>` | 角速度、线速度、帧间角位移、线位移、采样间隔分别记录；reported 至少一项 |
| environment | Enum | laboratory_controlled、natural_environment、indoor_structured、outdoor_structured、synthetic_simulation、reconstructed_simulation、mixed_environments、other_specified |
| environment_details | object | dataset_ids:`array<string>`、scene_count:integer≥1/null、fov_deg:QuantityRange/null、distance_range:QuantityRange/null、distance_distribution:Enum（fixed、measured、statistical_prior、estimated）、scene_dynamics:Enum（static、dynamic、mixed）、distance_knowledge:Enum（known_metric、known_relative、partially_known、not_known）；未披露/未知/不适用的子字段按状态记录 |
| texture_noise | object | stimulus_type:Enum（periodic_grating、random_pattern、natural_image、synthetic_pattern、natural_video、other_specified）、contrast、spatial_frequency、illumination、noise 为 QuantityRange/null；outlier_fraction、occlusion_fraction 为 number/null 且 0..1 |
| scale | Enum | absolute_metric、relative_scale、direction_only、scale_unobservable；空值状态不属于实际值域 |
| scale_source_prior | `array<Enum>` | inertial_metric、known_baseline、known_scene_geometry、known_camera_height、known_metric_motion、metric_range_sensor、metric_training_prior、other_metric_prior、none；reported 非空无重复，none 互斥 |
| scale_observability | Enum | proven_under_assumptions、empirically_validated_under_assumptions、unobservable、not_demonstrated |
| method_and_validation | object | assumptions:`array<string>`、validation_types:`array<evidence_kind Enum>`、dataset_ids:`array<string>`、sample_count/trial_count:integer≥1/null、baseline_ids/metric_ids/failure_conditions:`array<string>` |

QuantityRange 固定为 quantity:Enum（angular_velocity、linear_velocity、angular_displacement、linear_displacement、sample_interval、fov、distance、contrast、spatial_frequency、illumination、noise、other_specified）、min/max:number（有限且 min≤max，单值 min=max）、unit:string、coordinate_frame:string/null、measurement_role:Enum（ground_truth、measured、estimated、assumed）、evidence_locator:`array<Locator>`。单位须与 quantity 相容，不猜测单位、坐标系及数值；other_specified 必须附明确定义及定位。嵌套可空字段采用相同 Condition 包装或 schema 固定的 field_states 路径映射，禁止无状态裸 null。Locator 定义见 §4.2。conditions 为上述字段的封闭对象（additionalProperties=false），同名 Assessment 投影确定性生成，不得另录矛盾值。JSON Schema 合格不等同科学门禁合格。

#### 3.1.1 空值隔离及人工复核时限

unknown 仅表示提取、解析、访问失败或尚未核验。首次持久化 unknown 即自动追加人工复核工单至 tasks.jsonl，含 assessment_id、field_path、scope_id、unknown_since_utc、failure_reason、来源 Version、review_condition、deadline_at_utc、review_task_id；同实体、字段、作用域的开放工单唯一，重试不得刷新起始时间或重复创建。

unknown 未升级驻留上限固定为 **24 小时（UTC，自 unknown_since_utc 起）**。每次写入、任务恢复和 Checkpoint 校验时检查；到期未解决必须自动转为 unknown_review_required，保留原时间、原因及工单，标记超时和优先级。不以重建 ID、刷新时间或改成 not_reported 消除超时。离线期间不虚构后台执行，恢复时立即补做检查；存在未升级超期 unknown 不得通过有效 Checkpoint。

人工复核有证据方可转 reported；核查完整相关原文确未披露方可转 not_reported；有不适用依据方可转 not_applicable；仍无法核验则维持 unknown_review_required 和未完成工单。影响主张判断的 unknown、unknown_review_required、关键 not_reported 均使 handling_level=insufficient_evidence；不影响独立子主张的缺失字段不拒收整个 Work。引用作用等非 conditions 的 unknown 按各自核验语义处理，不混入本空值枚举。

### 3.2 量化证据准入与拒收阈值

拒收对象是具体主张的合格证据资格，不是合法发现的 Work。Assessment 必须记录 claim_id、claim_type（theoretical、biological_mechanism、engineering_performance、engineering_trajectory、other_specified）、evidence_admission_status（eligible、insufficient_evidence、pending_review）、rejection_codes、dataset_records、baseline_records、condition_levels、metric_records、proof_record。

统一门禁：主张必须具有与证据路线、条件相符的严密数学推导或量化实验/仿真支撑；不以与主张无关的量化数据代替证明。

- 理论主张：至少一个可核验结论、完整推导定位、模型、关键假设、变量/尺度、适用条件、退化及反例边界。proof_record 包含 assumption_locators、derivation_locators（均为非空 Locator 数组）、conclusion_locator（Locator 对象）、checked_by（string）、verification_status（§4.2 枚举）。定性描述、无推导的公式及假说不是证明。
- 实验/仿真、生物机制与工程效果：至少 1 项与主张直接对应的可核验量化结果（数值或可复核原始数据）、指标定义、单位、数据/刺激/仿真出处及条件；记录适用样本数/试验数、变异或不确定性及缺失状态。改善声明至少 1 个可比较基线/对照及效果量；因果主张须有适用干预或识别依据。决定性对照、样本或统计设计缺失不得凭数字本身通过。
- 工程轨迹主张：必须有基准数据集出处（名称、版本、URL/DOI 或原文定位、序列/划分、真值来源）、运动/噪声条件、至少 1 条评估序列及 ATE 与 RPE 的明确数值/量级、定义、单位、对齐方式、RPE 时间/距离间隔、统计量和失败样本口径；数学等价指标须给出定义与等价关系，不伪造 ATE/RPE。非轨迹工程主张（如两帧旋转/平移方向、速度编码、传感器延迟）必须提供相应真值指标和数据出处，不要求不适用的轨迹指标，不得升格为轨迹性能结论。

MetricRecord 类型固定：metric_id:string、metric_name:Enum（ATE、RPE_translation、RPE_rotation、rotation_geodesic_error、translation_direction_error、angular_velocity_error、linear_velocity_error、depth_error、correlation、response_amplitude、response_latency、time_constant、adaptation_gain、receptive_field_error、selectivity_index、contrast_sensitivity、effect_size、runtime、failure_rate、other_defined）、definition:string、value:number/null、unit:string、statistic:Enum（single、mean、median、rmse、std、quantile、confidence_interval、other_defined）、sample_count:integer/null、dataset_id:string/null、baseline_id:string/null、alignment:Enum（none、SE3、Sim3、scale_only、other_defined、not_applicable）、alignment_source:Enum（ground_truth_fit、external_metric_calibration、none、not_applicable）、interval:QuantityRange/null、uncertainty:object/null、evidence_locator:`array<Locator>`、field_states:object。metric_records 为该类型数组。数值有限且满足对应物理值域；估读图表标明方法、精度及来源；未取得数值不得编造。other_defined 不能绕过门禁。

用于核验最低条件数、数据来源和基线的结构化记录必须包含：

| 字段 | 类型与最低字段 |
| --- | --- |
| dataset_records | `array<DatasetRecord>`；dataset_id:string（Assessment 内唯一）、name:string、version:string/null、data_kind:Enum（public_benchmark、author_experiment、simulation、recorded_flight、neural_recording、other_defined）、source_locator:Locator、sequence_ids:array（string）、split_id:string/null、ground_truth_source:Locator/null、ground_truth_independence:Enum（independent、used_for_calibration、used_for_alignment、not_applicable）、field_states:object |
| baseline_records | `array<BaselineRecord>`；baseline_id:string（Assessment 内唯一）、baseline_type:Enum（prior_method、ablation、control_group、pre_adaptation、null_model、ground_truth、other_defined）、description:string、dataset_id:string/null、condition_ids:array（string）、metric_ids:array（string）、evidence_locator:Locator 数组、field_states:object |
| condition_levels | `array<ConditionLevel>`；condition_id:string（Assessment 内唯一）、factor:Enum（contrast、spatial_frequency、texture、speed、adaptation_state、environment、motion_component、cell_identity、control_intervention、other_defined）、level_id:string、quantity:QuantityRange/null、description:string、evidence_locator:Locator 数组、field_states:object；数量门禁按不同 factor 下经核验的不同 level_id 计数，不以重复试验或文字描述重复计数 |

MetricRecord 的 dataset_id、baseline_id 以及 method_and_validation 中的 dataset_ids、baseline_ids、metric_ids 必须引用本 Assessment 的相应记录；baseline_records 的 metric_ids 与 condition_ids 同样必须解析。其他可空字段按 §3.1 的状态语义登记；不得将未披露信息补写为事实。工程轨迹声明必须验证实际关联数据及对齐条件，而非仅检查指标名称存在。

各 L 的最低定量阈值（严格理论证明按相应理论路径审核）：

| L | 最低可核验阈值 |
| --- | --- |
| L01 | ≥1 深度/邻近度/空间信息量化指标及真值、可比较空间条件或明确任务；完整重建须有结构/深度误差与平移尺度条件 |
| L02 | 每个声称消除依赖的因素 ≥2 个受控水平/图案条件及 ≥1 速度误差或稳定性指标；改善须有对照 |
| L03 | ≥1 瞬态/适应量化指标；适应效应 ≥2 个可比较状态，局部/广域分离须有对应控制 |
| L04 | ≥1 明确自然/高速/复杂刺激条件及 ≥1 量化结果；速度泛化 ≥2 个可比较速度条件且覆盖主张范围 |
| L05 | ≥1 明确物种及 VS 细胞编号/特征，≥1 定量感受野比较或机制相关响应/连接强度数据；因果解释须有干预/比较 |
| L06 | 每个声称恢复的运动分量 ≥1 对应误差、解码或串扰指标；混合运动主张 ≥1 混合运动验证条件；绝对尺度另过 §3.3 |
| L07 | 幅值编码 ≥2 个真实速率/幅值水平，涵盖所主张平台区，报告幅值误差或可区分性；仅方向不能通过幅值门禁 |
| L08 | ≥1 有出处的距离/飞行统计量及样本信息或自适应效果量；跨环境声明 ≥2 个明确不同环境及比较；绝对尺度另过 §3.3 |
| L09 | ≥1 明确 Hx 细胞/物种及量化感受野、响应或选择性；同等假设检验须有假设、统计量/效应与比较依据 |

这些阈值是证据完整性下限，不是跨学科统一准确度或显著性门槛。特定准确度声明须按其预先定义的误差界或判据核验。

rejection_codes 白名单：missing_fulltext_evidence、missing_rigorous_derivation、missing_quantitative_result、missing_metric_definition_or_unit、missing_dataset_provenance、missing_baseline_or_control、missing_sample_information、missing_critical_conditions、threshold_not_met、missing_trajectory_metrics、invalid_metric_alignment、missing_metric_scale_prior、scale_observability_not_demonstrated、unsupported_generalization、conflicting_evidence_unresolved、schema_invalid。任何必要门禁失败，记录代码、依据及复查条件，强制 handling_level=insufficient_evidence；不列为合格进展。可定位的失败 Assessment 留在证据矩阵与审计数据；完全无定位则仅记录任务。合格负证据及不可观测性证明仍可纳入主题表。不得据此拒收整篇 Work。

### 3.3 L06/L08 绝对尺度可观测性门禁

已标定单目中心投影、未知场景结构且无度量约束时，同时缩放平移与场景距离不改变图像观测。固定任意尺度、平移范数归一化、相对深度及以真值进行 Sim(3) 对齐均不能证明绝对平移尺度恢复。

凡声称完整六自由度且包含绝对尺度的 L06/L08 主张，必须登记（claims_absolute_scale.status=reported 且 value=true）：

- claims_absolute_scale: `Condition<boolean>`，§3.1 的 scale、scale_source_prior、scale_observability、motion_dof、known_translation；scale_prior_details 为结构化数组，包含先验类型、物理量/单位、数值或标定依据、证据定位、获取阶段及独立于待估尺度的程度。
- measurement_model、state_variables、gauge_freedoms、observability_assumptions、observability_argument_locator、degeneracy_conditions、excitation_requirements、external_measurement_sources；明确先验如何破除尺度自由度及成立、退化条件。IMU 融合、已知基线/场景、特定机动等只是潜在来源，不自动意味着尺度可观测。度量训练先验须说明训练/测试与泛化限制，不等同严格几何可观测性。
- 经验主张必须提供未依赖真值拟合比例的度量尺度误差及实际平移误差、真值独立性、对齐方式和尺度标定来源；仅 Sim(3) 结果不是绝对尺度证据。严格理论主张必须提供尺度破除的推导及条件，不强制要求不适用的实验。
- 无有效尺度来源（none、未披露或未知）、无可核验可辨识性说明、经验验证缺失或仅用真值拟合尺度时，禁止收录为已证实的绝对尺度主张：evidence_admission_status=insufficient_evidence，handling_level=insufficient_evidence，记录 §3.2 对应代码。Work、原主张及证据定位仍保留；旋转、方向、相对尺度的独立合格结论另建 Assessment；不可观测性证明作为合格反证。

同一 Work 可归多个 L，每个 L 具有独立证据；不同路线、条件、主张分别建立 Assessment。多主题计数之和不等于独立 Work 数。

## 4. 数据库定义与基本原则

### 4.1 数据源及一致性

`temp/` 采用 UTF-8 JSONL 作为实体、关系、日志和任务的规范结构化数据源；作用域及 Checkpoint 元数据采用 JSON，风险与变更记录采用 Markdown。由规范结构化数据确定性生成根目录 `ref.bib`、`ref.html`、`misc.html` 及 `ref-data/`，不独立手工维护相互冲突的内容。

- ref.bib 是规范书目全集，每个有效 Work 恰有一条 BibTeX 条目。
- 离线书目分为九张主题表和独立的 U00 页。每个有效 Work 至少出现于一张表。摘要、状态、研究结论及其证据保存在规范数据和相应研究导出中。
- 所有已识别的 Work 均入库，包括无关、背景、全文不可得、书目暂定、范围外和非学术资源。相关性筛选只影响分类及已声明的扩展范围，不删除已发现书目。不能定位独立书目身份的原始引文出现项依 §4.3 保留，不制造虚假 Work。
- 每个 Checkpoint 同步提交两份根目录输出、§8.4 五个研究视图及对应审计数据。只有通过 §9 对账的提交才可作为有效 Checkpoint。

### 4.2 实体及固定最低字段

字段名采用 snake_case；主键不可复用；外键必须可解析至有效实体或有明确指向的历史别名。枚举字段仅使用本文件或 §8.3 字段定义中的固定值。未知、未披露、不适用的语义必须区分；未知标识用 null 配合状态表示。所有来源记录 URL/标识、取得日期、来源版本、核验状态及许可。

| 实体 | 固定最低字段 |
| --- | --- |
| Seed mapping | seed_id、upload_id、work_id、version_id、target_related_id、seed_relation_type、relation_type、verification_status、notes；去重审计见 §2.2 |
| Upload | upload_id、filename、sha256、pages、text_extractability、source、received_at、internal_batch_id（仅内部，不在正文或 HTML 展示）、work_id、version_id、duplicate_of_upload_id、discovery_route、discovery_path、admission_status、relation_type、verification_status、notes |
| Work | work_id、work_key（BibTeX key）、canonical_title、title_variants、authors、document_type、publication_status、year、publication_date、venue、volume、number、pages/eid、publisher、identifiers、doi、url、language、discovery_sources、identity_confidence、verification_status、merge_history、fulltext_status、abstract_status、abstract_source、abstract_items、license、u00_reasons、review_condition、dimension_status |
| Version | version_id、work_id、version_type、version_date、identifiers、source、url、file_records（sha256、pages、text_extractability、取得时间、许可、解析状态）、verification_status、related_version_ids、version_materialization |
| ReferenceOccurrence | occurrence_id、citing_work_id、version_id、reference_label、section、page、raw_reference、raw_fingerprint、candidate_ids、cited_work_id、identity_confidence、verification_status、source、failure_reason |
| CitationEdge | edge_id、citing_key、cited_key、occurrence_ids、discovery_sources、verification_status、citation_roles、context_locators、date；方向恒为 citing → cited |
| Person | person_id、display_name、name_variants、orcid、external_ids、identity_confidence、verification_status、affiliation_history（org_id、角色、起止时间及依据）、sources |
| Organization | org_id、canonical_name、name_variants、raw_affiliations、ror、external_ids、organization_level、parent_org_id、historical_relations、valid_from、valid_to、verification_status、sources |
| Project | project_id、canonical_name、grant_id、org_ids、person_ids、start_date、end_date、objective、url、output_work_ids、project_relation、evidence_locator、verification_status、sources |
| Assessment | assessment_id、work_id、work_key、limitation_id、claim_id、claim_type、relation_type、handling_level、evidence_level、evidence_kind、evidence_route、conditions、species、motion_type、environment、scale、method、results、baseline、effect、dataset_records、baseline_records、condition_levels、metric_records、proof_record、evidence_admission_status、rejection_codes、claims_absolute_scale、scale_prior_details、measurement_model、state_variables、gauge_freedoms、observability_assumptions、observability_argument_locator、degeneracy_conditions、excitation_requirements、external_measurement_sources、remaining_limitations、counter_evidence、counter_evidence_types、evidence_locator、provenance_upload_ids、provenance_version_ids、assessment_status、superseded_by_assessment_id、cascade_event_id、discard_reason、fulltext_status、verification_status、citation_roles、project_relation、statement_basis、reviewer、date、biological_implications、engineering_implications |
| Alias | alias_id、entity_type、raw_identifier、normalized_identifier、target_id、historical_key、reason、source、verification_status、date |
| Query / Task / Checkpoint / Scope | 采用 §5.6、§6.2、§8.3、§9.1 定义的固定字段 |

Assessment 的 species、motion_type、environment、scale 是 conditions 对应字段的确定性投影，不得独立录入冲突值。evidence_locator 为数组；每项含 source_id、version_id（适用时）、upload_id（适用时）、URL/标识、页码/节/图/式/表/段落中适用的位置、访问日期及证据说明。文献全文、摘要、引用关系、项目关系的核验状态独立记录。

关系类型固定为 cites、authored_by、affiliated_with、participates_in、funded_by、project_output、version_of、related_work、related_to_limitation；发表机构关联必须带时间及来源。Work 间 related_work 的子类型固定为 preliminary_of、expanded_from、contains_publication、included_in_thesis、related_report、translation_of、correction_of、other_verified_relation、unverified_relation；不同 Work 不能仅以 version_of 替代实质出版关系。共作者或同机构不证明实际引用、方法继承或共同参加项目。

通用状态枚举：

| 字段 | 值 |
| --- | --- |
| identity_confidence | confirmed、probable、ambiguous、unresolved |
| verification_status | unverified、source_supported、verified、conflicting、rejected |
| document_type | journal_article、conference_paper、preprint、thesis、technical_report、book、book_chapter、patent、software、dataset、project_resource、web_resource、personal_communication、other |
| publication_status | published、accepted、preprint、unpublished、withdrawn、retracted、unknown、not_applicable |
| version_type | version_of_record、accepted_manuscript、preprint、submitted_manuscript、institutional_copy、translation、corrected_version、other、unknown |
| version_materialization | bibliographic_only、file_available、structured_fulltext、partial |
| admission_status | admitted、pending_identity；拒绝文件只在 rejected_uploads.log 记录 rejected |
| assessment_status | active、pending_review、merged、discarded；merged 须有 canonical 指针，discarded 须有废弃理由 |
| text_extractability | extractable、partial、image_only、unreadable、unknown、not_applicable |
| Upload / Seed mapping 的 relation_type | canonical、additional_version、duplicate_upload、unresolved |
| organization_level | university、research_institute、faculty、department、laboratory、research_group、research_center、other、unknown |

confirmed 或 verified 必须有支持依据。撤稿及更正记录保留原书目与状态，不将撤稿结果当作有效的正面结论。

所有实体核心 ID、外键、key、枚举与时间为 string（符合固定格式/枚举）；标志为 boolean；计数为非负 integer；测量为有限 number；多值字段为带 item schema 的 array；嵌套关系、证据及条件为封闭 object；null 仅在字段明确可空且具有状态依据时允许。Assessment 的 claim_id 为稳定字符串，§7.2 多标签为去重枚举数组，handling_level、evidence_level、evidence_route、evidence_admission_status、assessment_status 为单值枚举；核心条件及指标按 §3.1–§3.3。provenance_upload_ids、provenance_version_ids 为唯一外键数组，superseded_by_assessment_id 为可空 Assessment 外键，cascade_event_id 为可空事务 ID；discard_reason 为可空说明。scale_prior_details 每项为 object（prior_type:Enum、quantity:QuantityRange/null、calibration_basis:string、independence_basis:string、acquisition_stage:Enum[training, calibration, runtime, evaluation, other_specified]、conditions:string、evidence_locator:`array<Locator>`）；claims_absolute_scale 为 `Condition<boolean>`（reported=true 表示有定位的明确主张，reported=false 表示核验后无该主张；未知不得默认为 false），measurement_model 为 string/null，state_variables、gauge_freedoms、observability_assumptions、degeneracy_conditions、excitation_requirements、external_measurement_sources 为结构化对象数组（description:string、evidence_locator:`array<Locator>`），observability_argument_locator 为 Locator 数组；绝对尺度主张必须满足 §3.3，其他主张按不适用状态处理。proof_record 为 §3.2 的 object/null。字段缺失/不适用理由按 §3.1 记录。schema.json 必须实现字段级校验与跨实体语义检查，不把任何核心枚举降级为自由文本。

### 4.3 书目身份归一化、去重与计数

1. 优先使用可核验的 DOI 或稳定出版标识。DOI 归一化：去除外围空白、doi: 前缀及 http(s)://doi.org/、http(s)://dx.doi.org/ 解析器前缀；解析 URL 时将路径内合法百分号编码解码一次，去除解析器 URL 的查询参数和片段；保留 DOI 本身有效标点，禁止盲目删除末尾字符；ASCII 字母转小写并核对 DOI 注册记录的题名、作者、年份及类型。原始 DOI 与规范 DOI 同时存入别名索引；错误或冲突 DOI 不自动合并。
2. 无 DOI 文献按规范化题名、作者/机构作者、年代、出版物、卷页、报告编号/ISBN/专利号等组合核验。Unicode NFC/NFKC、空白、大小写、重音、连字符、OCR 与译名差异仅用于匹配候选，原始题名和姓名必须保留。模糊匹配不得单独作为合并依据；冲突交人工复核。
3. 相同字节内容只保留一个文件内容身份；相同 Work 的不同 Version 均保留。作者稿、镜像、正式版的对应关系依证据确认；具有独立出版身份的会议论文、期刊扩展版、章节、学位论文及 §2.2 指定的独立书目不得因内容相似而误合并。已去重 Upload 按 §2.2、§8.3 审计，指向既有实体并强制执行 §1.3 级联。
4. 能识别独立书目但字段不足或存在合并疑义的 Work 使用暂定 key、真实已知字段和 identity_confidence，进入 ref.bib 与 U00。无法建立独立身份的原始引文标记 unresolved，保留 occurrence_id、原始字符串、指纹、查询记录及重试入口，不计为 Work。项目实体与可独立引用的项目资源分开。
5. 发现已存在 Work 时仅补充来源、Version、引文边、缺失字段和未完成任务。经核验合并重复 Work 时，保留被合并 work_id、历史 key 与迁移证据，更新全部外键、合并关系及评估，执行 §1.3 级联；不删除原始引文出现项、失败记录和历史 Checkpoint。
6. BibTeX key 使用第一作者姓氏的 ASCII 转写（保留原姓名于 author）加四位出版年，如 Kern2005。机构作者采用其已核验的规范短名 ASCII 转写；转写去除组合重音及非 ASCII 标点，空白转为下划线，无法可靠转写使用稳定的 ID 后缀。不知道作者或年份时使用 Temp 加不可复用的 work_id 安全片段，标记暂定。冲突按首次分配顺序使用 a、b、…、z、aa、ab… 后缀；已分配 key 永不因插入或排序重排，合并及必要纠错保留历史别名，禁止复用废弃 key。
7. 计数：Seed record 数仅由 §2.2 得出；Upload 数为 uploads 与 seed-manifest 中去重审计 Upload 的唯一 upload_id 并集；文件数为已核验非空 SHA-256 的不同值数（缺失哈希单列）；Version 数为有效 version_id 数；规范 Work 数为有效 work_id 数（confirmed 与暂定分别报告，已合并别名及 unresolved occurrence 不计）；引文出现项、唯一有向边、有效 Assessment（active，按 evidence_admission_status 分组）、pending_review、merged/discarded 审计记录、拒绝文件事件及主题表行数分别统计。

## 5. 文献发现与递归检索

主流程固定为：种子导入 → 向后引文 → 向前引文 → 作者追踪 → 机构/项目追踪 → 证据评估 → 验收。新增 Work 按 §5.6 返回向后引文及其他扩展队列。检索前执行 §8.3 缓存及去重检查。

### 5.1 阶段 A：种子导入

- 按 §2.2 固定种子拓扑、建立 Seed record 与 seed-manifest、Upload、Work、Version 映射，先执行 §2.3 准入；核验文件可读性、完整性、哈希及版本，提取作者、发表时机构、出版信息和摘要。
- 按 §4.3 识别重复与相关独立书目；已去重 Upload 按 §2.2 保存，不另建 Work；PPT 仅为分类来源，不作为论文引用，不建立 Work。
- 所有种子进入处理队列；文件不可得而身份可确认时仍入库，记录缺口。
- 载入既有规范数据、历史 key 和任务状态，按 §8 生成输出。

### 5.2 阶段 B：向后查找参考文献

对每个 Work 的未完成 references 任务：

1. 优先读取合法可用的原文或出版商结构化全文，定位 References/Bibliography 及附录、补充材料的独立书目。覆盖双栏、跨页、扫描及缺页场景，核验版面及列表边界；必要 OCR 必须记录方法、误识别风险及人工复核。
2. 逐条保留原始字符串、参考文献序号、页码/节、来源 Version、指纹与核验状态，识别稳定标识，匹配既有 Work。原始引文不得因不相关、过早、低被引量或文献类型而静默删除。
3. 身份可识别的新增 Work 按 §4 入库并加入扩展队列；未取得合法全文时利用允许来源补充元数据和摘要，结构化引用列表须标注来源、覆盖和与全文核验的区别。保留引用出现项及施引→被引边。
4. 重复处理新 Work 的向后任务直至适用队列为空；不得将没有 PDF 或未发现引用数据的 Work 标记为完成。
5. 无法识别、缺全文、缺参考文献、接口失败或限流分别记录原因、状态、尝试证据与重试入口。verified_none 必须有明确无参考文献的证据；检索无结果不能代替该证据。

### 5.3 阶段 C：向前查找施引文献

对范围内每个 Work 使用 DOI、数据库 ID、规范题名、作者/年份和已核验 Version 查找冻结快照内可发现的全部施引 Work。使用独立来源互补，遍历分页、检查总量并记录差异，不以被引计数或前若干条代替完整结果。

将范围内身份可识别的施引 Work 全部入库；查证实际引用边、获取正文引用位置、记录作用。仅索引支持的边标记 source_supported，语境未核验时 citation_roles 为 unknown。查询失败、截断、未收录、访问受限不能解释为零施引。新增 Work 返回阶段 B，按 §5.6 继续扩展。

### 5.4 阶段 D：作者追踪

- 处理范围内 Work 的全部署名作者，不限第一/通信作者；以 ORCID、署名机构、合作者、履历、姓名变体及出版记录消歧，不以姓名相同自动合并。
- 查找该作者的其他 Work，按相对基准 Work 的时间区分前期、同期与后续成果；范围内发现的 Work 全部登记，不要求直接引用基准论文。发表时机构、历史机构与当前机构分别核验。
- 查找公开学术项目、基金、研究方向及其成果；记录项目目标、参与者、时间、来源和论文关系。独立可引用报告、数据集、软件或项目页面建立相应 Work；不可独立引用的项目仅建立 Project，禁止虚构论文。
- 新 Work 返回阶段 B；作者消歧及检索分页按 §5.6 记录。

### 5.5 阶段 E：机构及研究项目追踪

- 建立作者发表时机构的层级、历史名称、研究组、研究人员公开身份及关联时间。核心范围为核实的实验室、课题组和项目；从核心范围扩展至同一大学/研究所其他团队与 L01–L09 相关的研究，不无条件抓取全校全部学科。
- P1 在 scope.json 中固定关键词/检索式/机构层级表：limitation_id、语言、关键词与同义词、布尔检索式、来源及字段、organization_level、org_id、父子机构扩展规则、研究团队/项目准入条件、时间边界、命中及排除依据。未经记录和批准不得任意缩小已冻结的范围；扩展范围变更须另立 scope_id。
- 查找机构库、课题组/研究人员成果列表、公开项目与基金、官方成果清单及论文资助致谢；对同一机构其他团队使用冻结的主题检索式。独立推进同类问题但未引用基准论文的 Work 同样纳入。
- 项目与 Work 的关系必须以官方成果记录、项目编号、正式资助说明或其他可追溯资料判定；同机构、同作者或共同发表仅为线索。记录不同来源冲突，不将间接线索作为已证实项目产出。
- 阶段 E 的主题边界仅约束机构扩展任务，不删除阶段 B/C/D 已发现的无关 Work。新增 Work 返回阶段 B 并按 §5.6 扩展。

### 5.6 固定任务编排、闭包与 Checkpoint

设 S 为 §2.2 的 Seed record 所映射的 Work 集合；D 为已入库有效 Work 集合；R、C、A、O 分别为作用域内向后参考文献、向前施引文献、作者作品及机构/项目作品的可发现目标集合。normalize 执行 §4.3。对固定作用域，递归目标定义为：

    D₀ = normalize(S)
    Dₙ₊₁ = normalize(Dₙ ∪ R(Dₙ) ∪ C(Dₙ) ∪ A(Dₙ) ∪ O(Dₙ))

任务编排固定为六步：

1. 载入规范数据、Seed record 映射和未完成任务。
2. 按广度优先处理适用的向后引文队列，归一化发现对象并生成任务。
3. 对已冻结的当前工作集合处理适用的施引、作者、机构及项目扩展任务。
4. 每个新增 Work 执行发现路径核验、文件准入（§2.3）、去重级联（§1.3）、入库及任务登记，返回第 2 步；已存在 Work 补充新增关系，不重复已成功的同参数查询。
5. 对已发现 Work 执行强类型、量化及尺度门禁，生成十表及 §8.4 五个研究视图；检索与评估允许交错，阶段门禁按 §10。
6. 保存并校验 Checkpoint；只要存在适用且未完成的任务，就继续在固定作用域内处理；闭包及停止声明依据本节条件。

采用分阶段扩展、完整递归目标和持久化队列。不得未经批准设置最大深度、每篇文献数量上限、仅处理种子施引者或只保留正面/相关结果。记录最短发现距离及来源链；优先级只决定调度顺序。每个任务以实体、任务类型、scope_id、来源、规范参数及快照版本确定身份，使用持久化 visited/缓存索引；新发现的关系或未完成维度仍生成适用任务。

Scope 以 SCOPE- 加稳定序号标识；每次运行绑定一个 scope_id 和起始/结束 checkpoint_id（CP- 加稳定序号）。P1 冻结 cutoff_at（ISO 8601，含时区，并存 UTC 值）、索引查询日期、来源准入、类型/语言/年代边界、机构检索式、资源与时间/API/人工复核预算，保存于 §8.3 指定的 scope.json。来源不具备历史快照能力时，记录查询时点与索引漂移，不虚构可复现的历史结果。新发表和索引更新依 P8 处理。

达到预算、遭遇限流或中断时，必须保存 Checkpoint、tasks.jsonl 中的游标、待办、错误码/原因与复查条件；报告已完成 Checkpoint CP-…、作用域 SCOPE-…、剩余任务队列及覆盖缺口。预算仅触发暂停，不等于截断或完成；恢复从已验证游标进行，不丢弃未完成任务。

严格闭包的验收条件：在固定作用域及可验证来源覆盖内，Dₙ₊₁ = Dₙ、全部适用扩展任务完成或有可证明的不适用/无数据状态、全部可见分页遍历并对账、无未披露失败、无未解析的身份阻断或未确认的截断。仅因为没有新增 Work 不能声明闭包成立。有未处理、受限、不完整或不可核验任务时，报告已完成范围和未完成缺口；不得称为已穷尽。全科学文献的绝对穷尽不属于可保证的验收口径。

### 5.7 文献类型及语言边界

范围内学术文献包括期刊、会议、预印本、学位论文、技术报告、书籍、章节、专利及具有独立可引用身份的软件、数据集和研究资源。非学术资源、非英语文献、非数字化文献和灰色文献不得因类型、语言、年代或获取困难而自动排除；原始引用出现项均保存。独立可识别资源进入 Work；无独立身份的个人通讯等依 §4.3 登记原始引用。不具备参考文献或施引索引的资源，按实际证据标记相应状态；不得假定无数据。任何明确排除类别、语言、年代或来源都必须在 scope.json 披露范围、依据和批准记录；已识别的范围外 Work 仍入库并记录不展开原因。

## 6. 数据来源与全文/元数据策略

### 6.1 允许来源与准入条件

允许使用现成网站、公开学术数据库、官方 API、授权浏览器访问、合法开放数据及必要辅助解析工具；不要求建设通用检索软件或逐站开发爬虫。按来源能力选择互补渠道，而非假定所有资源具备相同覆盖和接口。

| 用途 | 允许资源 |
| --- | --- |
| 全文、参考文献解析 | 合法 PDF、出版商 JATS/XML、GROBID、版面解析与人工复核 |
| DOI/出版元数据 | Crossref、DataCite、DOI 登记页面、出版商、[DBLP](https://dblp.org/) |
| 引文/施引 | OpenAlex、Semantic Scholar、OpenCitations、Crossref 可用字段、PubMed/Europe PMC、具备合法授权的 [Web of Science 中国入口](https://webofscience.clarivate.cn/wos/alldb/smart-search) 与 [国际入口](https://www.webofscience.com/)；同一数据库不同入口不计独立来源 |
| 出版物及开放学术资源 | [ScienceDirect](https://www.sciencedirect.com/)、[PubScholar](https://pubscholar.cn/)、PMC/Europe PMC、出版商网站及大学/研究所机构库 |
| 预印本及版本线索 | [arXiv](https://arxiv.org/)、[ChinaXiv](https://www.chinaxiv.org/home.htm)、[alphaXiv](https://www.alphaxiv.org/)；评论或机器摘要不作为论文原文证据 |
| 合法全文定位 | Unpaywall、开放许可出版版本、作者合法分享版本、机构存档、用户提供的合法 PDF、授权订阅 |
| 作者/机构身份 | ORCID、ROR、OpenAlex 作者/机构 ID、官方学术履历、论文署名、[Research.com](https://research.com/)、[ResearchGate](https://www.researchgate.net/)；第三方资料须核验 |
| 项目/基金 | 大学、研究所、实验室官方页面、公开基金数据库、项目报告、成果清单、论文 Funding/Acknowledgements |

每条来源的准入记录包含 source_id、名称、URL/接口、API 版本、认证方式（不含凭据）、授权/许可、适用实体和覆盖范围、分页机制、可见总数语义、历史快照能力、限额、核验方法及日期、verification_status、限制和降级方式。只有核验了相应功能与合法访问条件的来源才能作为该维度的覆盖证据。优先使用原文与官方记录；多源冲突保留并复核。不得绕过付费墙、访问控制或利用 Sci-Hub 等未授权渠道取得受版权保护全文。无法合法访问的 Work 仍进入 ref.bib 和对应 HTML 表，记录可获取元数据、缺口和复查条件。

### 6.2 查询日志及缓存

每次查询或合法的缓存命中在 queries.jsonl 中保存以下最低字段：

    query_id, task_id, scope_id, checkpoint_id, entity_id,
    source_id, endpoint_or_url, api_version, query_kind,
    raw_parameters, normalized_parameters, queried_at_utc,
    cursor_in, cursor_out, page_index, page_complete,
    visible_total, returned_count, count_before_dedup,
    count_after_dedup, new_work_ids, new_work_count,
    result_identifiers, status, verification_status,
    error_code, error_message, retry_count, retry_at,
    cache_path, cache_hit, reused_query_id, rerun_reason,
    coverage_note, license_note

查询计数（returned_count、count_before_dedup、count_after_dedup、new_work_count）确实不可得时采用 null，并由 field_states 记录 unknown 或 not_applicable 及依据；unknown 必须关联复核工单，禁止伪造为 0。原始查询UTC不可得时采用 query_time_status=unavailable_exact、queried_at_utc=null，另记 recorded_at_utc 和可核验日期，不据此证明精确时间覆盖。可见总数未知时用 null 并注明来源限制；不得以 returned_count 代替全量总数。合并不同来源结果时按 Work 身份去重，同时保留各来源计数和关系证据。缓存键及重查规则见 §8.3。遵守来源限额、分页协议及服务条款，采用退避、受控重试和可恢复任务。索引缺失不是未引用证据，未收录不是不存在。

### 6.3 摘要、全文及版权

abstract_status 及每个 abstract_items 元素的 status 采用以下固定枚举：

| 值 | 含义 |
| --- | --- |
| original_oa | 原摘要以已核实开放许可允许公开展示 |
| original_licensed | 原摘要以明确转载许可允许公开展示 |
| chinese_summary_from_fulltext | 中文忠实概括，依据合法取得的全文 |
| chinese_summary_from_abstract | 中文忠实概括，仅依据合法可读原摘要 |
| abstract_missing | 未获得可用于概括的摘要或全文 |
| abstract_restricted | 访问/许可限制使摘要或依据不能取得或公开使用 |

存在合法可用的全文或摘要时必须生成中文忠实概括并附原文链接；许可允许时另附原摘要及署名，不以登录权限推断转载许可。abstract_status 表示主展示摘要的状态，abstract_items 逐项记录 status、text、source、version_id、license、summarizer、date、source_language 及核验状态；无可展示内容时 text 为 null，并显示缺失/受限及原因。不依据标题、机器生成摘要或未读来源编造论文摘要。原摘要与中文概括明确区分；中文概括须经依据版本核对。

fulltext_status 固定为 pending、available_unverified、available_verified、partial、not_found、restricted、not_digitized、retryable_error、not_applicable。available_verified 指合法可读的对应 Version 经完整性核验，不等于全部 Assessment 已全文验证。仅有摘要、片段或索引不标记 available_verified。

不得提交未获转载许可的 PDF、受限全文、受限摘要、大段受保护原文、API 密钥、登录凭据、个人联系方式及非公开个人数据。合法本地全文缓存独立管理，Git 仅保存允许公开的元数据、摘要概括、必要合法摘录、证据定位及脱敏日志。

## 7. 针对九项局限性的证据分析

### 7.1 逐篇阅读与引用语境

对可能相关的 Work 读取合法可用原文，核验引言、方法、结果、讨论、公式、图表、补充材料及正文引用语境。按 §3.1、§4.2 记录原问题与假设、方法、基线、定量/定性结果、样本与实验条件、与前作的实质差异、适用条件、失效情形、原文结论及研究者推断。区分期刊正式版、报告和其他 Version。

仅摘要/书目信息只能标记为候选，不得写入全文已验证；不得以标题或索引替代结果。缺少支持某 L 的已核验正文证据时不作直接或部分处理判断，相关 Work 进入 U00（除已具备其他主题的合格 Assessment 者）。非论文的官方项目/数据文档只支持其能够核验的事实与研究关系，不自动支持论文的科学效果。负结果、反例、复现失败及不同物种/条件下的矛盾证据单独标记。

### 7.2 固定证据矩阵

每条 Assessment 绑定一个 limitation_id、一个 evidence_route、一个 claim_id，独立记录 §3.1 强类型条件及证据定位，执行 §3.2–§3.3 门禁。多标签字段为数组、同一标签不重复；单值字段不可同时赋多个互斥状态。跨路线证据分别建立 Assessment，不进行未经验证的外推。

| 字段 | 类型 | 固定枚举及含义 |
| --- | --- | --- |
| relation_type | 多标签 | direct_study（直接研究）、indirect_mitigation（间接缓解/机制）、foundational_support（基础支持）、engineering_application（工程应用）、independent_progress（独立进展）、counter_evidence（反证）、background_only（背景）、unrelated（无关）、candidate（候选） |
| handling_level | 单值 | directly_addressed_under_conditions（明确条件下直接处理）、partially_addressed（部分处理）、new_evidence_or_hypothesis（新增证据/假说）、proposed_unvalidated（提出未验证）、not_resolved（未解决/反例）、insufficient_evidence（证据不足）、not_applicable（不适用） |
| evidence_level | 单值 | fulltext_result（全文推导/结果）、fulltext_discussion（全文讨论/假说）、abstract_only（摘要）、index_or_official_record（索引或官方记录）、metadata_only（书目） |
| evidence_kind | 多标签 | mathematical_proof、simulation、controlled_experiment、electrophysiology、imaging、connectomics、causal_intervention、behavioral_experiment、real_world_engineering、dataset_measurement、author_discussion、official_record、bibliographic_index、other |
| evidence_route | 单值 | biological_mechanism（生物机制）、mathematical_computational_model（数学/计算模型）、engineering_implementation（工程实现） |
| project_relation | 单值/按具体 Project–Work 边 | official_confirmed（官方证实）、funding_acknowledgment（资助致谢支持）、indirect_clue（间接线索）、unknown（未知）、not_applicable |
| citation_roles | 多标签/按具体引文边 | inheritance、improvement、comparison、replication、validation、challenge、engineering_transfer、background、unknown |
| counter_evidence | 布尔值 | true、false；未取得证据时 false 不表示不存在反例 |
| counter_evidence_types | 多标签 | negative_result、counterexample、replication_failure、cross_species_conflict、cross_condition_conflict、methodological_conflict |
| statement_basis | 单值 | author_explicit（原作者明确主张）、reviewer_inference（有依据的分析推断）、unverified_hypothesis（未验证猜想） |
| evidence_admission_status | 单值 | eligible、insufficient_evidence、pending_review；判定按 §3.2–§3.3 |
| claim_type | 单值 | theoretical、biological_mechanism、engineering_performance、engineering_trajectory、other_specified |
| assessment_status | 单值 | active、pending_review、merged、discarded；级联见 §1.3 |
| rejection_codes | 多标签 | §3.2 白名单；不足证据必须记录原因 |
| 摘要/全文状态 | 单值 | 见 §6.3 |
| U00 原因 | 多标签 | 见 §8.2 |

强制判定门禁：

- 每条 Assessment 必须具有可定位的证据条目（具体 Version 的页码、节、图、式、表、段落或精确 URL/定位）。无法定位的 Work 保留待评估任务，不生成虚假 Assessment。
- directly_addressed_under_conditions、partially_addressed 必须具有与路线一致的全文结果或等价合法原始证据、符合 §3.1 强类型条件、通过 §3.2 量化/推导及适用的 §3.3 尺度门禁、明确处理对象和结果、证据定位及未覆盖条件。仅讨论/假说且无严格推导或量化支撑者只能作为候选、handling_level=insufficient_evidence；原作者的未验证假说在说明及 statement_basis 中保留。仅摘要/书目不能满足门禁。
- evidence_level 表示来源及内容类型，不是跨学科绝对质量排名。理论证明、仿真、神经因果实验和真实工程实验按各自适用域评价；不由单项成功推及全场景。
- counter_evidence 为 true 时必须记录具体类型、相反结论、适用条件及依据；不得用剩余局限字段代替负证据。互相矛盾的 Assessment 分别保存，说明冲突而非删除。
- 引用关系不等于引用作用，只有已核验正文引用语境方可确认具体作用；索引只能证明索引支持的边。项目关系不从共同署名或机构归属直接推出。
- 证据中涉及尺度、速率、位移、旋转轴及方向时分别评价，禁止混用。条件缺失且妨碍判断时降为 insufficient_evidence；背景、无关、候选与实质相关的标签不得在同一判断中自相矛盾。

### 7.3 各主题综合说明

每张 L 表前必须按五段式给出中文综合分析：

1. 原问题：PPT 与原文的对应及表述差异。
2. 研究路线：前期、直接后续、独立后续、作者/机构/项目四类路径。
3. 具体进展、证据条件、冲突与剩余问题。
4. 可追溯研究链路：使用已核验 Work key、引文边、作者/机构/项目关系；实际引用与其他关联分开。
5. 生物机制启示与工程算法启示分别陈述，并标明证据路线和外推条件。

没有合格相关证据时显示“无相关证据”，说明检索覆盖及未完成缺口，不等同于问题未被研究。

## 8. 输出规范

### 8.1 ref.bib

- UTF-8、LF 换行、文件末尾换行；通过标准 BibTeX 解析器。按规范 ASCII key 字典序排序；已确认及暂定 Work 均生成条目，已合并历史别名不生成重复条目。
- 文献类型映射：journal_article → @article；conference_paper → @inproceedings；book_chapter → @incollection；book → @book；thesis → @phdthesis 或 @mastersthesis（学位类型明确时）；technical_report → @techreport；其余类型及非学术资源 → @misc 并在 howpublished/type 注明资源类型。未知学位类型不得冒称博士。
- 固定字段顺序（缺失或不适用的字段省略）：author、editor、title、year、month、journal、booktitle、series、edition、volume、number、pages、eid、publisher、school、institution、address、type、howpublished、doi、isbn、issn、url、urldate、language、note、abstract。DOI 采用 §4.3 规范值，URL 采用稳定来源；作者按 BibTeX and 分隔，保留原姓名重音及专名大小写保护，机构作者正确括号保护。
- abstract 非必填，仅写入可公开、与 §6.3 一致的内容。规范数据保留摘要状态。暂定书目在 note 标记身份未核验，不杜撰作者、题名、年、DOI 或摘要。运行日志不写入 BibTeX。
- 相同有效结构化输入须生成字节一致的输出，不因运行时间或排序重排旧 key；合并及更正保留别名映射。

### 8.2 离线书目索引

双击 `ref.html` 浏览 L01–L09，双击 `misc.html` 浏览 U00。两页各自搜索全部所属文献并排序，普通链接切换页面。每页只加载自己的数据与本地共享样式、脚本。主题选择、清除筛选和返回顶部支持键盘操作。U00 每页最多 50 行。原有 U00 文献锚点会跳至新页对应记录。

| 页面 | 表及稳定 ID | 独立列，依次排列 |
| --- | --- | --- |
| `ref.html` | 九张主题表，`limitation-L01` 至 `limitation-L09` | BibTeX key、题名、作者、年份、发表来源、DOI |
| `misc.html` | 其他、背景与待分类文献，`literature-U00` | BibTeX key、题名、作者、年份、发表来源、DOI、未分类原因、下一步动作 |

主题表仅输出六项书目字段及分组和行定位索引。生成时依据既有 Assessment 核对主题归属；结论、证据等级、反证统计和剩余问题均留在规范数据与 §8.4 导出中。页面显示所属作用域、检查点和文献数；研究覆盖、查询时点与缺口详见对应检查点报告。

每个 Work 使用稳定 key，作者按登记顺序列出，发表来源优先使用 venue，其次为已登记的学位授予机构或出版者。缺失字段显示“—”。已登记的 DOI 可直接复制和打开。同一主题内每个 key 一行，各 L 之间可以共用 key。

U00 逐项显示规范数据登记的未分类原因。根据快照中各工单的最新事件，从与该 Work 有明确关联且符合当前阅读范围的可执行工单中，按原优先级、最早到期时间及稳定工单 ID 选择一个动作。未满足依赖、访问或重试条件的工单保留原状态，页面仅提示等待或待核实。没有未结工单时显示“暂无已登记动作”。原复查条件、时间与审计历史保存在规范数据中。

CP11 展示版本的验收预算为每个 HTML 入口最多 32 KiB、主题页初次读取最多 128 KiB、整套最多 2 MiB。Chrome 与 Edge 分别在全新浏览器配置、网络禁用的条件下各测三次，本地页面从开始导航到可操作的中位数须在两秒内。归档检查点仍以其发布提交复现；仅展示层的后续修订另行登记文件哈希。

U00 的 `u00_reasons` 可包含多个值。

| 值 | 展示名称 |
| --- | --- |
| background | 背景文献 |
| unrelated | 主题无关 |
| pending_assessment | 待评估 |
| insufficient_evidence | 证据不足 |
| metadata_unverified | 书目待核验 |
| non_academic_resource | 非学术资源 |
| project_software_dataset_only | 仅项目/软件/数据集 |
| out_of_scope | 范围外 |
| duplicate_pending_merge | 重复待合并 |

duplicate_pending_merge 仅指身份未定的 Work 合并疑义，不是已经去重的 Upload。复查条件必须指出缺失证据、待办任务或明确不再展开的范围依据。某 Work 获得至少一个 assessment_status=active 且 evidence_admission_status=eligible 的实质相关 Assessment（含合格反证，不含背景/候选）时进入对应 L 表并从 U00 移除，保留既有 key、审计历史及其他未完成任务。U00 与所有主题表互斥；完整集合对账按 §9.2。

### 8.3 temp/ 数据及日志

固定目录如下；所有 JSONL 为 UTF-8，每行一个 JSON 对象；JSON 为 UTF-8，Markdown 为可审查文本。规范记录采用唯一 ID 与确定性字段、行排序；查询和状态事件按持久化事件顺序保存。字段定义由 schema.json 固定版本并与本文件一致；扩展字段必须有定义及迁移记录，不改变本文件强制字段与枚举。

    temp/
      seed-manifest.jsonl          # Seed mapping；去重 Upload 的唯一完整审计记录
      uploads.jsonl                # 保留的非去重 Upload 规范记录
      rejected_uploads.log         # 文件准入拒绝事件（JSONL）
      cascade-events.jsonl         # 去重/合并级联事务及审计记录
      work-relations.jsonl         # 独立 Work 关系及固定种子外键映射
      works.jsonl                  # 有效及历史 Work、状态、摘要
      versions.jsonl               # Version、文件内容身份及合法来源
      aliases.jsonl                # 标识、题名变体、历史 key 及合并映射
      reference-occurrences.jsonl  # 原始引文及定位、未解析记录
      citation-edges.jsonl         # 实际引用边及证据
      authors.jsonl                # Person、身份及隶属历史
      organizations.jsonl          # Organization、机构层级与历史关系
      projects.jsonl               # Project、参与者、成果与证据
      assessments.jsonl            # Assessment、分类与证据
      queries.jsonl                # 查询、分页、缓存、错误、重试
      tasks.jsonl                  # 任务、游标、状态事件及恢复入口
      partitions/                  # 大型 JSONL 的无损物理分片及 manifest.json
      discovery-paths.jsonl        # 已核验的发现路径；关系真实性与发现记录分级
      author-publication-leads.jsonl # 作者索引候选归属及逐 Work 消歧状态
      project-relations.jsonl       # 项目资助、参与及成果关系
      reference-coverage.jsonl      # 原文/注册参考表覆盖与缺口
      manual-reviews.jsonl          # 实际复核活动与预算核算
      runs.jsonl                    # 运行授权、预算与停止条件
      source-observations.jsonl     # 冻结作用域内追加的能力核验
      schema.json                  # 字段定义、类型、枚举、主外键、schema_version
      risk-register.md             # 风险登记
      change-log.md                # 规范数据及状态迁移、合并和范围变更
      exports/                     # §1.1 研究问题的确定性视图
        citation_graph.json
        evidence_matrix.csv
        research_entities.json
        research_entities/         # CP-0013 起按研究主体类别保存的 JSON 及目录索引
        research_paths.json
        research_implications.csv
      snapshots/
        scope.json                 # 当前活动作用域的规范执行参数
        scopes/                    # 不可变的各 scope_id JSON 快照
        checkpoints/               # 每个 checkpoint_id 的 JSON 清单与审计统计

**大型 JSONL 的存储规则。** 上表路径为逻辑数据集名称。单个 JSONL 超过 4 MiB 时，按完整行顺序无损分片：第一片保留原路径，其他片保存于 `temp/partitions/<数据集名>/<SHA-256>.jsonl`；`temp/partitions/manifest.json` 固定记录有序片路径、逐片记录数、字节数及 SHA-256，以及逻辑全集记录数和拼接哈希。每片仍逐行服从同一实体 Schema，ID 不得跨片重复；读取、去重、队列恢复、导出和验收必须按 manifest 读取逻辑全集，禁止只读取第一片。分片仅处理仓库存储与传输，不改变研究范围、队列、实体身份、原始证据或统计分母；全部分片纳入 Checkpoint 哈希和 Git。该规则适配 [GitHub 单文件限制](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)。

Seed mapping 与去重 Upload 记录通过 record_type（seed_mapping、duplicate_upload）区分，去重记录的 seed_id 为 null；保留非去重 Upload 的完整记录仅位于 uploads.jsonl。两份文件中的 upload_id 映射构成 Upload 视图，禁止重复存放同一去重审计实体。seed-manifest 中 Seed mapping 只引用对应保留 Upload，不重复维护其原文件属性；去重记录指向已存在 Upload、Work、Version，无独立 Work。上传出现项的最低审计字段如下（含内部字段见 §4.2）：

    upload_id | filename | sha256 | pages | work_id | version_id |
    duplicate_of_upload_id | relation_type | verification_status | notes

work-relations.jsonl 最低字段：relation_id、from_work_id、to_work_id、relation_type、inverse_relation_type、source_seed_ids、evidence_locator、verification_status、scope_id；种子指针由 §2.2 确定性生成，互逆关系以同一 relation_id 统计。cascade-events.jsonl 最低字段：cascade_event_id、scope_id、checkpoint_id、trigger_upload_id、canonical_upload_id、affected_work_ids、affected_version_ids、affected_assessment_ids、merged_assessment_map、discarded_assessment_ids、pending_review_ids、affected_edges、before_after_counts、reason、validation_results、transaction_status（committed、rolled_back）、created_at_utc；与 §1.3 级联保持同一事务。rejected_uploads.log 按 §2.3 追加事件，不包含受限原文。

scope.json 字段固定为 scope_id、schema_version、cutoff_at、cutoff_at_utc、index_observed_at、sources（§6.1 准入表）、document_types、languages、date_range、institution_scope（§5.5 关键词/检索式/层级表）、expansion_policy、exclusions、access_and_license、resource_limits、budget、approval、created_at。活动 scope 变更通过新 scope_id 和不可变 scopes 记录追踪。

Checkpoint 清单字段固定为 checkpoint_id、scope_id、parent_checkpoint_id、schema_version、created_at_utc、task_cursor_state、query_log_high_watermark、counts、coverage、unresolved_tasks、failure_reasons、artifact_hashes、validation_results、status。status 仅为 valid 或 invalid；有效性须满足 §9。保存 Git 提交与 Checkpoint 的对应关系（可由 Git 历史及 Checkpoint ID 定位，不在同一提交内嵌该提交自身哈希）。

查询前必须检查 ref.bib、works、aliases、原始引文指纹、queries 和 tasks；缓存键为规范实体 ID、任务类型、source_id、API 版本、规范化参数、scope_id 与快照版本。相同键下已成功的查询复用结果，不再次访问来源；仅补漏、冲突核验、失败重试或快照更新允许重新查询并写明原因。合并 Work 时别名和已完成查询状态随映射迁移，既有新关系或未完成任务仍须处理。

Checkpoint 提交前统一生成并校验 ref.bib、两页书目及全部离线资源、§8.4 五个研究视图与对应 temp 状态，失败不得标记有效；恢复时从最后有效 Checkpoint 的游标及任务事件继续。temp 审计数据纳入 Git，不得因阶段完成清空、覆盖不可变快照或将其作为普通缓存删除。受限全文、认证信息和私人数据按 §6.3 留于合法本地缓存；不提交包含秘密的查询参数、路径或错误日志。

风险登记册字段固定为 risk_id、风险、触发条件、影响、控制措施、状态、责任角色、证据/复查条件。最低风险项：

| risk_id | 风险 | 控制及验收依据 |
| --- | --- | --- |
| R01 | 编号错乱 | §2.2 唯一编号源；映射及静态检查 |
| R02 | 范围爆炸 | scope_id、分阶段队列、预算暂停；不静默截断 |
| R03 | API 限流或中断 | 退避、游标、Checkpoint 恢复及失败日志 |
| R04 | 版权/许可 | 来源准入、权限核验与公开内容审查 |
| R05 | 作者同名消歧 | 多标识核验、冲突记录、人工复核 |
| R06 | 引用索引缺失 | 多源对照、分页及覆盖缺口披露 |
| R07 | 摘要翻译质量 | 依据 Version、概括者及抽查 |
| R08 | 项目关系证据不足 | 官方记录、资助致谢与间接线索分级 |
| R09 | HTML 对账失败 | §9.2 集合校验，不通过禁止有效提交 |
| R10 | 重复合并误判 | DOI/书目联合核验、历史别名及可追溯迁移 |
| R11 | 游离文件或伪造发现路径 | §2.3 解析前阻断及拒绝日志 |
| R12 | Assessment 级联丢证据或重复 | §1.3 原子级联、外键及反证对账 |
| R13 | 量化门禁或尺度假设误判 | §3.2–§3.3 逐主张核验与拒收代码 |
| R14 | 非法枚举或 unknown 超时 | §3.1 强类型及复核工单 |
| R15 | 研究视图与规范库不一致 | §8.4、§9.2 导出对账 |

### 8.4 研究问题交付视图及格式

从 CP-0013 的工作快照起，Q2 的入口为 `temp/exports/research_entities.json`。打开同级目录 `research_entities/index.json` 可按需查阅五组独立 JSON 文件。目录 `people/` 保存人员，`organizations/` 保存机构，`projects/` 保存项目，`work_refs/` 保存 Work ID 与书目键，`relations/` 保存带来源和状态的关系。每个数据文件是带有作用域、检查点标识和 `records` 数组的普通 UTF-8 JSON，最大 2 MiB。索引列出有序文件名、主键范围、条数、字节数与 SHA-256。空集合在索引中显示为零条。按索引顺序读取各组即可重建原有 Q2 对象。入口绑定具体索引的 SHA-256，索引绑定重建对象的 SHA-256。Q3 引文图使用同一格式，按节点、边、未解析位置和独立进展四组保存。工作快照的验收状态见对应的检查点清单。

在仓库根目录运行 `python -B scripts/partitioned_research_json.py temp/exports/research_entities.json` 可逐片校验并显示重组后的 SHA-256。需要单文件供旧程序读取时，加上 `--output` 和一个新文件路径。检查点的 `task_cursor_state` 和 `unresolved_tasks` 延续相同的分片规则，分别以原始任务 ID 排序保存。检查点入口保留日期、状态、计数和验收结果，并绑定可重建原任务游标和未决任务全集的目录索引。运行 `python -B scripts/partitioned_checkpoint.py temp/snapshots/checkpoints/CP-0013.json` 可核对全部游标和未决任务，也可用 `--output` 将重建对象写入新文件。

固定路径见 §1.1。所有视图均含 scope_id、checkpoint_id、schema_version（JSON 顶层；CSV 每行），使用 UTF-8、LF、确定性排序、有限数值、无凭据/受限正文；JSON 为合法对象及数组，CSV 为 RFC 4180 风格逗号分隔、固定表头、正确引用/转义，复合字段以合法 JSON 编码在单元格内，空值按 schema 状态表示。每次有效 Checkpoint 的视图均由规范实体生成，禁止手工补填不在源记录中的事实。

| 文件 | 固定结构与最小字段 |
| --- | --- |
| citation_graph.json | nodes（work_id、work_key、canonical_title、identity_confidence、publication_status）；edges（edge_id、citing_work_id、cited_work_id、citing_key、cited_key、verification_status、citation_roles、context_locators、occurrence_ids、discovery_sources）；independent_progress（assessment_id、work_id、limitation_id、relation_type）；未解析端点单列 unresolved_occurrences（occurrence_id、citing_work_id、candidate_ids、failure_reason、canonical_dataset），按 occurrence_id 回溯原始引文逻辑数据集，不复制整段证据、不作虚假边 |
| research_entities.json | people、organizations、projects、work_refs、relations；关系字段 relation_id、relation_type、from_id、to_id、valid_from、valid_to、verification_status、evidence_locator；分别区分发表时隶属、历史隶属、资助、项目参与及实际成果 |
| evidence_matrix.csv | 固定列 scope_id,checkpoint_id,schema_version,assessment_id,work_id,work_key,limitation_id,claim_id,claim_type,evidence_route,relation_type,handling_level,evidence_level,evidence_kind,evidence_admission_status,rejection_codes,conditions,dataset_records,baseline_records,condition_levels,metric_records,proof_record,claims_absolute_scale,scale_prior_details,observability_argument_locator,effect,remaining_limitations,counter_evidence,counter_evidence_types,evidence_locator,provenance_upload_ids,provenance_version_ids,verification_status,reviewer,date；一行一个 active Assessment，含不足证据主张；pending_review/merged/discarded 不计有效行，保留于审计源 |
| research_paths.json | paths（path_id、limitation_id、assessment_id、seed_id、work_id、ordered_steps、path_type、verification_status、evidence_locators、counter_evidence、gap_reason）；每步含 from_id、to_id、relation_id、relation_type、source_id、locator；至少保存各已核验发现路径类型的代表路径，不枚举全部可能组合；不将种子预置关系或作者关联伪作引用 |
| research_implications.csv | 固定列 scope_id,checkpoint_id,schema_version,assessment_id,work_key,limitation_id,evidence_route,evidence_admission_status,biological_implications,engineering_implications,conditions,remaining_limitations,statement_basis,evidence_locator；每个 active Assessment 一行，未验证启示明确标记，不得据不足证据宣称有效 |

全部节点、边、Assessment、路径、启示必须可按规范 ID 回溯至 temp 原始数据与证据，覆盖不足及 pending_review 状态在 Checkpoint 报告单列。citation_graph.json 的实际引用边与 citation-edges.jsonl 有效边集合相等；JSON 节点/边及 CSV 主键均不得重复，边的 work_id 与 work_key 必须指向同一规范记录；work-relations 不混入 cites。两份 CSV 的 assessment_id 集合等于 active Assessment 集合；research_entities 的实体/关系集合与规范记录对账；research_paths 的每一跳核验端点、来源及关系类型，缺口显式记录。校验五文件存在、格式、表头、排序、外键、计数、哈希及作用域一致性，结果写入 Checkpoint validation_results。

## 9. 质量控制、状态及验收

### 9.1 任务状态枚举与种子映射

每个 Work 分维度记录 metadata、fulltext、abstract、references、citations、authors、affiliations/projects、assessment（结构化键 affiliations_projects）；同时为各来源、Person、Organization、Project 及扩展任务记录独立状态。dimension_status 的值使用以下状态枚举，不能以一个布尔值代替全部维度。摘要及全文的内容状态另按 §6.3 记录。

| 状态 | 含义及验收约束 |
| --- | --- |
| pending | 待处理 |
| running | 处理中，须保存游标 |
| verified_complete | 已核验完成，有来源、覆盖证据及对账 |
| partial | 部分完成，缺口与重试/复查入口明确 |
| verified_none | 经核实确无该类数据，不得以无查询结果代替 |
| needs_disambiguation | 待消歧，保留候选及冲突 |
| restricted | 访问/许可受限，不能算完成 |
| retryable_error | 可重试失败，记录错误和重试策略 |
| paused_budget | 预算暂停，保留全部待办和游标 |
| out_of_scope | 固定作用域外，记录具体排除依据 |
| unavailable_final | 已核验不可得，记录原因、证据及复查条件；不等同已完成覆盖 |
| not_applicable | 经核验不适用，记录理由 |

tasks.jsonl 最低字段：task_id、entity_type、entity_id、task_type、scope_id、source_id、normalized_parameters、task_state、cursor、dependency_ids、query_ids、attempt_count、error_code、failure_reason、retry_at、review_condition、created_at_utc、updated_at_utc、checkpoint_id、event_sequence、assessment_id、field_path、unknown_since_utc、deadline_at_utc、review_task_id、priority、overdue。人工复核工单按 §3.1.1 生成，其他任务不适用字段按 schema 标记。状态变更以追加事件保留历史，当前状态取相同 task_id 最新事件；已完成状态必须引用支持记录。

种子验收以 §2.2 为准：逐条核对 seed-manifest 映射、独立书目及版本/相关关系；去重 Upload 的原始哈希、来源和映射完整保留；计数严格按 §4.3，不得用 Seed record 数替代 Work 数。文件缺失及身份疑义必须有任务记录；核验 §2.2 所有预置外键、互逆类型及 Work 分立身份、§2.3 准入日志和 §1.3 基数与级联。

### 9.2 自动校验和人工抽查

设 K 为 ref.bib 中全部有效 key 集合，T_i 为 L0i（i=1,…,9）表中 key 集合，U 为 U00 表中 key 集合。强制满足：

    K = U ∪ T₁ ∪ … ∪ T₉
    U = K ∖ (T₁ ∪ … ∪ T₉)

- ref.bib 可无错解析，key 唯一、无未经核验的 DOI 冲突；有效 Work 与条目一一对应，历史别名可解析。无 DOI 不是失败条件。
- 按 §8.2 分别核验主题页九表和 U00 页一表的列、资源和完整集合。每表 key 唯一，所有 K 均可定位，U 与主题并集互斥。逐项核对书目字段、U00 原因和动作。跨主题行按 Work 去重，分页使用全部 U00 数据对账。
- 种子与 Upload/Work/Version 主外键符合 §9.1；实体、历史别名、原始引文及引用边可对账。引文出现项可多次支持同一唯一边；未知端点保留 unresolved 任务，不能伪造边。
- 每项已完成扩展任务必须具有来源准入、完整分页及覆盖证据；去重前后数量、可见总数差异和新增 Work 可对账；索引或访问限制不得隐藏。
- 按 §7.2 检查 Assessment 条件、路线、等级、证据定位、负证据和处理程度；人工抽查原文、摘要概括、引用语境、身份消歧、机构历史及项目关系；发现错误建立纠正任务。
- 离线检查两页的本页搜索、排序、主题选择、分页、键盘操作和旧链接跳转。索引以文本形式展示外部书目，仅加载同一目录包的脚本。核对主题页资源字段白名单和双生成哈希。
- 相同结构化输入及快照重复生成，输出字节一致。通过中断、API 限流、解析失败、重复导入及恢复测试，必须从最后有效 Checkpoint 继续，保留任务和日志，无重复条目、遗漏或错误完成状态。
- §1.3：所有有效 Work/Version/Upload 满足基数及唯一所有者，去重指针无环；核对级联前后有效 Assessment、证据与反证、外键及审计记录；失败事务不得部分提交。
- §2.2–§2.3：种子预置关系逐项对账；边界外无合法发现路径文件必须在解析前被拒且仅留审计事件，合法发现的 Work 不因文件被拒而丢失。
- §3.1–§3.3：强类型校验拒绝非法枚举、错误类型及无状态空值；unknown 必须有工单且无未升级超期记录；证据不足主张强制降级。逐项核验工程轨迹指标、L06/L08 的尺度先验、可观测性和真值对齐口径，不将相对尺度判为绝对尺度。
- §8.4：五个导出文件及格式、集合、主外键、状态、哈希与规范数据一致；引用/主体/路径关系不得混同，合格主题表只包含 eligible 的实质 Assessment 支持的 Work。

- 未通过任一强制校验的产物不得作为有效 Checkpoint 或完整覆盖证据。

### 9.3 P1 样本门禁

按 §2.2 选择三类受控样本：有 DOI 的期刊论文；无 DOI 的技术报告（以已核验无 DOI 的记录作为样本，不把暂未查到 DOI 当作已核验）；重复 Upload/Version 关系。分别验证：

| 样本 | 验收条件 |
| --- | --- |
| DOI 期刊论文 | 提取并核验书目、摘要、作者及机构、DOI 归一化、参考文献边界及原始引文；生成真实 Work/Version 映射、BibTeX 和合法摘要显示；验证缓存与日志 |
| 无 DOI 技术报告 | 以报告编号、机构、题名、作者、日期等建立可核验身份；不杜撰 DOI；分别核验版本和与相关 Work 的关系；生成书目、HTML 落位及日志 |
| 重复 Upload/Version 关系 | 复核文件指纹、同 Work 不同 Version、独立相关出版物的区别；去重 Upload 只留审计映射，引用和身份合并不丢失关系；验证重跑不重复入库 |

P1 还必须执行以下受控正/反例测试，不将虚构测试数据写入正式库：非法枚举及类型、not_reported 与 unknown 的隔离、首次自动复核工单及 24 小时超时升级（可控测试时钟）、游离文件拒收和合法发现路径准入、种子硬编码外键及逆向一致性、Assessment 等价合并/无依据废弃/独立反证保留及级联回滚、量化证据缺失和工程轨迹指标缺失降级、无度量先验的单目绝对尺度主张拒收与合法尺度证据/不可观测性反证通过、五个研究视图格式及 ID 对账。任何门禁失败阻断 P2，记录失败及重试入口。

所有样本均执行 Upload/Work/Version 映射、解析、去重、HTML 落位、日志与 K/T/U 对账，并验证来源准入及 Checkpoint 恢复。样本产物使用隔离验证目录或明确隔离的样本 scope，不污染正式书目。失败必须记录具体错误、证据、影响及重试入口；未通过门禁不得进入 P2，不能以失败记录代替通过。合规不可得情况通过替代样本验证能力，同时保留原样本的缺口记录。

### 9.4 Checkpoint 报告与最终结论模板

每个有效 Checkpoint 报告 scope_id、checkpoint_id、输入及新增/重复/待消歧 Work、§4.3 各计数、引文边、元数据/全文/摘要/参考文献/施引/作者/机构与项目/Assessment 各维度覆盖、L 与 U00 数量、分页对账、风险、剩余任务、失败原因和复查条件。报告必须包括五个视图的路径、哈希、记录数及对账结果，拒绝文件与级联计数、证据拒收代码分布、绝对尺度门禁结果、unknown 工单及超期计数。各完成度明确分子、分母和不适用项；未解决或受限项不得计入 verified_complete。

最终报告逐项采用固定结论模板：

| 字段 | 内容 |
| --- | --- |
| Work key | 规范 BibTeX key、可追溯来源 |
| 作者/团队/项目 | 相关主体、时间归属、项目关系及证据 |
| 时间 | 发表、项目或证据的明确日期 |
| 方法 | 模型、算法、实验或测量及比较基线 |
| 证据等级/路线 | §7.2 枚举与可定位依据 |
| 对应 L | §3 编号 |
| 效果与处理程度 | 数据/推导支持的结果、反例与处理程度 |
| 适用条件 | §3.1 最小可判定条件 |
| 引用前作 | 实际引文 key、语境及引用作用；独立路线单列 |
| 剩余问题 | 未解决、未验证和冲突证据 |
| 生物机制启示 | 与物种、神经元和生物证据相符的结论或假说 |
| 工程算法启示 | 工程/数学依据、使用条件及未验证外推 |

最终报告依 §5.6 声明闭包是否成立、已验证作用域、来源覆盖与缺口；不能把阶段验收、无新增结果或预算暂停当作已穷尽。

## 10. 路线图及门禁

执行状态统一记录于 [进度追踪](temp/progress.md)。CP-0013 待完成验收，最近通过验收的是 CP-0012。[CP-0013 阶段报告](temp/reports/P3-P6-CP0013.md)记录本轮研究与缺口。[检查点](temp/snapshots/checkpoints/CP-0013.json)继承 [CP-0012](temp/snapshots/checkpoints/CP-0012.json) 的数据和任务游标。CP-0003 保留为 invalid 历史。

| 阶段 | 输入 | 任务及验收产物 | 门禁 |
| --- | --- | --- | --- |
| P0 | 研究问题与用户决策 | 规范基线：交付本文件；不生成数据文件 | 规范内容、分类和编号一致 |
| P1 | 启动指令、§2.2、P0 | 建立 seed-manifest、uploads、固定关系初始化、强类型 schema、准入/级联/复核协议、来源准入表、scope.json、样本验收及五视图格式 | §9.3 通过；来源能力、范围及预算明确 |
| P2 | P1 合格产物、§2.2 | 导入种子表，锁定预置关系及外键，初始化 ref.bib、双页书目索引、temp 状态、五视图和扩展队列 | §9.1–§9.2 映射及对账通过 |
| P3 | 待处理向后任务 | 从参考文献列表递归查找前作，用书目信息核对题名、作者、年份和标识符，去重并登记引文边、发现路径及缺口 | 依 §5.2、§9.2 对账。书目身份有歧义时保留候选及复核工单 |
| P4 | 适用的施引任务 | 通过书目索引查找施引论文，对照参考文献列表核验引用关系，登记查询、分页、覆盖和新增 Work | 依 §5.3 核对来源和计数。引用作用缺乏允许材料中的明确依据时记为未核实，新增 Work 返回 P3 |
| P5 | 适用的作者、机构和项目任务 | 用论文署名、机构、登记资助信息及摘要检索相关论文，逐项核对标识符和明示的关联 | 依 §5.4–§5.5 保存关系来源。身份、项目角色及成果归属缺乏依据时记为未核实，新增 Work 返回 P3 |
| P6 | P3–P5 队列及已发现 Work | 根据书目信息、摘要和参考文献列表归类 L01–L09，记录摘要明示的主张、证据层级、出处和待核实问题，更新研究视图 | 沿用 §7、§9 的证据门禁。需要正文、图表、补充材料或实验复算才能确认的事项保持未核实和待办 |
| P7 | Checkpoint、规范输出、证据及风险 | 数据一致性、覆盖及科学结论审计，冻结验收快照，交付 §1.1、§8.4 全部产物与 §9.4 报告 | §9 强制校验通过；闭包声明满足 §5.6，未成立必须明示 |
| P8 | 新发表文献或索引更新且用户批准 | 增量更新：建立新 scope_id、差异记录及 Checkpoint；复用历史身份与查询记录，按范围重新核验 | 保留历史快照；执行 §5–§9 |

自 2026-11-28 起，后续论文检索和复核只查阅书目信息、摘要和参考文献列表。停止阅读论文正文、图表和补充材料，停止复算实验数据。各阶段按此范围执行其他章节所列任务。摘要中的作者陈述按摘要层级登记。既有检查点、原始查询、历史证据和工单时限继续留存。

P3–P6 是可循环阶段，不是只执行一次的线性流水线。Checkpoint 可交付阶段性成果，但只有对应门禁及覆盖条件成立才可标记相应阶段或任务完成。

## 11. 执行决策

本节为生效规则；正文的种子编号、题名及种子身份以 §2.2 为唯一事实源。出现冲突时以本节和 §2.2 为准；本节对其他规范内容采用章节引用，不另建事实清单。

| 决策 ID | 生效规则 |
| --- | --- |
| DEC-01 | 种子集合及编号固定为 §2.2；去重 Upload 不进入种子表、不建立 Work，其哈希、来源和映射仅保存于 seed-manifest；分别统计 Seed record、Upload、文件哈希、Work、Version（§4.3）；执行 §1.3、§2.2–§2.3 基数、级联、预置关系及准入。 |
| DEC-02 | 采用核心实验室/课题组/项目及所属机构其他团队的主题相关成果范围；固定机构层级、关键词、检索式、准入边界和依据（§5.5）。 |
| DEC-03 | 分阶段扩展、完整递归目标、持久化 Checkpoint；使用 scope_id/checkpoint_id；预算仅暂停，不得未经批准硬截断（§5.6）。 |
| DEC-04 | L01–L09 九项局限性分类固定为 §3；强类型、量化及尺度门禁按 §3.1–§3.3。 |
| DEC-05 | P1 执行参数记录于 temp/snapshots/scope.json：检索截止时间、来源可用性、许可/访问状态、覆盖、资源及预算；只使用合法资料（§5.6、§6、§8.3）。 |
| DEC-06 | 中文忠实概括及原文链接必备；原摘要须具备公开许可，缺失或受限显式标注（§6.3）。 |
| DEC-07 | temp/ 为持久化审计数据目录，纳入 Git，不得清空；目录、字段、查询及 Checkpoint 规则固定为 §8.3；拒绝事件、级联及复核工单必须可追溯。 |
| DEC-08 | 全部已识别 Work 入 ref.bib；九张 L 表与第十张 U00 对账；以 ref.bib 和 temp 防止重复检索（§4、§8、§9.2）；五个研究问题交付物固定为 §1.1、§8.4。 |
| DEC-09 | 项目目标为具体文献调查，不开发通用检索软件；采用 §6 的允许来源及工具，来源可用性、许可/访问状态、资源与预算在 P1 写入 scope.json。 |

实质性范围变更、访问授权或无法自行消歧的冲突，须登记风险或决策记录并获得必要的用户批准。

## 12. 本文件不包含/不产生的事项

- 本文件不执行 PDF 参考文献解析、外部学术检索、作者/机构/项目调查、全文获取或自动递归。
- 本文件不创建或填充 ref.bib、双页书目索引、§8.4 研究视图及 temp 数据文件，不产生或虚构检索结果、引文统计、研究成果与局限性处理结论。
- 本文件不修改 PPT、不上传 PDF、不提交运行代码；P1 允许提交合规配置模板、字段定义和必要的审计记录，不提交密钥、受限数据或私人信息。
- 启动 P1 的条件是用户发布启动指令；启动后按本文件执行，不再重复确认 DEC-01–DEC-09。

