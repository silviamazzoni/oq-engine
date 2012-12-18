# Copyright (c) 2010-2012, GEM Foundation.
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake.  If not, see <http://www.gnu.org/licenses/>.


"""Base code for calculator classes."""

import kombu

from openquake import logs
from openquake.utils import config

# Routing key format string for communication between tasks and the control
# node.
ROUTING_KEY_FMT = 'oq.job.%(job_id)s.tasks'


class Calculator(object):
    """Base abstract class for all calculators."""

    def __init__(self, job_ctxt):
        """
        :param job_ctxt: :class:`openquake.engine.JobContext` instance.
        """
        self.job_ctxt = job_ctxt

    def initialize(self, *args, **kwargs):
        """Implement this method in subclasses to record pre-execution stats,
        estimate the calculation size, etc."""

    def pre_execute(self, *args, **kwargs):
        """Implement this method in subclasses to perform pre-execution
        functions, such as instantiating objects need for the calculation and
        loading calculation data into a cache."""

    def execute(self, *args, **kwargs):
        """This is only method that subclasses are required to implement. This
        should contain all of the calculation logic."""
        raise NotImplementedError()

    def post_execute(self, *args, **kwargs):
        """Implement this method in subclasses to perform post-execution
           functions, such as result serialization."""

    def clean_up(self, *args, **kwargs):
        """Implement this method in subclasses to perform clean-up actions
           like garbage collection, etc."""


# TODO: make concurrent_tasks and block_size as properties
# TODO: change config.get_section hazard task_exchange type=direct
class CalculatorNext(object):
    """
    Base class for all calculators.

    :param job: :class:`openquake.db.models.OqJob` instance.
    """

    def __init__(self, job):
        self.job = job

    def pre_execute(self):
        """
        Override this method in subclasses to record pre-execution stats,
        initialize result records, perform detailed parsing of input data, etc.
        """

    def execute(self):
        """
        Calculation work is parallelized over sources, which means that each
        task will compute hazard for all sites but only with a subset of the
        seismic sources defined in the input model.

        The general workflow is as follows:

        1. Fill the queue with an initial set of tasks. The number of initial
        tasks is configurable using the `concurrent_tasks` parameter in the
        `[hazard]` section of the OpenQuake config file.

        2. Wait for tasks to signal completion (via AMQP message) and enqueue a
        new task each time another completes. Once all of the job work is
        enqueued, we just wait until all of the tasks conclude.
        """
        block_size = int(config.get('hazard', 'block_size'))
        concurrent_tasks = int(config.get('hazard', 'concurrent_tasks'))

        # The following two counters are in a dict so that we can use them in
        # the closures below.
        # When `self.progress['compute']` becomes equal to
        # `self.progress['total']`, `execute` can conclude.

        task_gen = self.task_arg_gen(block_size)

        exchange, conn_args = exchange_and_conn_args()

        routing_key = ROUTING_KEY_FMT % dict(job_id=self.job.id)
        task_signal_queue = kombu.Queue(
            'tasks.job.%s' % self.job.id, exchange=exchange,
            routing_key=routing_key, durable=False, auto_delete=True)

        with kombu.BrokerConnection(**conn_args) as conn:
            task_signal_queue(conn.channel()).declare()
            with conn.Consumer(
                task_signal_queue,
                callbacks=[self.get_task_complete_callback(task_gen,
                    block_size,
                    concurrent_tasks)]):

                # First: Queue up the initial tasks.
                for _ in xrange(concurrent_tasks):
                    try:
                        queue_next(self.core_calc_task, task_gen.next())
                    except StopIteration:
                        # If we get a `StopIteration` here, that means we have
                        # a number of tasks < concurrent_tasks.
                        # This basically just means that we could be
                        # under-utilizing worker node resources.
                        break

                while (self.progress['computed'] < self.progress['total']):
                    # This blocks until a message is received.
                    # Once we receive a completion signal, enqueue the next
                    # piece of work (if there's anything left to be done).
                    # (The `task_complete_callback` will handle additional
                    # queuing.)
                    conn.drain_events()
        logs.LOG.progress("calculation 100% complete")

    def post_execute(self):
        """
        Override this method in subclasses to any necessary post-execution
        actions, such as the consolidation of partial results.
        """

    def post_process(self):
        """
        Override this method in subclasses to perform post processing steps,
        such as computing mean results from a set of curves or plotting maps.
        """

    def export(self, *args, **kwargs):
        """Implement this method in subclasses to write results
           to places other than the database."""

    def clean_up(self, *args, **kwargs):
        """Implement this method in subclasses to perform clean-up actions
           like garbage collection, etc."""


def exchange_and_conn_args():
    """
    Helper method to setup an exchange for task communication and the args
    needed to create a broker connection.
    """

    exchange = kombu.Exchange(
        config.get_section('hazard')['task_exchange'], type='direct')

    amqp_cfg = config.get_section('amqp')
    conn_args = {
        'hostname': amqp_cfg['host'],
        'userid': amqp_cfg['user'],
        'password': amqp_cfg['password'],
        'virtual_host': amqp_cfg['vhost'],
        }

    return exchange, conn_args


def queue_next(task_func, task_args):
    """
    :param task_func:
        A Celery task function, to be enqueued with the next set of args in
        ``task_arg_gen``.
    :param task_args:
        A set of arguments which match the specified ``task_func``.

    .. note::
        This utility function was added to make for easier mocking and testing
        of the "plumbing" which handles task queuing (such as the various "task
        complete" callback functions).
    """
    task_func.apply_async(task_args)


def signal_task_complete(**kwargs):
    """
    Send a signal back through a dedicated queue to the 'control node' to
    notify of task completion and the number of sources computed.

    Signalling back this metric is needed to tell the control node when it can
    conclude its `execute` phase.

    :param kwargs:
        Arbitrary message parameters. Anything in this dict will go into the
        "task complete" message.

        Typical message parameters would include `job_id` and `num_items` (to
        indicate the number of work items that the task has processed).

        .. note::
            `job_id` is required for routing the message. All other parameters
            can be treated as optional.
    """
    msg = kwargs
    # here we make the assumption that the job_id is in the message kwargs
    job_id = kwargs['job_id']

    exchange, conn_args = exchange_and_conn_args()

    routing_key = ROUTING_KEY_FMT % dict(job_id=job_id)

    with kombu.BrokerConnection(**conn_args) as conn:
        with conn.Producer(exchange=exchange,
            routing_key=routing_key) as producer:
            producer.publish(msg)
