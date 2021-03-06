import json
import yaml
import zmq

from zmq.utils.strtypes import u

from xmlrpc import client as xmlrpclib
from urllib.parse import urlsplit


from squad.ci.backend.null import Backend as BaseBackend


description = "LAVA"


class Backend(BaseBackend):

    # ------------------------------------------------------------------------
    # API implementation
    # ------------------------------------------------------------------------
    def submit(self, test_job):
        job_id = self.__submit__(test_job.definition)
        return job_id

    def fetch(self, test_job):
        data = self.__get_job_details__(test_job.job_id)
        if data['status'] in self.complete_statuses:
            yamldata = self.__get_testjob_results_yaml__(test_job.job_id)
            data['results'] = yaml.load(yamldata)
        return self.__parse_results__(data)

    def listen(self):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        # TODO: filter by topic for each server
        # Topic should be set in the Backend model
        # TODO: there might be an issue with setsockopt_string depending on
        # python version. This might need refactoring
        self.socket.setsockopt_string(zmq.SUBSCRIBE, "")  # listen to all messages
        # TODO: change address to proper one
        # This hardcoded value is incorrect in most cases
        self.socket.connect("tcp://%s:5510" % urlsplit(self.data.url).netloc)

        while True:
            try:
                message = self.socket.recv_multipart()
                (topic, uuid, dt, username, data) = (u(m) for m in message[:])
                lava_id = data['job']
                if 'sub_id' in data.keys():
                    lava_id = data['sub_id']
                lava_status = data['status']
                if lava_status in self.complete_statuses:
                    db_test_job_list = self.data.test_jobs.filter(
                        submitted=True,
                        fetched=False,
                        job_id=lava_id)
                    if db_test_job_list.exists() and len(db_test_job_list) == 1:
                        # TODO: move to async execution
                        self.data.fetch(db_test_job_list[0])
            except Exception as e:
                # TODO: at least log error
                pass

    # ------------------------------------------------------------------------
    # implementation details
    # ------------------------------------------------------------------------
    def __init__(self, data):
        super(Backend, self).__init__(data)
        self.complete_statuses = ['Complete', 'Incomplete', 'Canceled']
        self.__proxy__ = None

    @property
    def proxy(self):
        if self.__proxy__ is None:
            url = urlsplit(self.data.url)
            endpoint = '%s://%s:%s@%s%s' % (
                url.scheme,
                self.data.username,
                self.data.token,
                url.netloc,
                url.path
            )
            self.__proxy__ = xmlrpclib.ServerProxy(endpoint)
        return self.__proxy__

    def __submit__(self, definition):
        return self.proxy.scheduler.submit_job(definition)

    def __get_job_details__(self, job_id):
        return self.proxy.scheduler.job_details(job_id)

    def __get_testjob_results_yaml__(self, job_id):
        return self.proxy.results.get_testjob_results_yaml(job_id)

    def __parse_results__(self, data):
        return (data['status'], {}, {}, {})
