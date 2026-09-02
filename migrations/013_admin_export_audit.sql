CREATE TABLE admin_export_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT NOT NULL,
  filter_json TEXT NOT NULL,
  row_count INTEGER NOT NULL CHECK(row_count BETWEEN 0 AND 10000),
  created_at TEXT NOT NULL
);
