import requests
import os
import json
import time
import subprocess
from functools import reduce

cwd = os.getcwd()
directory_in_str = cwd+'/pipelines'
directory = os.fsencode(directory_in_str)
instanceURL = 'https://testing-cdf-project-261000-dot-usw1.datafusion-staging.googleusercontent.com/'
deployEndpoint = 'api/v3/namespaces/%s/apps/'
runEndpointFormat = "api/v3/namespaces/%s/apps/%s/workflows/DataPipelineWorkflow/start"
runStatusEndpointFormat = "api/v3/namespaces/%s/apps/%s/workflows/DataPipelineWorkflow/runs/"
draftEndpoint = 'api/v3/namespaces/system/apps/pipeline/services/studio/methods/v1/contexts/%s/drafts/'
previewEndpoint = 'api/v3/namespaces/%s/previews'
metricsEndpoint = 'api/v3/metrics/query?metric='

perfMetricLatFile = cwd+'/metricLatencies.csv'
perfCreateLatFile = cwd+'/createLatencies.csv'


def getAuthHeader():
    token = subprocess.check_output(
        "gcloud auth print-access-token", shell=True).decode('UTF-8')
    token = token.strip(" \n")
    return "Bearer "+token


def deployPipeline(pipelineJson, pipelineName, namespace='default'):
    pipelineJson['name'] = pipelineName
    print("Deploying "+pipelineName+" in namespace "+namespace)
    headers = {"Authorization": getAuthHeader()}
    url = instanceURL+deployEndpoint % namespace+pipelineName
    startTime = time.time()
    res = requests.put(url, json=pipelineJson, headers=headers)
    print(res.text)
    if res.status_code == 200:
        return time.time() - startTime
    return None


def deletePipeline(pipelineName, namespace='default'):
    print("Deleting pipeline "+pipelineName+" in namespace "+namespace)
    headers = {"Authorization": getAuthHeader()}
    url = instanceURL+deployEndpoint % namespace+pipelineName
    res = requests.delete(url, headers=headers)
    print(res.text)


def startPreviewRun(pipelineJson, pipelineName, namespace='default'):
    print("Starting preview for "+pipelineName+" in namespace "+namespace)
    headers = {"Authorization": getAuthHeader()}
    url = instanceURL+previewEndpoint % namespace
    pipelineJson['preview'] = {
        "programName": "DataPipelineWorkflow",
        "programType": "Workflow",
        'endStages':[pipelineJson['config']['connections'][0]['to']],
        'startStages':[pipelineJson['config']['connections'][0]['from']],
        'realDatasets':[],
        'runtimeArgs':{}
    }
    res = requests.post(url, headers=headers, json=pipelineJson)
    print(res.text)


def startPipelineRun(pipelineName, runtimeArgs={}, namespace='default'):
    print("Starting run for "+pipelineName+" in namespace "+namespace)
    headers = {"Authorization": getAuthHeader()}
    url = instanceURL+runEndpointFormat % (namespace, pipelineName)
    res = requests.post(url, headers=headers, json=runtimeArgs)
    print(res.text)


def createDraft(pipelineJson, pipelineName, namespace='default'):
    pipelineJson['name'] = pipelineName
    print("Create draft "+pipelineName+" in namespace "+namespace)
    headers = {"Authorization": getAuthHeader()}
    url = instanceURL+draftEndpoint % namespace+pipelineName
    data = {
        'name': pipelineName,
        'artifact': pipelineJson['artifact'],
        'config': pipelineJson
    }
    startTime = time.time()
    res = requests.put(url, json=pipelineJson, headers=headers)
    print(res.text)
    if res.status_code == 200:
        return time.time() - startTime
    return 'ERROR'


def deleteDraft(pipelineName, namespace='default'):
    print("Deleting draft "+pipelineName+" in namespace "+namespace)
    headers = {"Authorization": getAuthHeader()}
    url = instanceURL+draftEndpoint % namespace+pipelineName
    res = requests.delete(url, headers=headers)
    print(res.status_code)


def draftCountMetricLatency():
    return queryMetricLatency('user.draft.count')


def pipelineCountMetricLatency():
    return queryMetricLatency('system.application.count')


def queryMetricLatency(metricName):
    print("Getting metric "+metricName)
    headers = {"Authorization": getAuthHeader()}
    url = instanceURL+metricsEndpoint+metricName
    startTime = time.time()
    res = requests.post(url, headers=headers)
    latency = time.time()-startTime
    if res.status_code == 200:
        return time.time() - startTime
    return 'ERROR'


def correctnessTests(pipelineJsons, testSleepPeriod, stepSleepPeriod):
    while True:
        for pj in pipelineJsons:
            for namespace in ['default', 'correctness']:
                pipelineName = pj['name']
                createDraft(pj, pipelineName, namespace)
                deployPipeline(pj, pipelineName, namespace)
                startPipelineRun(pipelineName, {}, namespace)
                startPreviewRun(pj, pipelineName, namespace)
            time.sleep(60)

        time.sleep(stepSleepPeriod)
        for pj in pipelineJsons:
            for namespace in ['default', 'correctness']:
                pipelineName = pj['name']
                deleteDraft(pipelineName, namespace)
                deletePipeline(pipelineName, namespace)

        time.sleep(testSleepPeriod)


def performanceTests(pipeline, numPipelines, testSleepPeriod):
    pipelineBaseName = pipeline['name']
    iterNum = 1
    with open(perfCreateLatFile, 'w') as f:
        f.write('iteration,pipelineNum,deployLat,draftLat\n')
    with open(perfMetricLatFile, 'w') as f:
        f.write('iteration,pipelineMetricLat,draftMetricLat\n')

    while True:
        createData = []

        for i in range(1, numPipelines+1):
            pipelineName = "%s-%d" % (pipelineBaseName, i)
            deployLat = deployPipeline(pipeline, pipelineName)
            draftLat = 0 #createDraft(pipeline, pipelineName)
            createData.append([str(iterNum), str(i), str(deployLat), str(draftLat)])

        draftMetricLat = draftCountMetricLatency()
        pipelineMetricLat = pipelineCountMetricLatency()
        metricData = [str(iterNum), str(pipelineMetricLat), str(draftMetricLat)]

        with open(perfCreateLatFile, 'a+') as f:
            f.writelines([','.join(row)+'\n' for row in createData])
        with open(perfMetricLatFile, 'a+') as f:
            f.write(','.join(metricData)+'\n')

        for i in range(1, numPipelines+1):
            pipelineName = "%s-%d" % (pipelineBaseName, i)
            deletePipeline(pipelineName)
            # deleteDraft(pipelineName)

        iterNum += 1
        time.sleep(testSleepPeriod)


pipelineJsons = []
for file in os.listdir(directory):
    filename = os.fsdecode(file)
    pipelinePath = os.path.join(directory_in_str, filename)
    f = open(pipelinePath, 'r')
    pipelineStr = f.read()
    f.close()
    pipelineJsons.append(json.loads(pipelineStr))


testSleepPeriod = 60 * 60
stepSleepPeriod = 15 * 60

correctnessTests(pipelineJsons, testSleepPeriod, stepSleepPeriod)
# performanceTests(pipelineJsons[0], 10, 60*60)