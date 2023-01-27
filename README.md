# Benchmarking ingest pipeline with an inference process 
This script will kick off a _reindex of an existing index into a new index. This is to remove external latency possibilities and focus on inference time. 

Different allocation and threads per allocation combinations are used for each loop, restarting the supervised model each time. 

## Various metrics are collected including:
- average_inference_time_ms_last_minute
- throughput_last_minute

For each of those metrics several calulations are done:
- min
- median
- max

both metrics and functions can be changed

# output
results are written to separate .csv and .json file formats