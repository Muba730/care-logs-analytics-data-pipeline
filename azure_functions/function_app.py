import json
import logging
import os

import azure.functions as func
import mssql_python

from database import get_latest_pipeline_run_key
from gold_loader import load_gold_tables
from silver_loader import (
    load_bronze_to_log_event,
    load_log_event_to_silver_tables,
)


app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def json_response(payload: dict, status_code: int) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(payload, default=str),
        status_code=status_code,
        mimetype="application/json",
    )


@app.function_name(name="LoadBronzeToSilverLogEvent")
@app.route(
    route="load-bronze-to-silver-log-event",
    methods=["POST"],
)
def load_bronze_to_silver_log_event(
    req: func.HttpRequest,
) -> func.HttpResponse:
    try:
        request_body = req.get_json()
    except ValueError:
        return json_response(
            {
                "status": "Failed",
                "message": "Request body must be valid JSON.",
            },
            400,
        )

    source_file = str(request_body.get("source_file", "")).strip()

    if not source_file:
        return json_response(
            {
                "status": "Failed",
                "message": "source_file is required.",
            },
            400,
        )

    connection_string = os.getenv("SQL_CONNECTION_STRING")

    if not connection_string:
        logging.error("SQL_CONNECTION_STRING is not configured.")

        return json_response(
            {
                "status": "Failed",
                "message": "Database configuration is missing.",
            },
            500,
        )

    connection = None

    try:
        connection = mssql_python.connect(
            connection_string,
            timeout=60,
        )

        pipeline_run_key = get_latest_pipeline_run_key(
            connection,
            source_file,
        )

        if pipeline_run_key is None:
            return json_response(
                {
                    "status": "Failed",
                    "source_file": source_file,
                    "message": (
                        "No audit.pipeline_run record exists for this file."
                    ),
                },
                409,
            )

        silver_result = load_bronze_to_log_event(
            connection=connection,
            source_file=source_file,
            pipeline_run_key=pipeline_run_key,
        )

        response_status = (
            "SucceededWithIssues"
            if silver_result["rows_rejected"] > 0
            else "Succeeded"
        )

        return json_response(
            {
                **silver_result,
                "status": response_status,
                "pipeline_run_key": pipeline_run_key,
            },
            200,
        )

    except Exception:
        logging.exception(
            "Bronze-to-silver.log_event processing failed for %s",
            source_file,
        )

        return json_response(
            {
                "status": "Failed",
                "source_file": source_file,
                "message": "Processing failed. Check the Function logs.",
            },
            500,
        )

    finally:
        if connection is not None:
            connection.close()


@app.function_name(name="LoadSilverLogEventToSilverTables")
@app.route(
    route="load-silver-log-event-to-silver-tables",
    methods=["POST"],
)
def load_silver_log_event_to_silver_tables(
    req: func.HttpRequest,
) -> func.HttpResponse:
    try:
        request_body = req.get_json()
    except ValueError:
        return json_response(
            {
                "status": "Failed",
                "message": "Request body must be valid JSON.",
            },
            400,
        )

    source_file = str(request_body.get("source_file", "")).strip()

    if not source_file:
        return json_response(
            {
                "status": "Failed",
                "message": "source_file is required.",
            },
            400,
        )

    connection_string = os.getenv("SQL_CONNECTION_STRING")

    if not connection_string:
        logging.error("SQL_CONNECTION_STRING is not configured.")

        return json_response(
            {
                "status": "Failed",
                "message": "Database configuration is missing.",
            },
            500,
        )

    connection = None

    try:
        connection = mssql_python.connect(
            connection_string,
            timeout=60,
        )

        pipeline_run_key = get_latest_pipeline_run_key(
            connection,
            source_file,
        )

        if pipeline_run_key is None:
            return json_response(
                {
                    "status": "Failed",
                    "source_file": source_file,
                    "message": (
                        "No audit.pipeline_run record exists for this file."
                    ),
                },
                409,
            )

        silver_result = load_log_event_to_silver_tables(
            connection=connection,
            source_file=source_file,
        )

        return json_response(
            {
                **silver_result,
                "pipeline_run_key": pipeline_run_key,
            },
            200,
        )

    except Exception:
        logging.exception(
            "silver.log_event-to-Silver-tables processing failed for %s",
            source_file,
        )

        return json_response(
            {
                "status": "Failed",
                "source_file": source_file,
                "message": "Processing failed. Check the Function logs.",
            },
            500,
        )

    finally:
        if connection is not None:
            connection.close()


@app.function_name(name="LoadSilverTablesToGold")
@app.route(
    route="load-silver-tables-to-gold",
    methods=["POST"],
)
def load_silver_tables_to_gold(req: func.HttpRequest) -> func.HttpResponse:
    try:
        request_body = req.get_json()
    except ValueError:
        return json_response(
            {
                "status": "Failed",
                "message": "Request body must be valid JSON.",
            },
            400,
        )

    source_file = str(request_body.get("source_file", "")).strip()

    if not source_file:
        return json_response(
            {
                "status": "Failed",
                "message": "source_file is required.",
            },
            400,
        )

    connection_string = os.getenv("SQL_CONNECTION_STRING")

    if not connection_string:
        logging.error("SQL_CONNECTION_STRING is not configured.")

        return json_response(
            {
                "status": "Failed",
                "message": "Database configuration is missing.",
            },
            500,
        )

    connection = None

    try:
        connection = mssql_python.connect(
            connection_string,
            timeout=60,
        )

        pipeline_run_key = get_latest_pipeline_run_key(
            connection,
            source_file,
        )

        if pipeline_run_key is None:
            return json_response(
                {
                    "status": "Failed",
                    "source_file": source_file,
                    "message": (
                        "No audit.pipeline_run record exists for this file."
                    ),
                },
                409,
            )

        gold_result = load_gold_tables(
            connection=connection,
            source_file=source_file,
        )

        return json_response(
            {
                **gold_result,
                "pipeline_run_key": pipeline_run_key,
            },
            200,
        )

    except Exception:
        logging.exception(
            "Silver-to-Gold processing failed for %s",
            source_file,
        )

        return json_response(
            {
                "status": "Failed",
                "source_file": source_file,
                "message": "Processing failed. Check the Function logs.",
            },
            500,
        )

    finally:
        if connection is not None:
            connection.close()
