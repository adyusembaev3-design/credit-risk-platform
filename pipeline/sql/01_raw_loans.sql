-- Stage 1: load the Lending Club file exactly as delivered.
-- Every column is read as text so one malformed value cannot break the load;
-- typing happens in stage 2 with TRY_CAST, where bad values become NULL.
CREATE OR REPLACE TABLE raw_loans AS
SELECT *
FROM read_csv(
    '__RAW_PATH__',
    header = true,
    all_varchar = true,
    ignore_errors = true
);
