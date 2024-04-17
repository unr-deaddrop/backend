from pathlib import Path
from typing import Any
import uuid
import shutil
import tempfile

from celery.result import AsyncResult

# from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.decorators import action, api_view
from rest_framework import status, permissions, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.authtoken.models import Token
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.filters import SearchFilter
from rest_framework.pagination import PageNumberPagination
from django_filters import rest_framework as filters


from django.core.files.uploadhandler import TemporaryFileUploadHandler
from django_filters.rest_framework import DjangoFilterBackend
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.db.models import Q, Func, IntegerField, DateTimeField
from django.conf import settings
from django.http import JsonResponse
from django.core.paginator import Paginator

from backend.models import (
    Agent,
    Protocol,
    Endpoint,
    Credential,
    File,
    Log,
    Message
)
from django_celery_results.models import TaskResult
from backend.serializers import (
    UserSerializer,
    AgentSerializer,
    BundleSerializer,
    ProtocolSerializer,
    EndpointSerializer,
    CredentialSerializer,
    FileSerializer,
    LogSerializer,
    TestSerializer,
    TaskResultSerializer,
    CommandSchemaSerializer,
    AgentSchemaSerializer,
    CommandSerializer,
    MessageSerializer,
    ExecuteCommandSerializer
)
from backend.packages import install_agent
from backend.preprocessor import preprocess_dict, preprocess_list
import backend.statistics as stats
import backend.tasks as tasks

import jsonschema
import humanize

class DashboardViewSet(viewsets.ViewSet):
    # @action(detail=False, methods=['get'])
    
    # Bit of an abuse of semantics, but whatever
    def list(self, request):
        """
        Get all dashboard-related statistics.
        """
        
        # Note that the message length excludes header data.
        # XXX: Also, note that this is strictly Postgres-only. This moves us away 
        # from SQLite use entirely.
        all_msgs = Message.objects.annotate(msg_length=Func('payload', function='pg_column_size', output_field=IntegerField()))
        
        outgoing_msgs = all_msgs.filter(Q(source=None) | Q(source=uuid.UUID(int=0))).all()
        incoming_msgs = all_msgs.filter(~(Q(source=None) | Q(source=uuid.UUID(int=0)))).all()
        
        outgoing_vol = sum([msg.msg_length for msg in outgoing_msgs])
        incoming_vol = sum([msg.msg_length for msg in incoming_msgs])
        
        return Response(
            {
                "installed_agents": Agent.objects.count(),
                "registered_endpoints": Endpoint.objects.count(),
                "messages_sent": outgoing_msgs.count(),
                "messages_fetched": incoming_msgs.count(),
                "outgoing_volume": humanize.naturalsize(outgoing_vol),
                "incoming_volume": humanize.naturalsize(incoming_vol),
                "total_tasks": TaskResult.objects.count(),
                "ongoing_tasks": TaskResult.objects.filter(status="PENDING").count(),
                "successful_tasks": TaskResult.objects.filter(status="SUCCESS").count(),
                "failed_tasks": TaskResult.objects.filter(status="FAILURE").count(),
            }
        )

class TaskResultViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TaskResult.objects.all()
    serializer_class = TaskResultSerializer
    filter_backends = [DjangoFilterBackend]
    # allows ?status=PENDING to determine running tasks
    filterset_fields = ["status"] 
    
    @action(detail=True, methods=['get'])
    def get_task_metadata(self, request, pk=None):
        task: TaskResult = self.get_object()
        initiating_user: User = task.task_creator
        
        # This is always set, but it might not be accurate
        finish_time: str = task.date_done.isoformat()
        
        if task.status == "PENDING":
            finish_time = "(in progress)"
        
        # All tasks are currently on demand, and we don't have the information
        # to generate a source just yet.
        return Response(
            {
                "source": "unknown",
                "initiating_user": initiating_user.username,
                "type": "on demand",
                "start_time": task.date_created,
                "finish_time": finish_time
            }
        )
    
    @action(detail=False, methods=['get'])
    def get_task_stats(self, request):
        """
        Get the number of messages sent by both the agent and the server, 
        separately, for each hour in the last 24 hours.
        """
        return Response(stats.get_task_stats())
    
class MessageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    filter_backends = [DjangoFilterBackend]
    # filterset_fields = [
    #     "id",
    #     "name",
    # ]
    @action(detail=False, methods=['get'])
    def get_global_recent_stats(self, request):
        """
        Get the number of messages sent by both the agent and the server, 
        combined, for each hour in the last 24 hours.
        """
        res = stats.get_recent_global_message_stats()
        # Select just the message_id column, which amounts to the combined 
        # agent/server communications.
        return Response(list(res.message_id))

    @action(detail=False, methods=['get'])
    def get_split_recent_stats(self, request):
        """
        Get the number of messages sent by both the agent and the server, 
        separately, for each hour in the last 24 hours.
        """
        res = stats.get_recent_global_message_stats()
        # "source" refers to the number of communications sent by the agent in 
        # each hour. "destination" refers to the same, but for the server.
        return Response(
            {
                "sent_by_agent":list(res.source),
                "sent_by_server":list(res.destination)
            }
        )
    
    @action(detail=False, methods=['get'])
    def get_endpoint_stats(self, request):
        """
        Get the number of messages sent by each endpoint *ever*. No filtering
        is applied.
        """
        return Response(stats.get_endpoint_communication_stats())

class TestViewSet(viewsets.ViewSet):
    serializer_class = TestSerializer

    # POST
    def create(self, request, format=None):
        res = tasks.test_connection.delay()
        result = res.get()

        return Response({"task_id": res.id, "data": result})

    
class UserViewSet(viewsets.ViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    
    @action(detail=False, methods=['post'], permission_classes=[AllowAny]) # detail is false bc we're posting with no pk
    def sign_up(self, request):
        data = request.data
        serializer = self.serializer_class(data=data)
        if serializer.is_valid():
            account = serializer.save()
            token = Token.objects.create(user=account).key # might also be create instead of get
            response = {
                "message": "User created",
                "token": token,
                "data": serializer.data
            }
            return Response(data=response, status=status.HTTP_201_CREATED)
        return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def login(self, request):
        data = request.data
        account = get_object_or_404(User, username=data['username'])
        if not account.check_password(data['password']):
            return Response("missing user", status=status.HTTP_404_NOT_FOUND)
        token, created = Token.objects.get_or_create(user=account)
        serializer = self.serializer_class(account)
        response = {
                "message": "successfully logged in",
                "token": token.key,
                "data": serializer.data
            }
        return Response(data=response, status=status.HTTP_200_OK)


# Agents
class AgentViewSet(viewsets.ModelViewSet):
    queryset = Agent.objects.all()
    serializer_class = AgentSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["id", "name"]
    
    @action(detail=True, methods=['get'])
    def get_metadata(self, request, pk=None):
        agent: Agent = self.get_object()
        
        # Expects exactly one agent.
        serializer = AgentSchemaSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors)
        
        # Pass the agent config schema through the preprocessor
        metadata = agent.get_agent_metadata()
        
        # Attach the protocol metadata as another key
        metadata['protocol_config'] = agent.get_protocol_metadata()
        
        # Return preprocessed dictionary
        return Response(preprocess_dict(metadata))

    @action(detail=True, methods=['get'])
    def get_command_metadata(self, request, pk=None):
        """
        Return all command metadata *without preprocessing*.
        
        This does not support the filtering that the endpoint version of this
        API endpoint does, since this is intended to be used purely for displaying
        the available commands of an agent to a user. It is not intended
        to be used in generating forms.
        """
        agent: Agent = self.get_object()
        return Response(agent.get_command_metadata())

    @action(detail=False, methods=['get'])
    def get_endpoint_share(self, request):
        """
        Get the number of endpoints currently associated with each agent.
        """
        data = stats.get_agent_stats()
        
        # The lists will directly correspond, see
        # https://stackoverflow.com/questions/835092/python-dictionary-are-keys-and-values-always-the-same-order
        return Response(
            {
                "labels": list(data.keys()),
                "values": list(data.values())
            }
        )

class InstallAgentViewSet(viewsets.ViewSet):
    serializer_class = BundleSerializer

    # See https://www.reddit.com/r/django/comments/soebxo/rest_frameworks_filefield_how_can_i_force_using/
    # This forces all uploaded files to always manifest as an actual file on
    # the filesystem, rather than loading the file as something in memory.
    # The package manager only accepts real files, so this guarantees everything
    # ends up on the filesystem.
    def initialize_request(self, request, *args, **kwargs):
        request = super().initialize_request(request, *args, **kwargs)
        request.upload_handlers = [TemporaryFileUploadHandler(request=request)]
        return request

    # POST
    def create(self, request, format=None):
        data = request.data
        serializer = BundleSerializer(data=data)

        if not serializer.is_valid():
            return Response(serializer.errors)
        
        temp_path = Path(data['bundle_path'].temporary_file_path())
        
        # Copy the file to somewhere where it won't get instantly obliterated after
        # this request finishes (which is really quickly)
        bundle_dir = (Path(settings.MEDIA_ROOT) / "install_agent_uploads").resolve()
        bundle_dir.mkdir(exist_ok=True, parents=True)
        bundle_target = bundle_dir / temp_path.name
        shutil.copy2(temp_path, bundle_target)
    
        result = tasks.install_agent.delay(str(bundle_target), request.user.id)

        return Response({"task_id": result.id})


