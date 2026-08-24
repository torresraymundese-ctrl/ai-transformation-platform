CREATE TABLE scenario_public_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id INTEGER NOT NULL,
    input_text TEXT NOT NULL CHECK(length(trim(input_text)) BETWEEN 1 AND 300),
    status TEXT NOT NULL CHECK(status IN ('draft', 'published', 'archived')),
    sort_order INTEGER NOT NULL CHECK(sort_order >= 0),
    UNIQUE(scenario_id, sort_order),
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id)
);
