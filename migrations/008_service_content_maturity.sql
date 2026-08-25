DROP TRIGGER validate_content_maturity_insert;
DROP TRIGGER validate_content_maturity_update;

CREATE TRIGGER validate_content_maturity_insert
BEFORE INSERT ON content_maturity_levels
WHEN NOT EXISTS (
    SELECT 1 FROM content_items
    WHERE id = NEW.content_item_id AND entry_type IN ('scenario', 'service')
)
BEGIN
    SELECT RAISE(ABORT, 'maturity level owner must be scenario or service content');
END;

CREATE TRIGGER validate_content_maturity_update
BEFORE UPDATE OF content_item_id ON content_maturity_levels
WHEN NOT EXISTS (
    SELECT 1 FROM content_items
    WHERE id = NEW.content_item_id AND entry_type IN ('scenario', 'service')
)
BEGIN
    SELECT RAISE(ABORT, 'maturity level owner must be scenario or service content');
END;

WITH service_maturity(service_code, maturity_code, sort_order) AS (
    VALUES
        ('foundation_workshop', 'explore', 0),
        ('knowledge_assistant_pilot', 'explore', 0),
        ('knowledge_assistant_pilot', 'pilot', 1),
        ('knowledge_assistant_pilot', 'scale', 2),
        ('customer_growth_pilot', 'explore', 0),
        ('customer_growth_pilot', 'pilot', 1),
        ('customer_growth_pilot', 'scale', 2),
        ('workflow_automation', 'explore', 0),
        ('workflow_automation', 'pilot', 1),
        ('workflow_automation', 'scale', 2),
        ('data_insight', 'pilot', 0),
        ('data_insight', 'scale', 1),
        ('data_insight', 'collaborate', 2),
        ('industry_integration', 'pilot', 0),
        ('industry_integration', 'scale', 1),
        ('industry_integration', 'collaborate', 2)
)
INSERT OR IGNORE INTO content_maturity_levels (
    content_item_id, maturity_code, sort_order
)
SELECT ci.id, mapping.maturity_code, mapping.sort_order
FROM service_maturity mapping
JOIN services service ON service.code = mapping.service_code
JOIN content_groups group_row ON group_row.service_id = service.id
    AND group_row.entry_type = 'service'
JOIN content_items ci ON ci.content_group_id = group_row.id
    AND ci.entry_type = 'service'
    AND ci.status = 'draft';