@api_view(["GET"])
def agents(request):
    agents = Agent.objects.all()
    serializer = AgentSerializer(
        agents, many=True
    )  # setting to true means to serialize multiple items. False is just one item
    return Response(serializer.data)


@api_view(["POST"])
def addAgent(request):
    serializer = AgentSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
    return Response(serializer.data)


# Credentials
class CredentialViewSet(viewsets.ModelViewSet):
    queryset = Credential.objects.all()
    serializer_class = CredentialSerializer


# Protocols
class ProtocolViewSet(viewsets.ModelViewSet):
    queryset = Protocol.objects.all()
    serializer_class = ProtocolSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = [
        "id",
        "name",
    ]

def start_command(endpoint: Endpoint, validated_data: dict[str, Any], user_id: int) -> AsyncResult:
        """
        Execute a command against an endpoint.
        
        `validated_data` is simply a dictionary with the following format:
        
        ```python
        {
            "cmd_name": str,
            "cmd_args": dict[str, Any]
        }
        ```
        """
        
        cmd_name = validated_data['cmd_name']
        cmd_args = validated_data['cmd_args']
        
        # Retrieve the JSON schema for this command, do not preprocess. Fail
        # if the command isn't found.
        command_metadata = endpoint.agent.get_command_metadata()
        commands = {cmd['name']: cmd for cmd in command_metadata}
        if cmd_name not in commands:
            raise ValidationError({"cmd_name": "Command is not valid for this endpoint!"})
        
        # Validate the incoming cmd_args against this schema
        #
        # Note that we can't use a serializer with a pre-defined schema, as with
        # https://pypi.org/project/drf-jsonschema/, since the schema is defined
        # at runtime. There are a few ways to get around this, but the stock
        # jsonschema is fine. 
        #
        # Additionally, note that jsonschema supports the anyOf syntax that is
        # normally removed by the preprocessor. We pass the raw Pydantic output
        # to jsonschema, since this does exactly what we want - validation
        # against the original. The absence of a non-required key is fine, since
        # when it reaches the agent, it should be assumed None. In our case, this
        # is guaranteed by Pydantic's model validation. Not necessarily true
        # for other libraries in other languages, but that's outside our scope.
        command_schema = commands[cmd_name]['argument_schema']
        validator = jsonschema.Draft202012Validator(command_schema)
        
        # Construct a validation error specifying failing fields that are
        # *close enough* to DRF's native format. When no 
        if not validator.is_valid(cmd_args):
            errors = {
                'global': [] # When tied to the overall schema
            }
            for error in validator.iter_errors(cmd_args):
                if not error.relative_path:
                    errors['global'].append(error.message)
                else:
                    errors[error.relative_path[-1]] = error.message
            raise ValidationError(errors)
        
        # If the command arguments pass, invoke the command execution task.
        # This also invokes a separate "receive message" subtask, which is started
        # at the end of the task and runs asynchronously. The user attribution
        # for the task is the same as the original command execution task.
        result = tasks.execute_command.delay(validated_data, str(endpoint.id), user_id)
        return result

