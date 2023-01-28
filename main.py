'''
test inference processor pipeline using _reindex
and different allocation and threads per allocations settings
'''

from elasticsearch import Elasticsearch
from elasticsearch.client import MlClient
import os
import sys
import time
import json
from datetime import datetime
from statistics import median, StatisticsError



def esConnect(cid, user, passwd):
    '''Connect to Elastic Cloud cluster'''

    #TODO switch to API key?
    es = Elasticsearch(cloud_id=cid, http_auth=(user, passwd))

    return es


def update_model_settings(es, model_id, at, cache='0b', retry_count=0):
    '''update the model allocation and threads per allocation'''

    # Don't have to stop when only updating allocation but its quick enough to do it everytime for now
    stop = MlClient.stop_trained_model_deployment(es,
                                                  model_id=model_id,
                                                  force=True)

    try:
        start = MlClient.start_trained_model_deployment(
            es,
            model_id=model_id,
            cache_size=cache,
            number_of_allocations=at[0],
            threads_per_allocation=at[1],
            wait_for='started',
            timeout='10m')
    #except elastic_transport.ConnectionTimeout:
    except:
        if retry_count < 2:
            update_model_settings(es, model_id, at, cache, retry_count=1)
        else:
            raise

    return


def create_new_index(es, index_name):
    '''
    Create the new index before reindex is started
    '''

    index_settings = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 1
        }
    }

    # may want to set the mapping

    response = es.indices.create(index=index_name, body=index_settings)
    if not response['acknowledged']:
        response_content = response.json()
        sys.exit()
    else:
        return


def start_reindex(es, source, destination, pipe):
    '''
    kick off _reindex after 60 second pause
    This is to allow the _last_minute metrics to 0 out
    '''

    time.sleep(60)

    request_body = {
        "source": {
            "index": source
        },
        "dest": {
            "index": destination,
            "pipeline": pipe
        }
    }

    # Execute the reindex operation
    response = es.reindex(body=request_body,
                          wait_for_completion=False,
                          max_docs=10000)

    return response


def mmm(nodesReport, funcs):
    '''return min median max removing 0s'''

    for node in nodesReport:
        for met in nodesReport[node]:
            tmpCalcs = {}
            metList = nodesReport[node][met]
            # removing 0's since we are concerned about metrics while processing, not general running stats
            metList = [x for x in metList if x != 0]
            
            for func in funcs:
                try:
                    tmpCalcs[func] = funcs[func](metList)
                except (ValueError, StatisticsError):
                    # Report False if there were no stats or non-zero stats collected
                    tmpCalcs[func] = False
            nodesReport[node][met] = tmpCalcs

    return (nodesReport)


## nodes = {'abc': {'i' : [222, ] , } }
def get_trained_models_stats(es, model, metrics, nodesReport):
    ''' 
    call _stats to get average_inference_time_ms_last_minute` and `throughput_last_minute`
    This pulls the max accross all nodes
    TODO track max per node
    '''

    newset = {m: [] for m in metrics}

    response = MlClient.get_trained_models_stats(es, model_id=model)
    for stats in response['trained_model_stats']:
        for node_data in stats['deployment_stats']['nodes']:
            print(node_data)
            # there is only one node inside deployment_stat.nodes.0.node
            node_name = node_data['node'][list(node_data['node'].keys())[0]]['name']

            tmpNodeStats = nodesReport.setdefault(node_name, newset)

            # append the current metric value on to the existing list
            for m in metrics:
                try:
                    tmpNodeStats[m].append(node_data[m])
                except KeyError:
                    pass

            nodesReport[node_name] = tmpNodeStats

    return (nodesReport)


def wait_until_ingest_complete(es, response, model, metrics, funcs,  wait=5):
    '''
    poll every 'wait' seconds, return when reindex thread is complete
    default wait = 10 seconds

    Also poll _ml/trained_models/_stats to get `average_inference_time_ms_last_minute` and `throughput_last_minute`
    '''

    inference, throughput = [], []
    nodesReport = {}

    while True:
        task_info = es.tasks.get(task_id=response['task'])
        if task_info['completed']:
            nodesReport = get_trained_models_stats(es, model, metrics, nodesReport)
            break
        else:
            nodesReport = get_trained_models_stats(es, model, metrics, nodesReport)
            time.sleep(wait)

    nodesReport = mmm(nodesReport, funcs)

    return (task_info['task']['running_time_in_nanos'], nodesReport)


