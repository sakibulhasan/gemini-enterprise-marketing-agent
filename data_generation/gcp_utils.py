"""
gcp_utils.py
============

Shared Google Cloud helper functions used by every pipeline.

This module isolates ALL direct interaction with the GCP SDKs so the individual
pipelines can focus purely on *generating data*. It provides:

- Lazily-created, reusable BigQuery and Cloud Storage clients.
- A helper to create the BigQuery dataset if it does not already exist.
- A generic "load a DataFrame into a BigQuery table" helper with an explicit
  schema (so column types are never guessed/inferred incorrectly).
- A helper to read the contractors table back out of BigQuery, which lets the
  job-ledger and ad-recommendation pipelines run standalone (they depend on
  contractor data that the contractors pipeline produces).
"""

import pandas as pd
from google.cloud import bigquery, storage
from google.api_core.exceptions import NotFound

import config

logger = config.get_logger(__name__)

# Module-level client singletons. Creating a GCP client opens auth/transport
# machinery, so we build each one once and reuse it.
_bq_client: bigquery.Client | None = None
_storage_client: storage.Client | None = None


def get_bq_client() -> bigquery.Client:
    """Return a cached BigQuery client bound to the configured project."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=config.PROJECT_ID)
    return _bq_client


def get_storage_client() -> storage.Client:
    """Return a cached Cloud Storage client bound to the configured project."""
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client(project=config.PROJECT_ID)
    return _storage_client


def create_bq_dataset_if_not_exists() -> None:
    """Ensure the destination BigQuery dataset exists (idempotent).

    BigQuery load jobs fail if the parent dataset is missing, so we create it
    up-front. Running this repeatedly is safe: if the dataset already exists we
    simply log and return.
    """
    client = get_bq_client()
    dataset_ref = bigquery.DatasetReference(config.PROJECT_ID, config.BQ_DATASET_NAME)
    try:
        client.get_dataset(dataset_ref)
        logger.info("Dataset '%s' already exists.", config.BQ_DATASET_NAME)
    except NotFound:
        logger.info("Dataset '%s' not found. Creating...", config.BQ_DATASET_NAME)
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"
        client.create_dataset(dataset)
        logger.info("Dataset '%s' created.", config.BQ_DATASET_NAME)


def load_dataframe_to_bq(
    df: pd.DataFrame,
    table_name: str,
    schema: list[bigquery.SchemaField],
) -> None:
    """Load a pandas DataFrame into a BigQuery table using an explicit schema.

    Parameters
    ----------
    df :
        The data to upload.
    table_name :
        Short table name (the dataset/project prefix is added automatically).
    schema :
        Explicit BigQuery column definitions. Passing the schema (rather than
        relying on autodetect) guarantees correct types — e.g. DATE columns stay
        DATE and integers do not become floats.

    The write disposition is WRITE_TRUNCATE so re-running a pipeline cleanly
    replaces the table contents instead of appending duplicates.
    """
    client = get_bq_client()
    table_id = f"{config.PROJECT_ID}.{config.BQ_DATASET_NAME}.{table_name}"

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition="WRITE_TRUNCATE",
    )

    logger.info("Loading %d rows into BigQuery table '%s'...", len(df), table_id)
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()  # Block until the load job finishes (or raise on failure).
    logger.info("Loaded %d rows into '%s'.", job.output_rows, table_name)


def fetch_contractors_from_bq() -> pd.DataFrame:
    """Read the contractors_master table back from BigQuery into a DataFrame.

    This lets the job-ledger and ad-recommendation pipelines be executed on
    their own (after the contractors pipeline has run at least once) without
    re-generating contractor identities.
    """
    client = get_bq_client()
    table_id = f"{config.PROJECT_ID}.{config.BQ_DATASET_NAME}.contractors_master"
    logger.info("Fetching contractors from '%s'...", table_id)
    return client.query(f"SELECT * FROM `{table_id}`").to_dataframe()
