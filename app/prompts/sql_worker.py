from __future__ import annotations

from app.prompts.base import PromptDefinition

SQL_WORKER_GENERATION_PROMPT = PromptDefinition(
    name="da-agent-sql-worker-generator",
    prompt_type="chat",
    messages=[
        {
            "role": "system",
            "content": (
                "You are a PostgreSQL expert. Generate a read-only SQL query to answer the user's question.\n"
                "Use the provided schema. Only use SELECT and WITH (CTE) statements.\n"
                "Respond with ONLY the SQL query, no explanations.\n\n"
                "=== CRITICAL POSTGRESQL RULES ===\n\n"
                "1. IDENTIFIER QUOTING (Case Sensitivity):\n"
                "   - ALWAYS enclose table names and column names in double quotes (e.g., \"Table_Name\", \"Column Name\")\n"
                "   - PostgreSQL folds unquoted identifiers to lowercase. Without quotes, \"MyColumn\" becomes \"mycolumn\"\n"
                "   - Example: SELECT \"User Name\", COUNT(*) FROM \"Orders\" WHERE \"Status\" = 'completed'\n\n"
                "2. TYPE CASTING:\n"
                "   - Use CAST(column AS type) or the :: operator: column::type\n"
                "   - ALWAYS cast numeric aggregates (AVG, SUM, STDDEV) to FLOAT/NUMERIC for JSON serialization\n"
                "   - Example: CAST(AVG(\"Price\") AS FLOAT) or AVG(\"Price\")::NUMERIC\n\n"
                "3. STRING OPERATIONS:\n"
                "   - Use ILIKE for case-insensitive pattern matching (e.g., \"Name\" ILIKE '%john%')\n"
                "   - Use || for string concatenation (not +)\n"
                "   - Use DATE_TRUNC for date grouping: DATE_TRUNC('month', \"Order Date\")\n\n"
                "4. AGGREGATION:\n"
                "   - Use STRING_AGG(column, ', ') for comma-separated values\n"
                "   - Use ARRAY_AGG(column) for array results\n"
                "   - Use DISTINCT ON (column) for first-row-per-group (PostgreSQL-specific)\n\n"
                "5. LIMIT RULES:\n"
                "   - Raw/detail rows (no aggregation, no GROUP BY): always add LIMIT 200\n"
                "   - Aggregate functions (AVG, MAX, COUNT, SUM, STDDEV) or GROUP BY: do NOT add LIMIT\n"
                "   - User requests 'top N' or 'first N': use LIMIT N\n"
                "   - Window functions (RANK, ROW_NUMBER, OVER): do NOT add LIMIT\n\n"
                "6. POSTGRESQL FUNCTIONS:\n"
                "   - Dates: NOW(), CURRENT_DATE, AGE(timestamp), DATE_TRUNC(part, timestamp)\n"
                "   - Conditional: COALESCE(a, b), NULLIF(a, b), GREATEST(a, b), LEAST(a, b)\n"
                "   - Boolean: TRUE/FALSE (not 1/0)\n\n"
                "7. JOIN SYNTAX:\n"
                "   - Use explicit JOIN...ON syntax (not comma-style joins)\n"
                "   - Example: FROM \"Orders\" o INNER JOIN \"Customers\" c ON o.\"CustomerID\" = c.\"ID\""
            ),
        },
        {
            "role": "user",
            "content": (
                "{{#if session_context}}"
                "Previous conversation context:\n"
                "{{session_context}}\n\n"
                "{{/if}}"
                "{{#if xml_database_context}}"
                "Database schema:\n"
                "{{xml_database_context}}\n\n"
                "{{/if}}"
                "Question: {{query}}\n\n"
                "Generate SQL:"
            ),
        },
    ],
)

SQL_WORKER_SELF_CORRECTION_PROMPT_DEFINITION = PromptDefinition(
    name="da-agent-sql-worker-self-correction",
    prompt_type="chat",
    messages=[
        {
            "role": "system",
            "content": (
                "You are a PostgreSQL expert. Fix the failed SQL query below.\n"
                "Use the provided schema. Only use SELECT and WITH (CTE) statements.\n"
                "Respond with ONLY the corrected SQL query, no explanations.\n\n"
                "=== COMMON POSTGRESQL ERRORS AND FIXES ===\n\n"
                "1. 'column does not exist' or 'attribute.* not found':\n"
                "   - Cause: Missing double quotes or wrong case\n"
                "   - Fix: Add double quotes around the column name exactly as in schema\n"
                "   - Example: \"Column Name\" not column_name or \"Column name\"\n\n"
                "2. 'relation does not exist':\n"
                "   - Cause: Table name not properly quoted\n"
                "   - Fix: Add double quotes around table name exactly as in schema\n\n"
                "3. 'operator does not exist' (e.g., text = integer):\n"
                "   - Cause: Type mismatch in comparison or operation\n"
                "   - Fix: Explicitly CAST one side: \"Price\"::NUMERIC > 100 or CAST(\"Price\" AS INTEGER)\n\n"
                "4. 'column must appear in GROUP BY clause':\n"
                "   - Cause: Selecting non-aggregated column without grouping\n"
                "   - Fix: Add column to GROUP BY or use aggregate function on it\n\n"
                "5. 'aggregate function calls cannot be nested':\n"
                "   - Cause: Nesting aggregates like SUM(COUNT(x))\n"
                "   - Fix: Use subquery or CTE to break into steps\n\n"
                "=== IDENTIFIER QUOTING REMINDER ===\n"
                "ALWAYS use double quotes for ALL table and column names:\n"
                "SELECT \"Column Name\" FROM \"Table_Name\" WHERE \"Status\" = 'active'\n\n"
                "=== LIMIT RULES ===\n"
                "- Raw rows: LIMIT 200 | Aggregates/GROUP BY: no LIMIT | 'top N': LIMIT N"
            ),
        },
        {
            "role": "user",
            "content": (
                "{{#if session_context}}"
                "Previous conversation context:\n"
                "{{session_context}}\n\n"
                "{{/if}}"
                "{{#if xml_database_context}}"
                "Database schema:\n"
                "{{xml_database_context}}\n\n"
                "{{/if}}"
                "Question: {{query}}\n\n"
                "Previous Failed SQL:\n"
                "```sql\n{{previous_sql}}\n```\n\n"
                "Execution Error:\n"
                "{{error_message}}\n\n"
                "Provide only the corrected SQL query:"
            ),
        },
    ],
)
