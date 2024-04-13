from pathlib import Path
from typing import Any, Union, Optional
from tempfile import TemporaryDirectory
import logging
import json
import shutil
import uuid

from django.contrib.auth.models import User, Group
from django.db import models
from django.urls import reverse
from django.conf import settings
from django.db.models.signals import post_delete
from django.dispatch import receiver

from django_celery_results.models import TaskResult

from deaddrop_meta.protocol_lib import DeadDropMessageType, DeadDropMessage
from deaddrop_meta.protocol_lib import Credential as DeadDropCredential
from deaddrop_meta.protocol_lib import File as DeadDropFile

logger = logging.getLogger(__name__)

# Add an extra field to the TaskResult model called task_creator. This is an FK
# to Django's stock User field. While allowed to be blank, it is not intended
# to remain blank if possible.
#
# In practice, it should never be left blank, since all DRF requests have the
# user available (unless anonymous.)
#
# Note that this naturally creates another migration. If you're not running
# in a virtual environment, this *will* edit the set of migrations in the
# Django application for django_celery_results. You may need to delete this
# migration for things to work correctly.
TaskResult.add_to_class('task_creator', models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True))

# from django.db.models.signals import post_save
# from django.dispatch import receiver
# from rest_framework.authtoken.models import Token

# @receiver(post_save, sender=settings.AUTH_USER_MODEL)
# def create_auth_token(sender, instance=None, created=False, **kwargs):
#     if created:
#         Token.objects.create(user=instance)

class Agent(models.Model):
    name = models.CharField(
        max_length=100, help_text="Human-readable name for the agent."
    )
    # Store the version of the agent along with the name. Different versions
    # of the same agent may not be backwards compatible, so it's necessary
    # to store definitions for each (even if their names are the same).
    #
    # Note that this differs from "conventional" package management in that
    # agents generally can't be remotely updated, and therefore the server must
    # continue using outdated metadata for that agent to communicate with it.
    version = models.CharField(max_length=100, help_text="The version for this agent.")
    # Path to the original agent package file. It may be the case that the user
    # wants to distribute the package itself, which is preferred over re-zipping
    # the unpackaged bundle (since the server may have left behind various files
    # that shouldn't be bundled.)
    package_file = models.FileField(
        upload_to="agents", help_text="The original agent package file."
    )
    # Path to the unpackaged contents. It is assumed that the package manager
    # has already unpackaged and generated the relevant metadata files by the
    # time an Agent instance is created for that package.
    #
    # Implicitly, all Agent instances are strictly tied to a package; it should
    # not be possible to create an endpoint without its corresponding package.
    package_path = models.FilePathField(
        path=settings.AGENT_PACKAGE_DIR,
        allow_folders=True,
        allow_files=False,
        help_text=(
            f"The directory in `{settings.AGENT_PACKAGE_DIR}` where the agent's files"
            " have been unpackaged, with metadata generated."
        ),
    )

    class Meta:
        # No two agents may have the same name and version.
        unique_together = (
            "name",
            "version",
        )

    def deserialize_package_json(self, package_file: str) -> dict[str, Any]:
        json_path = (Path(self.package_path)/package_file).resolve()
        if not json_path.exists():
            raise RuntimeError(f"{json_path} does not exist in the package directory")
        with open(json_path, "rt") as fp:
            return json.load(fp)

    # Various helper commands to get the relevant metadata for this agent.
    # Right now, these are just loosely-structured JSON and Python dictionaries;
    # in the future, deaddrop_meta will allow us to validate the metadata and
    # return an actual object with attributes.
    def get_command_metadata(self) -> list[dict[str, Any]]:
        """
        Get all supported commands and their details for this agent.
        
        This simply deserializes commands.json.
        """
        return self.deserialize_package_json("commands.json")

    def get_protocol_metadata(self) -> list[dict[str, Any]]:
        """
        Get all supported protocols and their details for this agent.
        
        This simply deserializes protocols.json.
        """
        return self.deserialize_package_json("protocols.json")

    def get_agent_metadata(self) -> dict[str, Any]:
        """
        Get the metadata for the agent.
        
        This simply deserializes agent.json and converts it to a dictionary.
        """
        return self.deserialize_package_json("agent.json")
    
    def copy_to_temp_dir(self) -> Union[TemporaryDirectory, None]:
        """
        Copy the agent package to a temporary directory and return the TemporaryDirectory
        object.
        
        If no package has been specified for this agent, this returns None.
        
        If a package has been specified, but it is not available, this raises
        RuntimeError.
        """
        temp_dir = TemporaryDirectory()
        
        # Helps avoid random Docker errors due to packaging being placed in folders
        # with trailing underscores.
        while "_" in temp_dir.name:
            logger.warning(f"You rolled Hu Tao! (directory name {temp_dir.name} invalid, retrying)")
            temp_dir = TemporaryDirectory()
        
        if not self.package_path:
            return None
        
        package_path = Path(self.package_path).resolve()
        if not package_path.exists():
            raise RuntimeError(f"{self} uses {package_path}, but that folder doesn't exist!")

        shutil.copytree(package_path, temp_dir.name, dirs_exist_ok=True)
        
        return temp_dir

    def get_absolute_url(self):
        return reverse("agent-detail", args=[str(self.id)])

    def __str__(self):
        return f"{self.name}-{self.version}"

