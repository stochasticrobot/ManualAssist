# Document Search

Make saved manual text searchable and use it to answer reader questions.

Search results keep their source references so answers and related guide links can
lead readers back to the manual instead of relying on unsupported AI memory.

## Files

| File | What it does |
| --- | --- |
| [answer_from_retrieved_passages.py](answer_from_retrieved_passages.py) | Answer a reader's question using relevant passages found in the saved manual. |
| [find_related_result_guides.py](find_related_result_guides.py) | Find saved guides that may help with a reader's question. |
| [index_and_search_parsed_text.py](index_and_search_parsed_text.py) | Store manual passages in a local search collection and find text relevant to questions. |
| [join_continuing_source_fragments.py](join_continuing_source_fragments.py) | Keep sentences split by PDF extraction understandable when they are searched. |
| [retain_original_column_context.py](retain_original_column_context.py) | Recover the missing beginning or end of a sentence split between page columns. |
