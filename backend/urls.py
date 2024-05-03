from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from backend import views

from rest_framework import routers
from rest_framework.authtoken.views import obtain_auth_token

router = routers.DefaultRouter()
router.register(r"agents", views.AgentViewSet, basename="agents")
router.register(r"protocols", views.ProtocolViewSet, basename="protocols")
router.register(r"endpoints", views.EndpointViewSet, basename="endpoints")
router.register(r"credentials", views.CredentialViewSet, basename="credentials")
router.register(r"files", views.FileViewSet, basename="files")
router.register(r"logs", views.LogViewSet, basename="logs")
router.register(r"users", views.UserViewSet, basename="user")
router.register(r"installAgent", views.InstallAgentViewSet, basename="installAgent")
router.register(r"test", views.TestViewSet, basename="test")
router.register(r"taskresults", views.TaskResultViewSet, basename="taskresults")
router.register(r"messages", views.MessageViewSet, basename="messages")
router.register(r"dashboard", views.DashboardViewSet, basename="dashboard")
router.register(r"executeCommand", views.ExecuteCommandViewSet, basename="executeCommand")
router.register(r"chat", views.ChatViewSet, basename="chat")

urlpatterns = [
    # path('/', views.credentials),
    # path('/agents', views.agents),
    # path(r'^', include(router.urls)),
    path("/", include(router.urls)),
    path('get_token/', obtain_auth_token, name='login'),
    path('api_login/', include('rest_framework.urls')),
    # path('/signUp/', views.signUp),
    # path('/signUpGeneric/', views.SignUpView.as_view(), name='signupgeneric'),
    # path('/credentials', views.credentials), # rememeber that this is backend/credentials on the server
    # path('/addCredential/', views.addCredential),
    # path('/protocols', views.protocols),
    # path('/endpoints', views.endpoints),
    # path('/tasks', views.tasks),
    # path('/taskresults', views.credentials),
    # path('/files', views.files),
    # path('/logs', views.logs),
]