@receiver(post_delete, sender=Agent)
def delete_agent_package(sender, instance, using, **kwargs):
    """
    On agent deletion, nuke the package path and the original package file.
    """
    (Path(settings.MEDIA_ROOT) / Path(instance.package_file.name)).unlink()
    shutil.rmtree(instance.package_path)

class Protocol(models.Model):
    # Human-readable name
    name = models.CharField(
        max_length=100, unique=True, help_text="Human-readable name for the protocol."
    )
    # Path to the original protocol package file. As with agents, the original
    # package file is preferred when redistribution is necessary, avoiding
    # bundling any server-specific files with it.
    package_file = models.FileField(
        upload_to="protocols", help_text="The original protocol package file."
    )
    # Path to the unpackaged contents.
    #
    # Note that unlike agents, protocols are required to expose an executable
    # to allow language agnostic implementations.
    package_path = package_path = models.FilePathField(
        path=settings.PROTOCOL_PACKAGE_DIR,
        allow_folders=True,
        allow_files=False,
        help_text=(
            f"The directory in `{settings.PROTOCOL_PACKAGE_DIR}` where the protocol's"
            " files have been unpackaged, with metadata generated."
        ),
    )

    def get_absolute_url(self):
        return reverse("protocol-detail", args=[str(self.id)])

    def __str__(self):
        return self.name


class Endpoint(models.Model):
    # The agent UUID.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Human-readable name, device hostname, and remote address; these cannot be
    # set at construct time
    name = models.CharField(max_length=100, blank=True, null=True)
    hostname = models.CharField(max_length=100, blank=True, null=True)
    address = models.CharField(max_length=32, blank=True, null=True)

    # Does this device actually have an agent installed?
    is_virtual = models.BooleanField()

    # What protocol and agent does this endpoint use, if any?
    # Also, block endpoints from destruction if an agent or protocol is deleted
    agent = models.ForeignKey(
        Agent, on_delete=models.PROTECT, related_name="endpoints", blank=True, null=True
    )

    # Agent-specific configuration object. Should be read-only after set.
    agent_cfg = models.JSONField(blank=True, null=True)

    # Protocol state object used to allow the agent to change its protocol 
    # execution across calls.
    protocol_state = models.JSONField(blank=True, null=True)

    # What other endpoints does this endpoint have direct access to?
    # FIXME: this may be wrong according to https://stackoverflow.com/questions/39821723/django-rest-framework-many-to-many-field-related-to-itself
    connections = models.ManyToManyField("self", blank=True, null=True)

    # The constructed payload for this endpoint (if not virtual).
    payload_file = models.FileField(
        upload_to="payloads",
        help_text="The original payload bundle.",
        blank=True,
        null=True,
    )

    def get_absolute_url(self):
        return reverse("endpoint-detail", args=[str(self.id)])

    def __str__(self):
        return self.name + ": " + self.hostname

class Message(models.Model):
    """
    Server-side representation of a DeadDropMessage.
    
    Note that this is generally only used to keep track of messages that have
    already been seen to prevent acting on them twice; it also provides an 
    alternative method of viewing all communication within the framework that is
    independent of the Log model.
    
    The structure of this model is virtually identical to DeadDropMessage. Note
    that since this is intended to be a "non-functional" class, no attempt at 
    matching the structure of the *payload* fields is made. Payloads are dumped
    out as-is.
    
    For the sake of logging, all messages that are ever received or sent by the 
    server should result in the creation of a Message model, even if the same
    information is duplicated elsewhere.
    """
    # This generally should not change very often, so this is valid.
    # By convention, deaddrop_meta should never *remove* existing message types.
    message_types = [(mtype.name, mtype.value) for mtype in DeadDropMessageType]
    
    # It is very rare that messages are created manually.
    message_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="users", blank=True, null=True)
    source = models.ForeignKey(Endpoint, on_delete=models.PROTECT, related_name="messages_sources", blank=True, null=True)
    destination = models.ForeignKey(Endpoint, on_delete=models.PROTECT, related_name="messages_destinations", blank=True, null=True)
    timestamp = models.DateTimeField()
    payload = models.JSONField()
    message_type = models.CharField(choices=message_types, max_length=50)
    digest = models.BinaryField(blank=True, null=True)
    
    @classmethod
    def from_deaddrop_message(cls, msg: DeadDropMessage) -> "Message":
        """
        Construct (but do not save) a new Message instance from a DeadDropMessage.
        """
        user = None
        source = None
        destination = None
        
        try:
            user = User.objects.get(id=msg.user_id)
        except User.DoesNotExist:
            pass
        
        try:
            source = Endpoint.objects.get(id=msg.source_id)
        except Endpoint.DoesNotExist:
            pass
        
        try:
            destination = Endpoint.objects.get(id=msg.destination_id)
        except Endpoint.DoesNotExist:
            pass
        
        # Note that there is a nonzero chance that the contents of the message are not 
        # Django-serializable but *are* Pydantic-serializable. I don't think we'll run
        # into this, but we may need to revisit this. By convention, messages don't have
        # scary datatypes, but that's not really much of a guarantee.
        return cls(
            message_id = msg.message_id,
            user = user,
            source = source,
            destination = destination,
            timestamp = msg.timestamp,
            payload = msg.payload.model_dump_json(),
            message_type = msg.payload.message_type,
            digest = msg.digest
        )
    

