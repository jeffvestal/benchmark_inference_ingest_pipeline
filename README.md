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

## json partial example
```
{'16x1': {'allocations': 16,
          'nodesReport': {'instance-0000000025': 
                    {'average_inference_time_ms_last_minute': {'max': 301.1378683157512,
                                                               'median': 301.11121703209403,
                                                               'min': 299.6329194524037},
                                                  'throughput_last_minute': {'max': 3147,
                                                                             'median': 3141.0,
                                                                             'min': 2749}}},
          'running_time_in_nanos': 190735480466,
          'threads per allocation': 1},
 '1x1': {'allocations': 1,
         'nodesReport': {'instance-0000000025': 
                    {'average_inference_time_ms_last_minute': {'max': 166.53015873015872,
                                                               'median': 163.46049046321525,
                                                                'min': 159.54521276595744},
                                                 'throughput_last_minute': {'max': 376,
                                                                            'median': 367.0,
                                                                            'min': 315}}},
                                                                            
```

## csv partial example
```
key,elapsed time (sec),allocations,threads per allocation,instance name,min( average_inference_time_ms_last_minute ),median( average_inference_time_ms_last_minute ),max( average_inference_time_ms_last_minute ),min( throughput_last_minute ),median( throughput_last_minute ),max( throughput_last_minute )
8x1,213.44,8,1,instance-0000000025,166.63,166.84,174.94,2496.00,2714.00,2845.00
16x1,193.43,16,1,instance-0000000025,304.61,304.80,306.12,2719.00,3094.00,3111.00
```

# Running
Currently most of the configurations options are hardcoded in the script (I have an issue open to move them to a config file). 
Elasticsearch connection info is set in environment variables. 

## Env Variables
- `es_cloud_id` : cloud id for ESS deployment
- `es_cloud_user` : username with access to create indices and start/stop Trained ML Models
- `es_cloud_pass` : password for above user

## Variables in the script
List of variables you may need to change to match your data:
- `allocation_threadsPer` - pairs of allocation and threads per allocation to test
- `sourceIndex` - source index in elastic to use for `_reindex` through the pipeline
- `pipelineName` - ingest pipeline name
- `modelID` - Trained ML model used in the ingest pipeline's inference processor

## Setup
1. Before running the first time, you need to have a source index that has not been previously run through the ingest pipeline. This source index will be used with `_reindex` for each run
2. It is best to test with 1 ML node to test throuhput, then you can scale out from there. Ideally this will be a "full sized" node (in ESS that would be either 64 or 60 GB RAM)
3. It is also ideal to not have other ML models started simply to fully max out a single node


## Starting
1. Set required environment variables
2. run ./main.py