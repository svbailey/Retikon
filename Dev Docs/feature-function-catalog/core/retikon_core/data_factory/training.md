# retikon_core/data_factory/training.py

Edition: Core

## Functions
- `training_jobs_uri`: Function that builds the training job registry URI, so the system works as expected.
- `load_training_jobs`: Function that loads training jobs from storage, so the system works as expected.
- `save_training_jobs`: Function that saves training jobs to storage, so the system works as expected.
- `create_training_job`: Function that creates a training job object, so the system works as expected.
- `register_training_job`: Function that persists a new training job, so the system works as expected.
- `update_training_job`: Function that updates an existing training job, so the system works as expected.
- `get_training_job`: Function that loads a training job by id, so the system works as expected.
- `list_training_jobs`: Function that lists training jobs, so the system works as expected.
- `mark_training_job_running`: Function that marks a job running, so the system works as expected.
- `mark_training_job_completed`: Function that marks a job completed, so the system works as expected.
- `mark_training_job_failed`: Function that marks a job failed, so the system works as expected.
- `mark_training_job_canceled`: Function that marks a job canceled, so the system works as expected.
- `execute_training_job`: Function that runs a job via a training executor, so the system works as expected.
- `enqueue_training_job`: Function that publishes a job to a queue, so the system works as expected.
- `_normalize_labels`: Internal helper that cleans up labels, so the system works as expected.

## Classes
- `TrainingSpec`: Data structure or helper class for Training Spec, so the system works as expected.
- `TrainingJob`: Data structure or helper class for Training Job, so the system works as expected.
- `TrainingResult`: Data structure or helper class for Training Result, so the system works as expected.
- `TrainingExecutor`: Data structure or helper class for Training Executor, so the system works as expected.