class Credential(models.Model):
    credential_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    source = models.ForeignKey(
        Endpoint, blank=True, null=True, on_delete=models.PROTECT, related_name="credentials"
    )
    
    # Task responsible for creating this credential entry, if any
    task = models.ForeignKey(
        TaskResult,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="credentials",
    )
    # Enum field, probably something like "session_token", "userpw", etc
    # Again, it may make sense to create an arbitrary tag model for this
    credential_type = models.CharField(max_length=32)

    # The actual value of the session token, username/password combo, etc -
    # in case the credential is composed of multiple things, it should have a
    # clear delimiter based on credential_type
    credential_value = models.CharField(max_length=1023)

    # When this credential becomes invalid
    expiry = models.DateTimeField(blank=True, null=True)

    @classmethod
    def from_deaddrop_credential(cls, credential: DeadDropCredential) -> "Credential":
        return cls(
            credential_id=credential.credential_id,
            credential_type=credential.credential_type,
            credential_value=credential.value,
            expiry=credential.expiry
        )

    def get_absolute_url(self):
        return reverse("credential-detail", args=[str(self.id)])

    def __str__(self):
        return self.credential_type + ": " + self.credential_value


class File(models.Model):
    file_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    source = models.ForeignKey(
        Endpoint, blank=True, null=True, on_delete=models.PROTECT, related_name="files"
    )
    
    remote_path = models.CharField(max_length=1023, blank=True, null=True)
    
    # Task responsible for creating this credential entry, if any
    task = models.ForeignKey(
        TaskResult, on_delete=models.PROTECT, blank=True, null=True, related_name="files"
    )
    # Path to file; location to be determined
    file = models.FileField(upload_to="files")

    @classmethod
    def from_deaddrop_file(cls, file: DeadDropFile) -> "File":
        # Note that this also generates the actual file in the media folder,
        # but may be dangling if the resulting model instance is not saved
        #
        # This is assumed to not be an issue because of the astronomically
        # low collision chance
        media_path = (
            Path(cls.file.field.upload_to) / f"{file.file_id}.bin"
        )
        file_target = Path(settings.MEDIA_ROOT) / media_path
        
        # Make sure the folder exists before performing operations
        file_target.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_target, "wb+") as fp:
            fp.write(file.file_data.data)
        
        return cls(
            file_id = file.file_id,
            remote_path=file.remote_path,
            file = str(media_path)
        )

    def get_absolute_url(self):
        return reverse("file-detail", args=[str(self.id)])

    def __str__(self):
        return self.file  # does this work?


class Log(models.Model):
    # Is the log tied to a specific endpoint? (If blank, it's assumed to be
    # the server)
    source = models.ForeignKey(
        Endpoint, blank=True, null=True, on_delete=models.PROTECT, related_name="logs"
    )
    # Is the log tied to a user?
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="logs",
    )
    
    # Is the log tied to a specific task?
    task = models.ForeignKey(
        TaskResult, blank=True, null=True, on_delete=models.PROTECT, related_name="logs"
    )
    # Enumerable field; may make sense to create a "Tag" model and allow
    # it to be associated with arbitrary models, could help with organization
    category = models.CharField(max_length=32, blank=True, null=True)
    # Enum field, levels are likely to be 0 - 5
    level = models.IntegerField(blank=True, null=True)
    # Time of log (ideally, relative to server time; these should be timezone aware)
    timestamp = models.DateTimeField()
    # Actual log message
    data = models.TextField()

    def get_absolute_url(self):
        return reverse("log-detail", args=[str(self.id)])

    def __str__(self):
        return str(self.id) + " " +self.timestamp.strftime("(%Y-%m-%d %H:%M:%S)")
