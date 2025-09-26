from django.urls import re_path

from general import views

app_name = "general"


urlpatterns = [
    re_path(r"^admin/reset_database/$", views.reset_database, name="reset_database"),
    re_path(r"^admin/backup_all/$", views.backup_all, name="backup_all"),
    re_path(r"^admin/restore_all/$", views.restore_all, name="restore_all"),
]
