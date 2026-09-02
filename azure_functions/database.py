def get_latest_pipeline_run_key(connection, source_file):
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT TOP (1)
                pipeline_run_key
            FROM audit.pipeline_run
            WHERE source_file = ?
            ORDER BY pipeline_run_key DESC;
            """,
            (source_file,),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else None
    finally:
        cursor.close()