# Endpoints
class EndpointViewSet(viewsets.ModelViewSet):
    queryset = Endpoint.objects.all()
    serializer_class = EndpointSerializer
    filter_backends = [DjangoFilterBackend]
    # filterset_fields = ['id', 'name', 'hostname', 'address', 'is_virtual', 'agent', 'protocols', 'encryption_key', 'hmac_key', 'connections']

    # The user can decide on the following fields. The ID is up to the agent to
    # generate.
    filterset_fields = [
        "name",
        "hostname",
        "address",
        "is_virtual",
        "agent",
        "connections",
    ]

    def create(self, request, *args, **kwargs):
        # This is overriden to change how the serializer returns. By spinning
        # up an asynchronous task, we can no longer bind the response to the
        # Endpoint result, since that would cause the request to return after a
        # *really* long time. Also, it might not even work, so it's better to just
        # return the task ID and return immediately.

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors)

        if serializer.data["is_virtual"]:
            raise ValidationError(
                {"is_virtual": "Virtual endpoints are not yet supported!"}
            )

        if not serializer.data["agent"]:
            raise ValidationError(
                {"agent": "An agent is required for non-virtual endpoints!"}
            )

        result = tasks.generate_payload.delay(serializer.data, request.user.id)

        # When implemented on the frontend, this should be used to redirect the
        # user to the task page.
        return Response({"task_id": result.id})

        # Synchronous version, used originally for debugging
        # tmp = tasks.generate_payload(serializer.data, request.user.id)
        # serializer_tmp = self.serializer_class(tmp)
        # return Response(serializer_tmp.data)

    # really, this should be a GET request, but i think the interface is "cleaner"
    @action(detail=True, methods=['get', 'post'])
    def get_command_metadata(self, request, pk=None):
        # Note that we expect an endpoint, not an agent, even though the response
        # would be the same across two endpoints of the same agent. This is to
        # emphasize that it should not be possible to get fine-grained, 
        # preprocessed metadata without a specific endpoint in mind.
        endpoint: Endpoint = self.get_object()
        
        # Verify the endpoint and command are valid...
        serializer = CommandSchemaSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors)
        
        metadata = preprocess_list(endpoint.agent.get_command_metadata())
        commands = {cmd['name']: cmd for cmd in metadata}
        
        # If no command was specialized, return the full list of commands,
        # preprocessed
        if 'command' not in serializer.data:
            return Response(metadata)
        
        # If a command was specified, but it doesn't exist for this endpoint
        # (i.e. it doesn't exist for this agent), then raise an error
        command = serializer.data['command']
        if command not in commands:
            raise ValidationError({"command": "Command is not valid for this endpoint!"})
    
        # Return the selected command, preprocessed
        return Response(commands[command])

    @action(detail=True, methods=['post'])
    def execute_command(self, request, pk=None):
        serializer = CommandSerializer(data=request.data)
        endpoint: Endpoint = self.get_object()
        
        if not serializer.is_valid():
            return Response(serializer.errors)
        
        try:
            result = start_command(endpoint, serializer.data, request.user.id)
        except Exception as e:
            return Response({"error": str(e)})

        # Return the task ID, which is intended to be used by the frontend
        # to bring the user to the relevant TaskResult detail page.
        return Response({"task_id": result.id})
    
    # This isn't idempotent. But on one hand, we're just getting data; on the other
    # hand, this violates what it means for something to be a GET endpoint, since
    # caching is NOT valid and this has side effects.
    @action(detail=True, methods=['get'])
    def get_messages(self, request, pk=None):
        """
        Start a task to get all new messages from an endpoint.
        """
        endpoint: Endpoint = self.get_object()
        result = tasks.receive_messages.delay(str(endpoint.id), request.user.id, None)
        return Response({"task_id": result.id})
        

class ExecuteCommandViewSet(viewsets.ViewSet):
    """
    Top-level access to command execution, primarily for debug so that we
    don't have to manually make POST requests since the form doesn't
    appear on the /endpoints/<id>/execute_command route
    """
    serializer_class = ExecuteCommandSerializer

    # POST
    def create(self, request, format=None):
        data = request.data
        serializer = ExecuteCommandSerializer(data=data)

        if not serializer.is_valid():
            return Response(serializer.errors)

        try:
            endpoint = Endpoint.objects.get(id=serializer.data["endpoint"])
            result = start_command(endpoint, serializer.data["cmd_data"], request.user.id)
        except Exception as e:
            return Response({"error": str(e)})

        return Response({"task_id": result.id})


# Files
class FileViewSet(viewsets.ModelViewSet):
    queryset = File.objects.all()
    serializer_class = FileSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = [
        "file_id",
        "task",
    ]


# Logs
def int_or(str, default):
    try: 
        ret = int(str)
    except ValueError:
        ret = default
    return ret
    
class LogPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'limit'

class LogViewSet(viewsets.ModelViewSet):
    queryset = Log.objects.all().order_by('id')
    serializer_class = LogSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    pagination_class = LogPagination
    filterset_fields = {
        'id': ['exact'],
        "category": ['exact'],
        "level": ['exact'],
        "source": ['exact'],
        "user": ['exact'],
        "task": ['exact'],
        "data": ['exact'],
        "timestamp": ['exact', 'gte', 'lte'],
    }
    # filter_class = LogFilter
    # ?search= will return on data only
    search_fields = ['data']
