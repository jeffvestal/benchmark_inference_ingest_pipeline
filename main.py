'''
test inference processor pipeline using _reindex
and different allocation and threads per allocations settings
'''

from elasticsearch import Elasticsearch, helpers
from elasticsearch.client import MlClient
import os
import time
from datetime import datetime


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

    #print(index_name)

    response = es.indices.create(index=index_name, body=index_settings)
    if not response['acknowledged']:
        response_content = response.json()
        #print(response_content)
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


def get_inference_throughput(es, model):
    ''' 
    call _stats to get average_inference_time_ms_last_minute` and `throughput_last_minute`
    This pulls the max accross all nodes
    TODO track max per node
    '''

    i, t = [], []
    response = MlClient.get_trained_models_stats(es, model_id=model)
    #print(response)
    for m in response['trained_model_stats']:
        for n in m['deployment_stats']['nodes']:
            try:
                i.append(n['average_inference_time_ms_last_minute'])
            except KeyError:
                i.append(0)
            try:
                t.append(n['throughput_last_minute'])
            except KeyError:
                t.append(0)

    return (max(i), max(t))


def wait_until_ingest_complete(es, response, model, wait=5):
    '''
    poll every 'wait' seconds, return when reindex thread is complete
    default wait = 10 seconds

    Also poll _ml/trained_models/_stats to get `average_inference_time_ms_last_minute` and `throughput_last_minute`
    '''

    inference, throughput = [], []

    while True:
        task_info = es.tasks.get(task_id=response['task'])
        if task_info['completed']:
            it = get_inference_throughput(es, model)
            inference.append(it[0])
            throughput.append(it[1])
            break
        else:
            it = get_inference_throughput(es, model)
            inference.append(it[0])
            throughput.append(it[1])
            time.sleep(wait)

    inference, throughput = max(inference), max(throughput)

    #print(task_info)
    return (task_info['task']['running_time_in_nanos'], inference, throughput)


if __name__ == '__main__':

    # file output results name
    results = 'pipeline-results__' + str(datetime.now())
    header = ('allocation x threads per allocation',
                   '_reindex running_time_in_nanos in seconds',
                   '_reindex running_time_in_nanos',
                   'max average_inference_time_ms_last_minute',
                   'max throughput_last_minute',
                    'destination index name')
    tmpResults = [','.join(header)]

    # setup elastic cloud connection
    es_cloud_id = os.environ['es_cloud_id']
    es_cloud_user = os.environ['es_cloud_user']
    es_cloud_pass = os.environ['es_cloud_pass']

    # set the test pairs of allocations and threads per allocation on the supervised model
    allocation_threadsPer = [
        [1,8],
        [1,1],
        [4,1],
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
        #print(at)
        configString = 'x'.join(map(str, at))
        #print(configString)

        # create new index name
        indexName = '__'.join([reindexName, pipelineName, runTS, configString])

        #tmpResults.append(indexName)
        # create new index
        create_new_index(es, indexName)

        # update supervised model with this round's settings
        update_model_settings(es, modelID, at)

        # kickoff _reindex
        reindexResponse = start_reindex(es, sourceIndex, indexName,
                                        pipelineName)
        #print(reindexResponse)

        # wait for _reindex to complete
        elapsed_time, inf_max, tp_max = wait_until_ingest_complete(es, reindexResponse, modelID)
        #print(inf_max)
        #print(tp_max)

        #tmp = configString, ": ", elapsed_time / 1000000000, "seconds (", elapsed_time, " nanos), max thro"
        tmp = ','.join(map(str, (configString, elapsed_time / 1000000000, elapsed_time, inf_max, tp_max, indexName)))
        tmpResults.append(tmp)
        print(tmp)

    print('Done with configuration options')
    #print(tmpResults)
    with open(results, "w") as file:
        #file.writelines('\n'.join([''.join(map(str, x)) for x in tmpResults]))
        file.writelines('\n'.join(tmpResults))

    print('Done')



# TODO ideas
'''
potential enhancement here could be to clone the testing pipeline on each config run
then when it is complete, use the last ml _stats call to parse out 
trained_model_stats[].ingest.pipeline.processors

have an option to delete the indices created from _reindex

fix deprecation warning
'''