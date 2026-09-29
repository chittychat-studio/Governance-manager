CREATE TABLE customers (
  id SERIAL PRIMARY KEY,
  tenant_id INTEGER NOT NULL,
  email TEXT NOT NULL
);
