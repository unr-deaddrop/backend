"""
The DeadDrop messaging system.

A longer description can be found at the following link:
https://github.com/unr-deaddrop/backend/issues/15

The messaging system works by assuming that a package contains a message_entry
recipe exists in the agent's Makefile. The entire package is copied to a temporary
directory before execution.

Additionally, note that this module *alone* is responsible for committing Message
instances to the database. This allows us to centralize where Messages are coming
from and keep track of where they're being spawned from.


The following conventions are assumed:
- That a Makefile exists, and that a `message_entry` recipe exists;
- That the called script leverages a `message_config.json` that is used to call
  the appropriate protocol handler bundled with the agent and configure it
  to reach out to the agent, where `message_config.json` contains the 
  *agent's* configuration data
- That if indicated in `message_config.json` to SEND, an additional file called
  `message.json` contains the serialized DeadDropMessage to be sent.
- That once the script returns, the following contents are made available in the
  temporary directory:
    - message-logs.txt, the immediate result of the task
    - if RECEIVING a message, messages.json, one or more messages retrieved from the
      protocol handler
    - protocol_state.json, an optional JSON document that allows for state maintenace
      across different calls to the protocol handler. The structure of this JSON
      document is agent-specific, and may be used (for example) to keep track of 
      messages that have already been seen.
    
Note that when sending (message.json) and receiving (messages.json), these messages
must be directly serializable to DeadDropMessage. If encryption, signing, or 
fragmentation must be performed, this *must* be done at the protocol level.
That is, all messages entering or exiting this component must already be in 
plaintext and are assumed to be *valid* messages. No signature verification is
done in this component.

In general, it is assumed that a Docker environment is spun up to allow the agent
messaging code to execute in a platform-independent manner.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Optional, Union, Literal
import datetime
import json
import logging
import subprocess

from deaddrop_meta.protocol_lib import DeadDropMessage, DeadDropLogLevel
from deaddrop_meta.interface_lib import MessagingObject, EndpointMessagingData, ServerMessagingData

from django.contrib.auth.models import User
from backend.models import Endpoint, Log, Message
from django_celery_results.models import TaskResult
from django.conf import settings
from django.db import IntegrityError

from pydantic import TypeAdapter

logger = logging.getLogger(__name__)

LOG_FILE_NAME = "message-logs.txt"
MESSAGE_CONFIG_NAME = "message_config.json"
PROTOCOL_STATE_NAME = "protocol_state.json"
MESSAGE_INPUT_NAME = "message.json"
MESSAGE_OUTPUT_NAME = "messages.json"

def send_message(
    msg: DeadDropMessage,
    endpoint: Endpoint,
    task_id: Optional[str] = None,
    user: Optional[User] = None
) -> dict[str, Any]:
    """
    Send the provided message to an endpoint.
    """
    # Commit the message to the database. If the message has already been sent
    # before, it will need to be sent with a new ID; this WILL raise an error.
    Message.from_deaddrop_message(msg).save()
    
    # Invoke the message handler.
    temp_dir = invoke_message_handler("send", endpoint, msg)
    temp_dir_path = Path(temp_dir.name).resolve()
    
    # Take message-logs.txt and use that as the result, also converting it into a 
    # LogMessage
    log = get_and_save_message_log(temp_dir_path, "messaging-send", user=user, task_id=task_id)
    
    # If present, read protocol_state.json and update the endpoint accordingly
    update_protocol_state(temp_dir_path, endpoint)
    
    # Blow up the temporary directory
    temp_dir.cleanup()
    
    # Return the contents of message-log.txt as the task's result
    return log.data

def receive_messages(
    endpoint: Endpoint,
    request_id: Optional[str],
    task_id: Optional[str] = None,
    user: Optional[User] = None
) -> list[DeadDropMessage]:
    """
    Receive messages from an endpoint.
      
    Filtering of duplicate messages is done at this stage by checking all 
    incoming DeadDropMessages against the list of Message instances currently
    contained in the database. If a message ID has already been seen, it is 
    assumed to be a duplicate message and dropped; otherwise, it is returned
    as part of the result. 
    
    Note that this function *does not* return Message instances (as declared 
    in models.py), but rather DeadDropMessage instances.
    
    If specified, request_id may be used to filter incoming messages to just
    the message specified. This only works if the message has a 
    CommandResponsePayload; all other messages are unconditionally dropped
    *from the result* when request_id is specified.
    
    Even when request_id is specified, Message instances are unconditionally
    committed to the database, so long as they are received from the agent.
    Duplicate messages are simply dropped; they do not raise exceptions.
    
    Finally, note that it is expected that the agent code perform any form
    of validation. It is assumed that if a message appears in messages.json,
    it has already been validated; evidently forged messages should be excluded
    from messages.json, but should be mentioned in the resulting log output.
    """
    temp_dir = invoke_message_handler("receive", endpoint, listen_id=request_id)
    temp_dir_path = Path(temp_dir.name).resolve()
    
    # Take message-logs.txt and use that as the result, also converting it into a 
    # LogMessage
    log = get_and_save_message_log(temp_dir_path, "messaging-receive", user=user, task_id=task_id)
    
    # If present, read protocol_state.json and update the endpoint accordingly
    update_protocol_state(temp_dir_path, endpoint)
    
    # Take messages.json and construct DeadDrop messages from it
    tmp_result = read_message_json(temp_dir_path)
    
    # For each DeadDropMessage, create and commit a new Message; ignore if it 
    # already exists
    result = []
    for msg in tmp_result:
        try:
            Message.from_deaddrop_message(msg).save()
            result.append(msg)
        except IntegrityError:
            logger.warning(f"Received {msg.message_id=}, assuming duplicate and dropping")
    
    # Blow up the temporary directory
    temp_dir.cleanup()
    
    # Return the contents of message-log.txt as the task's result
    return result

def invoke_message_handler(
    action: Union[Literal["send"], Literal["receive"]],
    endpoint: Endpoint,
    msg: Optional[DeadDropMessage] = None,
    listen_id: Optional[str] = None
) -> TemporaryDirectory:
    """
    Invoke the message handler. 
    
    This returns the temporary directory so that any method-specific actions
    can be taken before the directory is destroyed manually.
    """
    # Copy the entire package into a temporary directory (note that we don't need
    # to resolve the package path, since it's already correct relative to wherever
    # Django and the workers are running)
    temp_dir = endpoint.agent.copy_to_temp_dir()
    temp_dir_path = Path(temp_dir.name).resolve()
    logger.info(f"Using {temp_dir_path} for messaging")
    
    # Construct our MessageObject, then dump it out to the temporary directory as
    # message_config.json
    #
    # Note that the server's private key should still be in base64 at this stage,
    # but the Pydantic model is set up to automatically convert it to bytes and
    # then back to base64 when JSON dumping is invoked.
    #
    # TODO: For now, the preferred protocol is completely ignored since Pygin 
    # only listens over one protocol in practice for the sake of reliability.
    # Pygin should select the first protocol in the list of listeners.
    msg_obj = MessagingObject(
        agent_config=endpoint.agent_cfg['agent_config'],
        protocol_config=endpoint.agent_cfg['protocol_config'],
        protocol_state=endpoint.protocol_state,
        endpoint_model_data = EndpointMessagingData(
            name=endpoint.name,
            hostname = endpoint.hostname,
            address= endpoint.address
        ),
        server_config = ServerMessagingData(
            action=action,
            listen_for_id=listen_id,
            server_private_key=settings.SERVER_PRIVATE_KEY if action == "send" else None,
            preferred_protocol=None
        )
    )
    with open((temp_dir_path / MESSAGE_CONFIG_NAME), "wt+") as fp:
        fp.write(msg_obj.model_dump_json())
    
    # Dump the DeadDropMessage as message.json into the temporary directory.
    if msg:
        with open((temp_dir_path / MESSAGE_INPUT_NAME), "wt+") as fp:
            fp.write(msg.model_dump_json())
        
    
    # Assert that the Makefile is present and invoke the message_entry recipe
    target = temp_dir_path / "Makefile"
    if not target.exists():
        raise RuntimeError(
            f"The payload build script {target} is missing from {temp_dir_path}!"
        )
    p = subprocess.run(
        ["make", "message_entry"], shell=False, capture_output=True, cwd=temp_dir_path
    )
    logger.warning(f"{p.stdout=} {p.stderr=}")
    
    return temp_dir

def get_and_save_message_log(
    temp_dir: Path,
    category: str,
    user: Optional[User] = None,
    task_id: Optional[str] = None,
) -> Log:
    log_path = temp_dir / LOG_FILE_NAME

    if not log_path.exists():
        raise RuntimeError(f"Missing log output for payload at {log_path}!")
    with open(log_path, "rt") as fp:
        logger.debug(f"Creating log entry from data at {log_path}")
        
        if task_id:
            task = TaskResult.objects.get(task_id=task_id)
        else:
            task = None
            
        log = Log(
            source=None,
            user=user,
            task=task,
            category=category,
            level=DeadDropLogLevel.INFO,
            timestamp=datetime.datetime.now(datetime.UTC),
            data=fp.read(),
        )

    log.save()

    return log

def update_protocol_state(
    temp_dir: Path,
    endpoint: Endpoint
) -> Union[dict[str, Any], None]:
    protocol_state_path = temp_dir / PROTOCOL_STATE_NAME
    
    if not protocol_state_path.exists():
        return None
    
    with open(protocol_state_path, "rt") as fp:
        endpoint.protocol_state = json.load(fp)
        
def read_message_json(
    temp_dir: Path
) -> list[DeadDropMessage]:
    """
    Read the message JSON. 
    
    The *absence* of the JSON file is considered an error and raises RuntimeError.
    If no messsages were retrieved, the JSON file should simply be an empty list.
    """
    message_path = temp_dir / MESSAGE_OUTPUT_NAME
    
    if not message_path.exists():
        raise RuntimeError(f"Missing message.json from expected message output at {message_path}")
    
    with open(message_path, "rt") as fp:
        data = fp.read()
        
    # Not needed since we're using typeadapter, not json.load
    # if not isinstance(data, list):
    #     raise RuntimeError(f"Expected list of messages from {MESSAGE_OUTPUT_NAME}, got {data}")
    
    # For each item, convert to DeadDropMessage
    # See https://stackoverflow.com/questions/55762673/how-to-parse-list-of-models-with-pydantic
    ta = TypeAdapter(list[DeadDropMessage])
    msgs = ta.validate_json(data)
    
    return msgs
    
    