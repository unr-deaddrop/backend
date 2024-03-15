"""
All shared Celery tasks.
"""

from typing import Any, Optional
import time
import logging

from celery import shared_task, current_task, states
from celery.signals import before_task_publish
from django_celery_results.models import TaskResult

from backend.models import Agent, Endpoint
from backend.serializers import EndpointSerializer
from django.contrib.auth.models import User
from django.db.models.query import QuerySet
import backend.messaging as messaging
import backend.payloads as payloads


from deaddrop_meta.protocol_lib import DeadDropMessage, CommandRequestPayload, DeadDropMessageType

logger = logging.getLogger(__name__)

# https://github.com/celery/django-celery-results/issues/286

# Instantly create TaskResults, rather than waiting until they're done.
@before_task_publish.connect
def create_task_result_on_publish(sender=None, headers=None, body=None, **kwargs):
    if "task" not in headers:
        return

    TaskResult.objects.store_result(
        "application/json",
        "utf-8",
        headers["id"],
        None,
        states.PENDING,
        # Celery places leading quotes when the task is complete, but this
        # normally doesn't. For consistency, we place leading quotes. There's
        # probably a better way to handle this, but I don't think it matters
        # much right now.
        task_name='"'+headers["task"]+'"',
        task_args='"'+headers["argsrepr"]+'"',
        task_kwargs='"'+headers["kwargsrepr"]+'"',
    )

def add_user_id_to_task(user_id: Optional[int]) -> Optional[User]:
    """
    Add a user ID to the current TaskResult object.
    
    If no user is set, nothing happens and this returns None. If a user is set,
    the corresponding user is returned.
    
    If the user does not exist, this does not catch the exception;
    `User.DoesNotExist` is raised.
    """
    # Get the current task ID. Use this to query the TaskResult database, which
    # should already have had an entry made (since the signal is before_task_publish,
    # the code should not get this far without the call having been made).
    if user_id is None:
        return None
        
    user = User.objects.get(id=user_id)
    
    task_id = current_task.request.id
    task_result = TaskResult.objects.get(task_id=task_id)
    task_result.task_creator = user
    task_result.save()
    
    return user

@shared_task
def test_connection() -> str:
    """
    Can the agent table be queried?
    """
    if Agent.objects.count() > 0:
        agent = Agent.objects.get(id=1)
        return agent.name
    
    return "None found!"

@shared_task
def generate_payload(
    validated_data: dict[str, Any], user_id: Optional[int]
) -> dict[str, Any]:
    """
    Generate a new payload. This is intended to spin up a sibling Docker
    container in a temporary folder with a random container name.

    Note that the keyword arguments `payload_file` and `connections` are ignored
    when generating physical payloads through this task. That is, if a payload
    file is specified, it is ignored and replaced by the container-generated
    payload file instead; if connections are specified, they are deleted and
    must be added after the fact.
    """
    # It's assumed all of these are coming from the serializer. Flaky, but
    # it works.
    user = add_user_id_to_task(user_id)
    
    # Extract the fields used throughout the build process and remove them from
    # the dictionary. The remaining fields are passed into the Endpoint constructor
    # as-is.
    agent = Agent.objects.get(id=validated_data.pop("agent"))
    build_args = validated_data.pop("agent_cfg")

    task_id = current_task.request.id
    endpoint = payloads.build_payload(agent, build_args, task_id, user, **validated_data)
    serializer = EndpointSerializer(endpoint)
    return serializer.data
    
@shared_task
def execute_command(
    validated_data: dict[str, Any], 
    endpoint_id: str,
    user_id: Optional[int] = None,
) -> dict[str, Any]:
    """
    Execute a command. Again, this is intended to spin up a sibling Docker container
    in which the agent can construct and send messages in a platform-independent
    manner.
    
    It is assumed that `validated_data` is (effectively) the contents of a
    CommandRequestPayload, which has already been validated by the JSON schema
    and passed through the preprocessor. This is to ensure that the user receives
    feedback *before* tasking is started.
    """
    # Associate the current task with the specified user
    user = add_user_id_to_task(user_id)
    
    # Select the relevant endpoint (and complain if it somehow doesn't exist)
    try:
        endpoint: Endpoint = Endpoint.objects.get(id=endpoint_id)
    except Endpoint.DoesNotExist:
        raise RuntimeError(f"The endpoint {endpoint_id=} does not exist!")
    
    # Construct DeadDropMessage, using CommandRequestPayload. Note that:
    # - The default factory for the message ID is used
    # - No source ID is specified, so it is implied that it comes from the server
    # - The current timestamp is used
    # - The message is NOT signed; it is up to the package to do this
    #
    # Note that we do not create a Message instance, since this is handled
    # by message handling system. Our only job is to construct the message, not
    # commit it to the database.
    msg = DeadDropMessage(
        user_id = user_id,
        payload = CommandRequestPayload(
            message_type = DeadDropMessageType.CMD_REQUEST,
            cmd_name = validated_data['cmd_name'],
            cmd_args = validated_data['cmd_args']
        ),
        destination_id = endpoint_id
    )
    
    # Invoke "send message" operation in the message handler, wait until return
    task_id = current_task.request.id
    result = messaging.send_message(msg, endpoint, task_id, user)
    
    # Asynchronously start the receieve_message task
    receive_messages.delay(endpoint_id, user_id, msg.message_id)
    
    # Return raw results from messaging unit
    return result
    
@shared_task
def receive_messages(
    endpoint_id: str,
    user_id: Optional[int] = None,
    request_id: Optional[str] = None
) -> list[str]:
    """
    Start a task to receive all messages from an endpoint.
    
    The immediate result of this task is simply a list of message IDs. These
    can be inspected through the corresponding Message or Log instances as
    needed.
    """
    # Associate the current task with the specified user
    user = add_user_id_to_task(user_id)
    
    # Select the relevant endpoint (and complain if it somehow doesn't exist)
    try:
        endpoint: Endpoint = Endpoint.objects.get(id=endpoint_id)
    except Endpoint.DoesNotExist:
        raise RuntimeError(f"The endpoint {endpoint_id=} does not exist!")
    
    # Invoke "receive message" operation, wait until return
    task_id = current_task.request.id
    msgs = messaging.receive_messages(endpoint, request_id, task_id, user)
    
    # Obviously we can't serialize DeadDropMessages, so the next best thing is
    # to just return a list of message IDs that can be looked up in the db
    return [str(msg.message_id) for msg in msgs]