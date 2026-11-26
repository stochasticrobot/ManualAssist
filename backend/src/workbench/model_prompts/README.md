# Model Prompts

Keep the written instructions sent to AI models in one identifiable part of the
project.

These files describe the tasks and evidence rules the models must follow. They
prepare request text; they do not send requests themselves.

## Files

| File | What it does |
| --- | --- |
| [analysis_task_prompts.py](analysis_task_prompts.py) | Write the instructions used when asking AI to extract facts, find uncertainties or make aids. |
| [shared_model_instructions.py](shared_model_instructions.py) | Store the common rules the AI receives when working with manual evidence. |
