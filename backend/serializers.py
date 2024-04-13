from typing import Any

from rest_framework import serializers
from rest_framework.validators import ValidationError
from backend.models import (
    Agent,
    Protocol,
    Endpoint,
    Credential,
    File,
    Log,
    Message
)
from django.contrib.auth.models import User
from django_celery_results.models import TaskResult


class TestSerializer(serializers.Serializer):
    test = serializers.CharField()

class TaskResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskResult
        fields = "__all__"

class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = "__all__"

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        # fields = '__all__'
        # fields = ['username', 'first_name', 'last_name', 'email', 'password', 'groups', 'user_permissions', 'is_staff', 'is_active', 'is_superuser', 'last_login', 'last_login', 'date_joined']
        fields = ['id', 'username', 'password']
    # def validate(self, attrs):
    #     email_exists = User.objects.filter(email=attrs['email']).exists()
    #     if email_exists:
    #         raise ValidationErrror("Email already in use!")
    #     return super().validate(attrs)

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = super().create(validated_data)
        user.set_password(password)
        user.save()
        return user

    def __str__(self):
        return self.username


class AgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agent
        fields = "__all__"
        # fields = ['name']


class BundleSerializer(serializers.Serializer):
    bundle_path = serializers.FileField(allow_empty_file=False)


class ProtocolSerializer(serializers.ModelSerializer):
    class Meta:
        model = Protocol
        fields = "__all__"
        # fields = ['name']


class EndpointSerializer(serializers.ModelSerializer):
    # agent = AgentSerializer()
    # protocols = ProtocolSerializer(many=True)
    class Meta:
        model = Endpoint
        fields = "__all__"


class PayloadSerializer(serializers.Serializer):
    """
    Serializer to generate a new Endpoint from a payload.

    This call is asynchronous and returns immediately.

    TODO: This call should return the task ID responsible for this call when
    we hook up Celery to the Django backend.

    TODO: There is no getAgentSchema endpoint (not yet).
    """

    # Generic build arguments, specific to the agent. It's expected the user
    # knows what the agent wants for its build arguments; this is normally
    # facilitiated by the getAgentSchema endpoint, which provides the user with
    # the schema - and therefore the structure - of the JSON form expected.
    build_args = serializers.JSONField()

class CredentialSerializer(serializers.ModelSerializer):
    # task = TaskSerializer()
    # credential_value = serializers.JSONField()
    class Meta:
        model = Credential
        fields = "__all__"
        # fields = ['id', 'credential_type']


class FileSerializer(serializers.ModelSerializer):
    # task = TaskSerializer()
    class Meta:
        model = File
        fields = "__all__"


class LogSerializer(serializers.ModelSerializer):
    # source = EndpointSerializer()
    # task = TaskSerializer()
    # task_result = TaskResultSerializer()
    class Meta:
        model = Log
        fields = "__all__"

class CommandSchemaSerializer(serializers.Serializer):
    """
    Serializer used to request the JSON schema for either all commands associated
    with an endpoint, or a specific command for that endpoint.
    """
    # endpoint = serializers.UUIDField() # PK of the endpoint, a UUID
    # endpoint = EndpointSerializer(read_only=True)
    command = serializers.CharField(required=False) # By command name, optional

class AgentSchemaSerializer(serializers.Serializer):
    # agent = serializers.IntegerField() # PK of agent
    agent = AgentSerializer(read_only=True)
    
    
class CommandSerializer(serializers.Serializer):
    # The command name.
    cmd_name = serializers.CharField(required=True)
    # The unvalidated command arguments.
    cmd_args = serializers.JSONField(required=True)
    
    
class ExecuteCommandSerializer(serializers.Serializer):
    endpoint = serializers.PrimaryKeyRelatedField(queryset=Endpoint.objects.all())
    cmd_data = CommandSerializer()