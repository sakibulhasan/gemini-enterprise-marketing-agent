"""
run_pipeline.py
===============

Orchestrator — runs all four pipelines end-to-end in the correct order.

Execution order matters because of data dependencies:

    1. contractors_pipeline       -> produces the contractor roster (must be first)
    2. job_ledger_pipeline        -> needs contractor capacity
    3. weather_pipeline           -> independent reference data
    4. ad_recommendations_pipeline-> needs contractor identities (-> GCS)

The contractor DataFrame produced in step 1 is passed directly into steps 2 and
4, avoiding an unnecessary read-back from BigQuery.

Run everything:
    python run_pipeline.py

Run a single pipeline standalone (after contractors_master exists):
    python contractors_pipeline.py
    python job_ledger_pipeline.py
    python weather_pipeline.py
    python ad_recommendations_pipeline.py
"""

import config
import gcp_utils
import contractors_pipeline
import job_ledger_pipeline
import weather_pipeline
import ad_recommendations_pipeline

logger = config.get_logger("run_pipeline")


def main() -> None:
    logger.info("=" * 60)
    logger.info("Capacity-Aware Ad Budget Optimizer POC — pipeline START")
    logger.info("Project=%s  Dataset=%s  Bucket=%s",
                config.PROJECT_ID, config.BQ_DATASET_NAME, config.GCS_BUCKET_NAME)
    logger.info("=" * 60)

    # Make sure the destination dataset exists before any BigQuery load runs.
    gcp_utils.create_bq_dataset_if_not_exists()

    # 1. Contractors (foundational) — keep the DataFrame to feed dependents.
    contractors_df = contractors_pipeline.run()

    # 2. Job ledger — depends on contractor capacity.
    job_ledger_pipeline.run(contractors_df)

    # 3. Weather demand factors — independent reference table.
    weather_pipeline.run()

    # 4. Ad recommendations -> GCS — depends on contractor identities.
    ad_recommendations_pipeline.run(contractors_df)

    logger.info("=" * 60)
    logger.info("Pipeline COMPLETED SUCCESSFULLY")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