if __name__ == '__main__':

    results = 'pipeline-results__' + str(datetime.now())
    resultsCollector = {}
    
    # setup elastic cloud connection
    es_cloud_id = os.environ['es_cloud_id']
    es_cloud_user = os.environ['es_cloud_user']
    es_cloud_pass = os.environ['es_cloud_pass']

    # metrics to collect from ml stats
    metrics = [
        'average_inference_time_ms_last_minute', 
        'throughput_last_minute'
    ]

    # math functions for reportin
    funcs = {'min': min, 
        'median' : median,
        'max' : max
        }

    # set the test pairs of allocations and threads per allocation on the supervised model
    allocation_threadsPer = [
        [1,1],
        [4,1],
        [1,8],
        [8, 1],
        [1,4],
        [2,8],
        [4,4],
        [16, 1]
    ]

    # set source index name
    sourceIndex = 'pii_test-no_redaction'

    # set the base name of the test index set - reindexName__pipelineName__runTS__AxT
    reindexName = 'pii_test_v2'
    runTS = datetime.now().strftime('%Y%m%d_%H%M%S')

    # set the ingest pipeline to use
    pipelineName = 'pii_script-redact-throuput_test_01'

    # set the name of the supervised model_id used in the pipeline
    # TODO could be smarter and get this from the pipeline config automatically
    modelID = 'dslim__bert-base-ner'

    #############
    # create elastic connection
    # TODO switch to apikey
    es = esConnect(es_cloud_id, es_cloud_user, es_cloud_pass)

    # Make go now
    for at in allocation_threadsPer:
        configString = 'x'.join(map(str, at))

        # create new index name
        indexName = '__'.join([reindexName, pipelineName, runTS, configString])

        # create new index
        create_new_index(es, indexName)

        # update supervised model with this round's settings
        update_model_settings(es, modelID, at)

        # kickoff _reindex
        reindexResponse = start_reindex(es, sourceIndex, indexName,
                                        pipelineName)

        # wait for _reindex to complete
        elapsed_time, nodesReport = wait_until_ingest_complete(
            es, reindexResponse, modelID, metrics, funcs)
        
        resultsCollector[configString] = {'running_time_in_nanos' : elapsed_time, 
                                          'nodesReport' : nodesReport,
                                          'allocations' : at[0],
                                          'threads per allocation' : at[1],
                                          'elapsed time seconds' : elapsed_time / 1000000000
                                         }

    
    print('Done with configuration options')
    print(resultsCollector)

    # Create csv output
    resultsStr = ''
    header = ['key', 'elapsed time (sec)', 'allocations', 'threads per allocation', 'instance name']
    funcKeys=tuple(funcs.keys())

    for met in metrics:
        for func in funcKeys:
            header.append(func + '( ' + met + ' )')
    header = ','.join(header)
    header += '\n'
        

    for key in resultsCollector:
        resultsStr += key
        resultsStr += ',%.2f' % resultsCollector[key]['elapsed time seconds'] 
        resultsStr += ',' + str(resultsCollector[key]['allocations'])
        resultsStr += ',' + str(resultsCollector[key]['threads per allocation'])
        
        for nodeName in resultsCollector[key]['nodesReport']:
            resultsStr += ',' + nodeName

            for met in metrics:
                for func in funcs:
                    resultsStr += ',' + '%.2f' %resultsCollector[key]['nodesReport'][nodeName][met][func]

        resultsStr += '\n'


    dir = 'results'
    os.makedirs(dir, exist_ok=True)
    
    file_path = os.path.join(dir, results + '.csv',)    
    with open(file_path, "w") as c_file:
        c_file.writelines(header)
        c_file.writelines(resultsStr)

    file_path = os.path.join(dir, results + '.json',)
    with open(file_path, "w") as j_file:
        json.dump(resultsCollector, j_file)


    print('Done')

