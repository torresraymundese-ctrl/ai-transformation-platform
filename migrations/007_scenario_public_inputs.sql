CREATE TABLE scenario_public_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL,
    input_text TEXT NOT NULL CHECK(
        typeof(input_text)='text'
        AND instr(input_text,char(0))=0
        AND length(input_text) BETWEEN 1 AND 300
        AND length(trim(input_text,
            char(9)||char(10)||char(11)||char(12)||char(13)||
            char(28)||char(29)||char(30)||char(31)||char(32)||
            char(133)||char(160)||char(5760)||
            char(8192)||char(8193)||char(8194)||char(8195)||char(8196)||
            char(8197)||char(8198)||char(8199)||char(8200)||char(8201)||
            char(8202)||char(8232)||char(8233)||char(8239)||char(8287)||char(12288)
        )) >= 1
    ),
    sort_order INTEGER NOT NULL CHECK(typeof(sort_order)='integer' AND sort_order >= 1),
    UNIQUE(content_item_id, sort_order),
    FOREIGN KEY (content_item_id) REFERENCES content_items(id)
);

CREATE INDEX scenario_public_inputs_revision_order
ON scenario_public_inputs(content_item_id, sort_order, id);

WITH reviewed_inputs(code,input_text,sort_order) AS (
    VALUES
        ('mfg_knowledge_assistant','设备与工艺知识文档的受控副本',1),
        ('mfg_knowledge_assistant','近三个月高频现场问题清单',2),
        ('mfg_quality_inspection','已标注的质检样本及缺陷分类规则',1),
        ('mfg_quality_inspection','现场设备图像采集条件说明',2),
        ('mfg_operations_reporting','已确认的生产经营数据字段清单',1),
        ('mfg_operations_reporting','当前报表模板和使用频率',2),
        ('retail_ai_service','已审核的商品与服务知识资料',1),
        ('retail_ai_service','近期客户咨询主题汇总',2),
        ('retail_marketing_content','已审批的活动素材及品牌规范',1),
        ('retail_marketing_content','活动目标与已有渠道数据',2),
        ('retail_inventory_insight','库存、销售和补货记录字段说明',1),
        ('retail_inventory_insight','商品主数据与门店范围',2),
        ('pro_document_knowledge','受控专业文档及其版本信息',1),
        ('pro_document_knowledge','用户问题与检索范围说明',2),
        ('pro_delivery_drafting','项目交付文档模板',1),
        ('pro_delivery_drafting','已确认的项目里程碑信息',2),
        ('pro_contract_review','待审合同文本及适用规则',1),
        ('pro_contract_review','审查范围与输出格式要求',2),
        ('creative_content_workflow','已审批的内容素材和风格规范',1),
        ('creative_content_workflow','发布渠道与内容计划',2),
        ('software_support_knowledge','产品知识库受控副本',1),
        ('software_support_knowledge','近期支持工单主题',2),
        ('project_delivery_automation','当前项目流程和字段清单',1),
        ('project_delivery_automation','已有任务与状态数据',2),
        ('data_process_foundation','现有数据源目录',1),
        ('data_process_foundation','数据责任人与更新频率',2)
)
INSERT INTO scenario_public_inputs(content_item_id,input_text,sort_order)
SELECT ci.id, reviewed_inputs.input_text, reviewed_inputs.sort_order
FROM reviewed_inputs
JOIN scenarios s ON s.code=reviewed_inputs.code
JOIN content_groups g ON g.scenario_id=s.id AND g.entry_type='scenario'
JOIN content_items ci ON ci.content_group_id=g.id AND ci.entry_type='scenario'
WHERE NOT EXISTS (
    SELECT 1 FROM scenario_public_inputs existing
    WHERE existing.content_item_id=ci.id
);

CREATE TRIGGER protect_scenario_public_inputs_insert
BEFORE INSERT ON scenario_public_inputs
WHEN NOT EXISTS (
    SELECT 1 FROM content_items
    WHERE id=NEW.content_item_id AND entry_type='scenario' AND status='draft'
)
BEGIN SELECT RAISE(ABORT, 'scenario inputs require a draft scenario revision'); END;

CREATE TRIGGER protect_scenario_public_inputs_update
BEFORE UPDATE ON scenario_public_inputs
WHEN NOT EXISTS (
    SELECT 1 FROM content_items
    WHERE id=OLD.content_item_id AND entry_type='scenario' AND status='draft'
) OR NOT EXISTS (
    SELECT 1 FROM content_items
    WHERE id=NEW.content_item_id AND entry_type='scenario' AND status='draft'
)
BEGIN SELECT RAISE(ABORT, 'scenario inputs require a draft scenario revision'); END;

CREATE TRIGGER protect_scenario_public_inputs_delete
BEFORE DELETE ON scenario_public_inputs
WHEN NOT EXISTS (
    SELECT 1 FROM content_items
    WHERE id=OLD.content_item_id AND entry_type='scenario' AND status='draft'
)
BEGIN SELECT RAISE(ABORT, 'scenario inputs require a draft scenario revision'); END;
