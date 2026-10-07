import mssql_python
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool


def create_sqlalchemy_engine(connection_string):
    """Use the existing SQL_CONNECTION_STRING and Microsoft Python driver."""
    return create_engine(
        "mssql+mssqlpython://",
        creator=lambda: mssql_python.connect(connection_string, timeout=60),
        poolclass=NullPool,
        use_insertmanyvalues=False,
    )


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
