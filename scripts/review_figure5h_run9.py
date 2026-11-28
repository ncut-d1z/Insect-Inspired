"""Build the typed S06 Figure 5h claim from the reviewed, hashed source-data summaries."""
from copy import deepcopy


def figure_claim(review, locate, unknown):
    aid = "A-RUN09-S06-L04-bIPS-mixture"
    data_id, baseline_id = "S06-F5h-bIPS-control", "S06-F5h-pure-yaw"
    method = locate("Sec27 ¶1–4,9–10; Sec26 ¶1", "球形 LED 点阵、刺激分量及减速说明。")
    species = locate("Sec17 ¶1; Sec18 ¶1", "实验动物的物种和成体阶段。")
    fig = locate("Fig5 caption, panels f–h; Sec8 ¶1–4; Sec38 ¶1–3", "比较运动方向、ROI、重复试验与钙信号标准化。")
    sheet = dict(fig, source_id="institutional_repository", url=review["source_url"], identifier="MOESM10",
                 section="Source Data Fig. 5, sheet 5h", table="5h!A21:H28",
                 evidence_note="校验原始工作簿后，逐行计算七个 ROI 的算术平均和样本标准差。")
    def state(status, reason, evidence):
        return dict(status=status, reason=reason, evidence_locator=[evidence], unknown_since_utc=None, review_task_id=None)
    def condition(value, evidence):
        return dict(state("reported", None, evidence), value=value)
    def na(reason, evidence):
        return state("not_applicable", reason, evidence)
    def missing(path, reason, evidence):
        return unknown("assessment", aid, path, reason, evidence)
    def quantity(kind, minimum, maximum, unit, frame, evidence):
        return dict(quantity=kind, min=minimum, max=maximum, unit=unit, coordinate_frame=frame,
                    measurement_role="assumed", evidence_locator=[evidence])
    # The source reports a display design and then halves the compound stimulus speed.
    # Store the source explicitly as a nominal input, never as free-walking ground truth.
    levels, metrics = [], []
    for group in review["groups"]:
        level, row = group["level"], group["cells"]
        lid, mid = "S06-F5h-level-"+level, "S06-F5h-mean-"+level
        loc = dict(sheet, table=row)
        weight = group["translation_to_yaw_weight"]
        levels.append(dict(condition_id=lid, factor="speed", level_id=level,
            quantity=quantity("other_specified", weight, weight, "dimensionless (translation/yaw stimulus weight)", "LED stimulus", method),
            description="设计平移/偏航权重为 "+str(weight)+"；偏航分量固定。", evidence_locator=[method,loc],field_states={}))
        metrics.append(dict(metric_id=mid, metric_name="response_amplitude", definition=review["metric"]+" 水平为 "+level+"。",
            value=group["mean"], unit="z-score difference", statistic="mean", sample_count=7,
            dataset_id=data_id, baseline_id=baseline_id, alignment="not_applicable", alignment_source="not_applicable",
            interval=None, uncertainty=dict(kind="std",value=group["sample_sd"],unit="z-score difference",
                description="样本标准差，分母 n−1，七个 ROI。"),evidence_locator=[fig,loc],
            field_states={"interval":na("此处度量方向选择性响应，未使用轨迹误差时间间隔。",fig)}))
    mids=[m["metric_id"] for m in metrics]
    cond={}
    cond["species"]=condition([dict(scientific_name="Drosophila melanogaster",taxon_id=None,cell_type="bIPS",cell_identifiers=["bIPS"],
        field_states={"taxon_id":state("not_reported","该文的动物与品系方法以物种名标识，未给出该动物的分类数据库编号。",species)})],species)
    cond["motion_type"]=condition("mixed_rotation_translation",method)
    cond["motion_dof"]=condition(dict(rotation_dof=1,translation_dof=1,estimated_components=[]),method)
    cond["known_translation"]=condition("externally_known",method)
    cond["speed_range"]=condition([quantity("angular_velocity",111,111,"deg/s","nominal design before compound scaling",method),
        quantity("linear_velocity",0,16.5,"mm/s","nominal treadmill equivalent before compound scaling",method)],method)
    cond["environment"]=condition("laboratory_controlled",method)
    env=dict(dataset_ids=[data_id],scene_count=None,
             fov_deg=quantity("fov",216,216,"deg","horizontal LED azimuth; vertical elevation 72 deg",method),
             distance_range=None,distance_distribution=None,distance_knowledge=None,scene_dynamics="dynamic",field_states={})
    env["field_states"]["scene_count"]=missing("conditions.environment_details.value.field_states.scene_count","源表没有提供各 ROI 的独立场景实例总数。",method)
    for key in ["distance_range","distance_distribution","distance_knowledge"]:
        env["field_states"][key]=na("刺激设计省略相对距离、透视与迫近线索。",method)
    cond["environment_details"]=condition(env,method)
    texture=dict(stimulus_type="synthetic_pattern",contrast=None,spatial_frequency=None,illumination=None,noise=None,
                 outlier_fraction=None,occlusion_fraction=None,field_states={})
    for key in ["contrast","illumination"]:
        texture["field_states"][key]=missing("conditions.texture_noise.value.field_states."+key,"需核验该图刺激的数值标定。",method)
    for key in ["spatial_frequency","noise","outlier_fraction","occlusion_fraction"]:
        texture["field_states"][key]=na("该图用人工点阵比较平移权重；此项并非装置设置的单一光栅频率、注入噪声、离群点或遮挡变量。",method)
    cond["texture_noise"]=condition(texture,method)
    for key in ["scale","scale_source_prior","scale_observability"]:
        cond[key]=dict(na("钙信号差值的比较不估计度量位移或场景尺度。",fig),value=None)
    cond["method_and_validation"]=condition(dict(assumptions=["以 ROI 为平均单位；同一只动物可贡献多个 ROI。"],
        validation_types=["imaging","controlled_experiment"],dataset_ids=[data_id],sample_count=6,trial_count=None,
        baseline_ids=[baseline_id],metric_ids=mids,failure_conditions=["人工复合光流；自由步行和自然场景的泛化尚未验证。"],
        field_states={"trial_count":state("not_reported","图注给出每蝇 5–10 次重复；源表记录 ROI 汇总，未给每 ROI 的确切次数。",fig)}),fig)
    ds=dict(dataset_id=data_id,name="Erginkaya et al. 2025, control bIPS, Figure 5h",version=review["spreadsheet_sha256"],
            data_kind="neural_recording",source_locator=sheet,sequence_ids=[],split_id=None,ground_truth_source=None,
            ground_truth_independence="not_applicable",field_states={k:na("实验响应比较没有训练划分或独立轨迹真值。",fig) for k in ("split_id","ground_truth_source")})
    base=dict(baseline_id=baseline_id,baseline_type="control_group",description="同一 bIPS 对照组的纯偏航（平移权重 0）。",
        dataset_id=data_id,condition_ids=[levels[0]["condition_id"]],metric_ids=[mids[0]],evidence_locator=[fig,sheet],field_states={})
    record=dict(assessment_id=aid,work_id="W-S06",work_key="Erginkaya2025",limitation_id="L04",claim_id="C-RUN09-S06-bIPS-direction-selectivity",
        claim_type="biological_mechanism",relation_type=["direct_study","counter_evidence"],handling_level="partially_addressed",
        evidence_level="fulltext_result",evidence_kind=["imaging","controlled_experiment"],evidence_route="biological_mechanism",conditions=cond,
        method=review["metric"],results="四个平移权重下的 ROI 均值依次为 9.47276、10.13533、1.29181 和 0.81776。源表给出纯偏航与最高权重 p=0.0040793。",
        baseline=base["description"],effect=review["interpretation"],dataset_records=[ds],baseline_records=[base],condition_levels=levels,
        metric_records=metrics,proof_record=None,evidence_admission_status="eligible",rejection_codes=[],
        claims_absolute_scale=condition(False,fig),scale_prior_details=[],measurement_model=None,state_variables=[],gauge_freedoms=[],
        observability_assumptions=[],degeneracy_conditions=[],excitation_requirements=[],external_measurement_sources=[],observability_argument_locator=[],
        remaining_limitations=review["boundaries"],counter_evidence=True,counter_evidence_types=["counterexample"],
        evidence_locator=[fig,method,sheet],provenance_upload_ids=[],provenance_version_ids=["V-S06-01"],assessment_status="active",
        superseded_by_assessment_id=None,cascade_event_id=None,discard_reason=None,fulltext_status="available_verified",verification_status="verified",
        citation_roles=[],project_relation="not_applicable",statement_basis="reviewer_inference",reviewer="Codex / RUN-0009",date=review["recorded_at_utc"][:10],
        biological_implications="同一细胞类型的偏航方向响应幅值依赖平移背景，限制了从纯旋转实验外推到混合刺激的范围。",
        engineering_implications="本实验未测里程计或轨迹精度。",field_states={})
    for k in ["species","motion_type","environment","scale"]:record[k]=deepcopy(cond[k])
    for k in ["proof_record","measurement_model"]:record["field_states"][k]=na("该条为有对照的钙成像结果。",fig)
    for k in ["superseded_by_assessment_id","cascade_event_id","discard_reason"]:record["field_states"][k]=na("活跃的初次登记记录。",fig)
    return record
