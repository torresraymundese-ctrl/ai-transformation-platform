CREATE TABLE scenario_public_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL,
    input_text TEXT NOT NULL CHECK(length(trim(input_text)) BETWEEN 1 AND 300),
    sort_order INTEGER NOT NULL CHECK(sort_order >= 0),
    UNIQUE(content_item_id, sort_order),
    FOREIGN KEY (content_item_id) REFERENCES content_items(id)
);

CREATE INDEX scenario_public_inputs_revision_order
ON scenario_public_inputs(content_item_id, sort_order, id);

CREATE TRIGGER protect_scenario_public_inputs_insert
BEFORE INSERT ON scenario_public_inputs
WHEN EXISTS (SELECT 1 FROM content_items WHERE id=NEW.content_item_id AND status <> 'draft')
BEGIN SELECT RAISE(ABORT, 'non-draft scenario inputs are immutable'); END;

CREATE TRIGGER protect_scenario_public_inputs_update
BEFORE UPDATE ON scenario_public_inputs
WHEN EXISTS (SELECT 1 FROM content_items WHERE id IN (OLD.content_item_id, NEW.content_item_id) AND status <> 'draft')
BEGIN SELECT RAISE(ABORT, 'non-draft scenario inputs are immutable'); END;

CREATE TRIGGER protect_scenario_public_inputs_delete
BEFORE DELETE ON scenario_public_inputs
WHEN EXISTS (SELECT 1 FROM content_items WHERE id=OLD.content_item_id AND status <> 'draft')
BEGIN SELECT RAISE(ABORT, 'non-draft scenario inputs are immutable'); END;
